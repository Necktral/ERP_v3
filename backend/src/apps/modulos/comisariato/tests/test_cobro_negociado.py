"""Cobro NEGOCIADO al pagar (CO-PA): abono parcial por deuda + pago del neto a entregar.

Ejemplo del dueño: préstamo C$12.000 + comisariato C$3.000, gana C$8.000 → negocia abonar
C$2.000 al préstamo y C$1.000 al comisariato → neto a entregar C$5.000; deudas a 10.000 / 2.000.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.nomina.models import (
    PayrollEntry,
    PayrollPeriod,
    PayrollSheet,
    PeriodStatus,
    PeriodType,
    SalaryType,
)
from apps.kernels.portfolio.models import Credit, Receivable
from apps.kernels.portfolio.services import create_credit, create_receivable, disburse_credit
from apps.modulos.comisariato.models import CustomerCreditAccount, CustomerSegment
from apps.modulos.comisariato.pay_negotiated import (
    CobrarPagarError,
    cobrar_y_pagar,
    deudas_por_planilla,
    rectificar_cobro,
)
from apps.modulos.iam.models import OrgUnit
from apps.modulos.org.models import IntercompanyRelationship
from apps.modulos.parties.models import Party

User = get_user_model()
pytestmark = pytest.mark.django_db

CED = "001-010190-0001X"


def _req(actor, company):
    return SimpleNamespace(user=actor, META={}, company=company, branch=None, _request=None, request_id="r", path="", method="POST")


def _setup(*, devengado="8000.00", comisariato="3000.00", prestamo="12000.00", relacion=True,
           carnet="", cedula=CED):
    t = uuid.uuid4().hex[:6]
    actor = User.objects.create_user(username=f"u{t}", email=f"{t}@t.local", password="x")
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H{t}")
    finca = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name=f"Finca{t}", parent=holding)
    comis = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name=f"Comis{t}", parent=holding)

    # Multi-empresa: el cobro cross-company del comisariato EXIGE la relación CXC declarada
    # finca↔comisariato (es la relación de empresas #3 del CO-PA). El préstamo es intra-finca.
    if relacion:
        IntercompanyRelationship.objects.create(
            company_a=finca, company_b=comis,
            relationship_type=IntercompanyRelationship.RelationshipType.CXC, is_active=True,
        )

    period = PayrollPeriod.objects.create(
        company=finca, year=2026, month=6, period_type=PeriodType.SECOND_HALF,
        start_date=date(2026, 6, 16), end_date=date(2026, 6, 30), working_days=15, status=PeriodStatus.APPROVED,
    )
    sheet = PayrollSheet.objects.create(period=period, sheet_name="FINCA", has_inss=False)
    entry = PayrollEntry.objects.create(
        sheet=sheet, full_name="Juan Demo", cedula=cedula, worker_code=carnet, has_inss=False,
        salary_type=SalaryType.MONTHLY, base_salary_nio=Decimal(devengado),
        days_in_period=15, days_worked=Decimal("15.00"),
        total_devengado=Decimal(devengado), total_deductions=Decimal("0.00"), net_to_pay=Decimal(devengado),
    )

    # Comisariato: cuenta EMPLOYEE (cobra la finca) + CxC (deuda). Identidad por carnet y/o cédula.
    p_comis = Party.objects.create(
        company=comis, party_type="NATURAL", display_name="Juan Demo", national_id=cedula, worker_code=carnet
    )
    CustomerCreditAccount.objects.create(
        company=comis, party=p_comis, segment=CustomerSegment.EMPLOYEE, collecting_company=finca, is_active=True
    )
    create_receivable(
        company=comis, party=p_comis, reference_type="DEMO", reference_id=entry.id,
        principal_amount=Decimal(comisariato), currency="NIO",
        issue_date=date(2026, 6, 1), due_date=date(2026, 6, 30), created_by=actor,
    )

    # Préstamo personal: Credit en la finca (borrower por carnet/cédula)
    p_borrower = Party.objects.create(
        company=finca, party_type="NATURAL", display_name="Juan Demo", national_id=cedula, worker_code=carnet
    )
    p_lender = Party.objects.create(company=finca, party_type="INTERNAL", display_name="Finca", national_id="")
    cr = create_credit(
        company=finca, credit_type="TERM_LOAN", lender_party=p_lender, borrower_party=p_borrower,
        approved_amount=Decimal(prestamo), currency="NIO", interest_rate=Decimal("0"), term_months=6,
        maturity_date=date(2026, 12, 31), created_by=actor,
    )
    disburse_credit(credit=cr, disbursed_amount=Decimal(prestamo), disbursement_date=date(2026, 6, 1), disbursed_by=actor)
    return actor, finca, entry


def _com_outstanding(finca):
    return sum((r.outstanding_amount for r in Receivable.objects.exclude(company=finca)), Decimal("0.00"))


def _loan_outstanding(finca):
    return sum((c.outstanding_amount for c in Credit.objects.filter(company=finca)), Decimal("0.00"))


def test_cobro_parcial_negociado_paga_neto_y_baja_deudas():
    actor, finca, entry = _setup()
    res = cobrar_y_pagar(
        request=_req(actor, finca), actor=actor, entry=entry,
        abono_comisariato=Decimal("1000.00"), abono_prestamo=Decimal("2000.00"),
        payment_method="CASH", idempotency_key="t-1",
    )
    assert res["neto_entregado"] == "5000.00"
    assert res["abono_comisariato"] == "1000.00"
    assert res["abono_prestamo"] == "2000.00"

    entry.refresh_from_db()
    assert entry.store_credit_deduction == Decimal("1000.00")
    assert entry.loan_payment == Decimal("2000.00")
    assert entry.net_to_pay == Decimal("5000.00")
    assert sum((p.amount for p in entry.payments.all()), Decimal("0.00")) == Decimal("5000.00")

    assert _com_outstanding(finca) == Decimal("2000.00")  # 3000 − 1000
    assert _loan_outstanding(finca) == Decimal("10000.00")  # 12000 − 2000


def test_abono_cero_paga_todo_sin_tocar_deuda():
    actor, finca, entry = _setup()
    res = cobrar_y_pagar(
        request=_req(actor, finca), actor=actor, entry=entry,
        abono_comisariato=Decimal("0"), abono_prestamo=Decimal("0"),
        payment_method="CASH", idempotency_key="t-0",
    )
    assert res["neto_entregado"] == "8000.00"
    assert _com_outstanding(finca) == Decimal("3000.00")
    assert _loan_outstanding(finca) == Decimal("12000.00")


def test_abono_excede_saldo_rechaza():
    actor, finca, entry = _setup()
    with pytest.raises(CobrarPagarError):
        cobrar_y_pagar(
            request=_req(actor, finca), actor=actor, entry=entry,
            abono_comisariato=Decimal("5000.00"), abono_prestamo=Decimal("0"),  # > 3000
            payment_method="CASH", idempotency_key="t-x",
        )


def test_abono_deja_neto_negativo_rechaza():
    actor, finca, entry = _setup()
    with pytest.raises(CobrarPagarError):
        cobrar_y_pagar(
            request=_req(actor, finca), actor=actor, entry=entry,
            abono_comisariato=Decimal("3000.00"), abono_prestamo=Decimal("6000.00"),  # 9000 > 8000
            payment_method="CASH", idempotency_key="t-neg",
        )


def test_idempotente_no_duplica():
    actor, finca, entry = _setup()
    kwargs = dict(
        request=_req(actor, finca), actor=actor, entry=entry,
        abono_comisariato=Decimal("1000.00"), abono_prestamo=Decimal("2000.00"),
        payment_method="CASH", idempotency_key="t-dup",
    )
    r1 = cobrar_y_pagar(**kwargs)
    r2 = cobrar_y_pagar(**kwargs)
    assert r1["payment_id"] == r2["payment_id"]
    entry.refresh_from_db()
    assert sum((p.amount for p in entry.payments.all()), Decimal("0.00")) == Decimal("5000.00")  # no doble pago
    assert _loan_outstanding(finca) == Decimal("10000.00")  # no doble abono


def test_sin_relacion_de_empresas_no_se_cobra_comisariato():
    """Multi-empresa: sin la relación CXC declarada finca↔comisariato, el comisariato (otra
    empresa) NO se cruza → su saldo es 0 y abonarle se rechaza. El préstamo (intra-finca) sigue."""
    actor, finca, entry = _setup(relacion=False)
    # Comisariato: sin relación → saldo 0 → abonar al comisariato se rechaza.
    with pytest.raises(CobrarPagarError):
        cobrar_y_pagar(
            request=_req(actor, finca), actor=actor, entry=entry,
            abono_comisariato=Decimal("1000.00"), abono_prestamo=Decimal("0"),
            payment_method="CASH", idempotency_key="t-norel",
        )
    # Préstamo personal (Credit en la propia finca) NO depende de la relación: sí se puede abonar.
    res = cobrar_y_pagar(
        request=_req(actor, finca), actor=actor, entry=entry,
        abono_comisariato=Decimal("0"), abono_prestamo=Decimal("2000.00"),
        payment_method="CASH", idempotency_key="t-rel-pre",
    )
    assert res["abono_prestamo"] == "2000.00"
    assert _loan_outstanding(finca) == Decimal("10000.00")


def test_rectificar_cobro_corrige_monto_y_anula_recibo():
    """El pagador puso 200 y eran 2000: rectifica → reversa el 200, cobra 2000 y anula el recibo."""
    actor, finca, entry = _setup()
    r1 = cobrar_y_pagar(
        request=_req(actor, finca), actor=actor, entry=entry,
        abono_comisariato=Decimal("200.00"), abono_prestamo=Decimal("0"),
        payment_method="CASH", idempotency_key="t-err",
    )
    recibo_previo = r1["payment_id"]
    assert _com_outstanding(finca) == Decimal("2800.00")  # 3000 − 200
    entry.refresh_from_db()
    assert entry.net_to_pay == Decimal("7800.00")  # 8000 − 200

    r2 = rectificar_cobro(
        request=_req(actor, finca), actor=actor, entry=entry,
        abono_comisariato=Decimal("2000.00"), abono_prestamo=Decimal("0"),
        payment_method="CASH", motivo="Tecleó 200 en vez de 2000", idempotency_key="t-rec",
    )
    assert r2["recibo_anulado"] == recibo_previo
    assert r2["motivo"]
    assert r2["abono_comisariato"] == "2000.00"
    assert r2["neto_entregado"] == "6000.00"  # 8000 − 2000

    entry.refresh_from_db()
    assert entry.store_credit_deduction == Decimal("2000.00")
    assert entry.net_to_pay == Decimal("6000.00")
    # El abono errado quedó reversado y el correcto aplicado: 3000 − 2000 = 1000.
    assert _com_outstanding(finca) == Decimal("1000.00")
    # Solo queda el pago nuevo (el previo se anuló) por el neto corregido.
    pagos = list(entry.payments.all())
    assert len(pagos) == 1
    assert pagos[0].amount == Decimal("6000.00")
    assert pagos[0].id != recibo_previo


def test_deudas_por_planilla_batch_por_carnet():
    """El resumen de deudas (batcheado, endpoint del CO-PA) cruza por carnet sin cédula."""
    actor, finca, entry = _setup(carnet="W-008888", cedula="")
    rows = deudas_por_planilla(period=entry.sheet.period)
    fila = next(r for r in rows if r["entry_id"] == entry.id)
    assert fila["worker_code"] == "W-008888"
    assert fila["comisariato_saldo"] == "3000.00"
    assert fila["prestamo_saldo"] == "12000.00"


def test_deudas_por_planilla_sin_relacion_comisariato_cero():
    """Sin relación CXC, el comisariato (otra empresa) no se cruza → saldo 0; el préstamo sí (intra-finca)."""
    actor, finca, entry = _setup(relacion=False)
    fila = next(r for r in deudas_por_planilla(period=entry.sheet.period) if r["entry_id"] == entry.id)
    assert fila["comisariato_saldo"] == "0.00"
    assert fila["prestamo_saldo"] == "12000.00"


def test_cobro_por_carnet_sin_cedula():
    """Trabajador SIN cédula: el cruce comisariato/préstamo se hace por el CARNET (ID del holding)."""
    actor, finca, entry = _setup(carnet="W-009999", cedula="")
    assert entry.cedula == ""
    assert entry.worker_code == "W-009999"

    # La deuda se encuentra por carnet (antes, sin cédula, salía 0 y no se podía cobrar).
    res = cobrar_y_pagar(
        request=_req(actor, finca), actor=actor, entry=entry,
        abono_comisariato=Decimal("1000.00"), abono_prestamo=Decimal("2000.00"),
        payment_method="CASH", idempotency_key="t-carnet",
    )
    assert res["abono_comisariato"] == "1000.00"
    assert res["abono_prestamo"] == "2000.00"
    assert _com_outstanding(finca) == Decimal("2000.00")  # 3000 − 1000
    assert _loan_outstanding(finca) == Decimal("10000.00")  # 12000 − 2000


def test_rectificar_sin_motivo_rechaza():
    actor, finca, entry = _setup()
    cobrar_y_pagar(
        request=_req(actor, finca), actor=actor, entry=entry,
        abono_comisariato=Decimal("200.00"), abono_prestamo=Decimal("0"),
        payment_method="CASH", idempotency_key="t-err2",
    )
    with pytest.raises(CobrarPagarError):
        rectificar_cobro(
            request=_req(actor, finca), actor=actor, entry=entry,
            abono_comisariato=Decimal("2000.00"), abono_prestamo=Decimal("0"),
            payment_method="CASH", motivo="   ", idempotency_key="t-rec2",
        )
