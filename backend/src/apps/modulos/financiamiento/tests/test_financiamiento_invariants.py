"""Invariantes de negocio del vertical FINANCIAMIENTO (QA negocio).

Ataca, con números concretos y casos borde, los invariantes propios del SIFA:
  - DOBLE SALDO C$/US$: el préstamo mantiene saldos INDEPENDIENTES en dos
    `portfolio.Credit`; abonar a una moneda NO mueve la otra.
  - CAFÉ EN CUSTODIA HASTA FIJACIÓN: el café recibido entra a custodia (costo 0)
    y solo la liquidación (COFFEE_QUOTA) reduce el saldo de la moneda fijada.
  - MONTE CARLO REPRODUCIBLE: misma semilla ⇒ mismo resultado; el VaR puede ser 0
    aunque la pérdida esperada sea > 0 cuando la mora es rara (NO es bug).
  - La PD heurística determinista corre SIEMPRE; el Random Forest es opcional
    (kill switch + sklearn) — estos tests NO dependen de sklearn.

Archivo NUEVO de QA: no edita producción ni tests existentes. Reusa los fixtures
de estilo de `test_financing.py`/`test_risk.py`.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.kernels.inventarios.models import InventoryItem, StockBalance, UoM
from apps.kernels.inventarios.services import create_warehouse
from apps.modulos.financiamiento import risk
from apps.modulos.financiamiento import services as fin
from apps.modulos.financiamiento.models import Currency, FixationStatus, LoanStatus
from apps.modulos.iam.models import OrgUnit
from apps.modulos.parties.models import Party

User = get_user_model()
UT = OrgUnit.UnitType


# --------------------------------------------------------------------------- #
# Helpers (espejan test_financing.py)
# --------------------------------------------------------------------------- #

def _scope():
    t = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=UT.HOLDING, name=f"H{t}", code=f"H-{t}")
    company = OrgUnit.objects.create(unit_type=UT.COMPANY, parent=holding, name=f"C{t}", code=f"C-{t}")
    branch = OrgUnit.objects.create(unit_type=UT.BRANCH, parent=company, name=f"B{t}", code=f"B-{t}")
    return holding, company, branch


def _user():
    t = uuid.uuid4().hex[:8]
    return User.objects.create_user(username=f"u_{t}", email=f"u_{t}@t.local", password="pass12345")


def _req(company, branch, user):
    return SimpleNamespace(
        company=company, branch=branch, user=user, META={}, headers={},
        path="/test/financiamiento/", method="POST", request_id=f"req-{uuid.uuid4().hex[:8]}",
    )


def _producer(company, name="Cooperativa Las Brumas", acopio="02-001"):
    party = Party.objects.create(
        company=company, party_type=Party.PartyType.NATURAL, display_name=name,
        national_id=f"001-{uuid.uuid4().hex[:9]}",
    )
    return fin.create_producer(company=company, party=party, acopio_code=acopio)


def _setup_acopio(req, company, branch, actor):
    custody = create_warehouse(
        request=req, company=company, branch=branch, actor_user=actor, name="Custodia", code="CUST",
    )
    own = create_warehouse(
        request=req, company=company, branch=branch, actor_user=actor, name="Propia", code="PROP",
    )
    item = InventoryItem.objects.create(
        company=company, sku=f"CAFE-{uuid.uuid4().hex[:6]}", name="Café pergamino", uom=UoM.POUND,
    )
    row = fin.get_or_create_settings(company=company)
    row.coffee_item = item
    row.custody_warehouse = custody
    row.liquidation_warehouse = own
    row.save()
    quality = fin.create_quality_grade(
        company=company, code="A", name="Primera", default_tare_pct=Decimal("0.00"),
    )
    return custody, own, item, quality


def _dual_loan(req, company, *, oficial, comite, admin, nio="10000.00", usd="1000.00"):
    producer = _producer(company)
    app = fin.create_application(
        company=company, producer=producer, actor=oficial,
        requested_nio=Decimal(nio), requested_usd=Decimal(usd), term_months=8,
        credit_type="AVIO", activity="Mantenimiento de café",
        interest_rate=Decimal("12.00"), penalty_rate=Decimal("4.00"), commission_rate=Decimal("2.00"),
        guarantee_farm_area_mz=Decimal("25.00"), guarantee_coffee_qq=Decimal("150.00"),
    )
    fin.submit_application(application=app)
    fin.approve_application(application=app, actor=comite, request=req)
    loan = fin.disburse_loan(request=_req(company, req.branch, admin), actor=admin, application=app)
    return app, loan


def _stock(company, branch, wh, item) -> Decimal:
    bal = StockBalance.objects.filter(company=company, branch=branch, warehouse=wh, item=item).first()
    return bal.qty_on_hand if bal else Decimal("0.0000")


# ===========================================================================
# DOBLE SALDO C$/US$ — saldos independientes por moneda
# ===========================================================================

@pytest.mark.django_db
def test_doble_saldo_independiente_dos_credits():
    """El préstamo dual envuelve DOS portfolio.Credit, uno por moneda, con saldos
    independientes. Con comisión 2%: outstanding = principal + fee."""
    _h, company, branch = _scope()
    oficial, comite, admin = _user(), _user(), _user()
    req = _req(company, branch, admin)
    _setup_acopio(req, company, branch, admin)
    _app, loan = _dual_loan(req, company, oficial=oficial, comite=comite, admin=admin,
                            nio="10000.00", usd="1000.00")

    assert loan.credit_nio is not None and loan.credit_usd is not None
    assert loan.credit_nio.id != loan.credit_usd.id
    assert loan.credit_nio.currency == Currency.NIO
    assert loan.credit_usd.currency == Currency.USD
    # 10000 + 2% comisión = 10200; 1000 + 2% = 1020.
    assert loan.credit_nio.outstanding_amount == Decimal("10200.00")
    assert loan.credit_usd.outstanding_amount == Decimal("1020.00")


@pytest.mark.django_db
def test_abono_nio_no_toca_saldo_usd():
    """Abonar al saldo en córdobas NO altera el saldo en dólares (aislamiento por moneda)."""
    _h, company, branch = _scope()
    oficial, comite, admin = _user(), _user(), _user()
    req = _req(company, branch, admin)
    _setup_acopio(req, company, branch, admin)
    _app, loan = _dual_loan(req, company, oficial=oficial, comite=comite, admin=admin,
                            nio="10000.00", usd="1000.00")
    usd_antes = loan.credit_usd.outstanding_amount

    out = fin.register_loan_payment(
        request=req, actor=admin, loan=loan, amount=Decimal("3000.00"),
        paid_currency=Currency.NIO, payment_method="CASH",
    )
    assert out["target_currency"] == Currency.NIO
    assert out["outstanding"] == "7200.00"  # 10200 - 3000

    loan.credit_nio.refresh_from_db()
    loan.credit_usd.refresh_from_db()
    assert loan.credit_nio.outstanding_amount == Decimal("7200.00")
    # El saldo en dólares queda intacto.
    assert loan.credit_usd.outstanding_amount == usd_antes == Decimal("1020.00")


@pytest.mark.django_db
def test_estado_de_cuenta_separa_y_consolida_con_tasa():
    """El estado de cuenta reporta cada moneda por separado y consolida en C$ con la tasa."""
    _h, company, branch = _scope()
    oficial, comite, admin = _user(), _user(), _user()
    req = _req(company, branch, admin)
    _setup_acopio(req, company, branch, admin)
    fin.set_exchange_rate(company=company, rate_date=timezone.localdate(), rate=Decimal("36.50"))
    _app, loan = _dual_loan(req, company, oficial=oficial, comite=comite, admin=admin,
                            nio="10000.00", usd="1000.00")

    st = fin.loan_statement(loan=loan)
    assert st["balances"]["NIO"]["outstanding"] == "10200.00"
    assert st["balances"]["USD"]["outstanding"] == "1020.00"
    # Consolidado = 10200 + 1020 × 36.50 = 10200 + 37230 = 47430.00
    assert st["consolidated_nio"] == "47430.00"
    # rate_used preserva la precisión del modelo (decimal_places=6).
    assert Decimal(st["rate_used"]) == Decimal("36.50")


# ===========================================================================
# CAFÉ EN CUSTODIA HASTA FIJACIÓN; liquidación COFFEE_QUOTA reduce el saldo correcto
# ===========================================================================

@pytest.mark.django_db
def test_cafe_en_custodia_hasta_fijacion():
    """El café recibido entra a CUSTODIA (sigue disponible para fijar) y no se compra
    hasta la liquidación: stock en custodia, nada en bodega propia, costo 0."""
    _h, company, branch = _scope()
    admin = _user()
    req = _req(company, branch, admin)
    custody, own, item, quality = _setup_acopio(req, company, branch, admin)
    producer = _producer(company)

    fin.receive_coffee(
        request=req, actor=admin, producer=producer, quality=quality,
        physical_state="HUMEDO", sacks=20, gross_lb=Decimal("2000.00"), tare_lb=Decimal("0.00"),
    )
    # El café está en custodia, no en bodega propia.
    assert _stock(company, branch, custody, item) == Decimal("2000.0000")
    assert _stock(company, branch, own, item) == Decimal("0.0000")
    dep = fin.producer_deposit_balance(producer=producer)
    assert dep["received_lb"] == "2000.00"
    assert dep["available_lb"] == "2000.00"  # todo disponible (nada fijado)
    assert dep["in_custody_lb"] == "2000.00"

    # Fijar compromete las libras (salen del disponible) pero NO mueve el inventario.
    fin.fix_price(company=company, producer=producer, pounds=Decimal("1200.00"),
                  price_per_lb=Decimal("0.80"), currency=Currency.USD)
    dep = fin.producer_deposit_balance(producer=producer)
    assert dep["available_lb"] == "800.00"      # 2000 - 1200 fijadas
    assert dep["in_custody_lb"] == "2000.00"    # físicamente sigue todo en custodia
    assert _stock(company, branch, own, item) == Decimal("0.0000")  # aún sin comprar


@pytest.mark.django_db
def test_liquidacion_coffee_quota_reduce_saldo_usd_correcto():
    """La liquidación (COFFEE_QUOTA) de una fijación en US$ abona el saldo en US$,
    deja el saldo en C$ intacto, y mueve el café de custodia a bodega propia."""
    _h, company, branch = _scope()
    oficial, comite, admin = _user(), _user(), _user()
    req = _req(company, branch, admin)
    custody, own, item, quality = _setup_acopio(req, company, branch, admin)
    fin.set_exchange_rate(company=company, rate_date=timezone.localdate(), rate=Decimal("36.50"))
    _app, loan = _dual_loan(req, company, oficial=oficial, comite=comite, admin=admin,
                            nio="10000.00", usd="1000.00")
    producer = loan.producer
    nio_antes = loan.credit_nio.outstanding_amount  # 10200

    fin.receive_coffee(
        request=req, actor=admin, producer=producer, quality=quality,
        physical_state="SECO", sacks=15, gross_lb=Decimal("1500.00"), tare_lb=Decimal("0.00"),
    )
    # 1000 lb × 0.80 USD = 800 USD bruto.
    fx = fin.fix_price(company=company, producer=producer, pounds=Decimal("1000.00"),
                       price_per_lb=Decimal("0.80"), currency=Currency.USD)

    liq = fin.liquidate(request=req, actor=admin, producer=producer, fixation_ids=[fx.pk], loan=loan)

    # Abono al saldo en US$ (la moneda de la fijación) = min(800, 1020) = 800.
    assert liq.applied_currency == Currency.USD
    assert liq.applied_to_loan == Decimal("800.00")
    assert liq.gross_value == Decimal("800.00")
    assert liq.surplus_amount == Decimal("0.00")  # todo el valor neto fue al préstamo

    loan.credit_usd.refresh_from_db()
    loan.credit_nio.refresh_from_db()
    assert loan.credit_usd.outstanding_amount == Decimal("220.00")  # 1020 - 800
    # El saldo en córdobas NO se tocó.
    assert loan.credit_nio.outstanding_amount == nio_antes == Decimal("10200.00")

    fx.refresh_from_db()
    assert fx.status == FixationStatus.LIQUIDATED
    assert loan.status == LoanStatus.ACTIVE  # aún debe

    # El café fijado salió de custodia y entró a bodega propia con costo de compra.
    assert _stock(company, branch, custody, item) == Decimal("500.0000")  # 1500 - 1000
    assert _stock(company, branch, own, item) == Decimal("1000.0000")


@pytest.mark.django_db
def test_liquidacion_sin_prestamo_todo_excedente():
    """Una fijación liquidada SIN préstamo no reduce ningún saldo: todo es excedente CxP."""
    _h, company, branch = _scope()
    admin = _user()
    req = _req(company, branch, admin)
    _custody, _own, _item, _quality = _setup_acopio(req, company, branch, admin)
    fin.set_exchange_rate(company=company, rate_date=timezone.localdate(), rate=Decimal("36.50"))
    producer = _producer(company)
    quality = fin.create_quality_grade(company=company, code="B", name="Segunda")
    fin.receive_coffee(
        request=req, actor=admin, producer=producer, quality=quality,
        physical_state="SECO", sacks=10, gross_lb=Decimal("1000.00"), tare_lb=Decimal("0.00"),
    )
    fx = fin.fix_price(company=company, producer=producer, pounds=Decimal("1000.00"),
                       price_per_lb=Decimal("0.80"), currency=Currency.USD)
    liq = fin.liquidate(request=req, actor=admin, producer=producer, fixation_ids=[fx.pk])
    assert liq.applied_to_loan == Decimal("0.00")
    assert liq.surplus_amount == Decimal("800.00")  # 1000 × 0.80, sin retenciones


# ===========================================================================
# MONTE CARLO — reproducible por semilla; VaR puede ser 0 con E[L] > 0
# ===========================================================================

def test_montecarlo_misma_semilla_mismo_resultado():
    """Reproducibilidad: misma semilla y mismas posiciones ⇒ resultado idéntico."""
    pos = [{"pd": 0.2, "loss_given_default": 1500.0},
           {"pd": 0.4, "loss_given_default": 2500.0}]
    a = risk.simulate_portfolio_loss(pos, simulations=4000, seed=2026)
    b = risk.simulate_portfolio_loss(pos, simulations=4000, seed=2026)
    assert a == b
    assert a["seed"] == 2026 and a["simulaciones"] == 4000


def test_montecarlo_var_puede_ser_cero_con_esperada_positiva():
    """Con mora RARA (PD muy baja) y pocas posiciones, el VaR95 puede ser 0
    aunque la pérdida esperada sea > 0. ESO NO ES BUG: no aseveramos VaR>esperada.
    Solo exigimos los invariantes monótonos del percentil."""
    pos = [{"pd": 0.001, "loss_given_default": 100000.0}]
    r = risk.simulate_portfolio_loss(pos, simulations=10000, seed=20260614, rho=0.15)
    esperada = float(r["perdida_esperada"])
    var95 = float(r["var_95"])
    var99 = float(r["var_99"])
    # E[L] ≈ 0.001 × 100000 = 100 > 0; el VaR95 (percentil 95) cae en escenarios SIN incumplimiento ⇒ 0.
    assert esperada > 0.0
    assert var95 == 0.0
    # Invariantes que SIEMPRE valen, sin aseverar VaR>esperada.
    assert var99 >= var95 >= 0.0
    assert float(r["perdida_maxima"]) >= esperada >= 0.0


@pytest.mark.django_db
def test_build_risk_package_usa_heuristica_sin_sklearn():
    """En tests la IA está apagada ⇒ PD por heurística determinista (sin depender de sklearn)."""
    _h, company, branch = _scope()
    oficial, comite, admin = _user(), _user(), _user()
    req = _req(company, branch, admin)
    _setup_acopio(req, company, branch, admin)
    _dual_loan(req, company, oficial=oficial, comite=comite, admin=admin, nio="10000.00", usd="1000.00")

    pkg = risk.build_risk_package(company, simulations=2000, seed=1)
    assert pkg["prestamos_activos"] == 1
    assert pkg["ai_used"] is False
    assert pkg["detalle"][0]["fuente_pd"] == "heuristica"
    sim = pkg["simulacion"]
    assert sim is not None
    assert float(sim["var_99"]) >= float(sim["var_95"]) >= 0.0
    assert float(sim["perdida_maxima"]) >= float(sim["perdida_esperada"]) >= 0.0
