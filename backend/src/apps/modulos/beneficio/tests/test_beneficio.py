"""Tests del beneficio: ciclo completo con costo absorbido exacto, merma/rendimiento,
alerta de rendimiento anómalo (antifraude de báscula) y estados ilegales."""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.inventarios.models import InventoryItem, StockBalance, UoM
from apps.kernels.inventarios.services import create_warehouse, post_receive
from apps.modulos.alertas.models import Alert
from apps.modulos.beneficio import services as ben
from apps.modulos.beneficio.models import OrderStatus
from apps.modulos.beneficio.services import BeneficioError
from apps.modulos.iam.models import OrgUnit

User = get_user_model()
UT = OrgUnit.UnitType


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
        path="/test/beneficio/", method="POST", request_id=f"req-{uuid.uuid4().hex[:8]}",
    )


def _setup(req, company, branch, actor, *, pergamino_lb="1000.00", cost_per_lb="29.20"):
    wh_in = create_warehouse(request=req, company=company, branch=branch, actor_user=actor,
                             name="Bodega Pergamino", code="BPER")
    wh_out = create_warehouse(request=req, company=company, branch=branch, actor_user=actor,
                              name="Bodega Oro", code="BORO")
    pergamino = InventoryItem.objects.create(
        company=company, sku=f"PER-{uuid.uuid4().hex[:6]}", name="Café pergamino", uom=UoM.POUND,
    )
    oro = InventoryItem.objects.create(
        company=company, sku=f"ORO-{uuid.uuid4().hex[:6]}", name="Café oro", uom=UoM.POUND,
    )
    post_receive(
        request=req, actor=actor, warehouse_id=wh_in.id, item_id=pergamino.id,
        qty=Decimal(pergamino_lb), unit_cost=Decimal(cost_per_lb),
        idempotency_key=f"seed-{uuid.uuid4().hex}",
    )
    recipe = ben.create_recipe(
        company=company, code="PER-ORO", name="Pergamino a oro",
        input_item=pergamino, output_item=oro,
        expected_yield_pct=Decimal("50.00"), yield_tolerance_pct=Decimal("5.00"),
    )
    return wh_in, wh_out, pergamino, oro, recipe


def _stock(company, branch, wh, item):
    bal = StockBalance.objects.filter(company=company, branch=branch, warehouse=wh, item=item).first()
    return (bal.qty_on_hand, bal.avg_cost) if bal else (Decimal("0"), Decimal("0"))


# ===========================================================================
# Ciclo completo: el costo del pergamino se absorbe COMPLETO en el oro
# ===========================================================================

@pytest.mark.django_db
def test_ciclo_completo_costo_absorbido():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh_in, wh_out, pergamino, oro, recipe = _setup(req, company, branch, actor)

    order = ben.create_order(
        company=company, recipe=recipe, input_warehouse=wh_in, output_warehouse=wh_out,
        input_qty=Decimal("1000.00"), actor=actor,
    )
    order = ben.start_order(request=req, actor=actor, order=order)
    assert order.status == OrderStatus.IN_PROCESS
    assert order.input_cost_total == Decimal("29200.000000")  # 1000 lb × 29.20
    qty_in, _ = _stock(company, branch, wh_in, pergamino)
    assert qty_in == Decimal("0.0000")  # el insumo salió completo

    order = ben.close_order(request=req, actor=actor, order=order, output_qty=Decimal("500.00"))
    assert order.status == OrderStatus.DONE
    assert order.yield_pct == Decimal("50.00")
    assert order.shrinkage_qty == Decimal("500.00")
    assert order.output_unit_cost == Decimal("58.4000")  # 29200 / 500: la merma encarece el oro

    qty_out, avg_out = _stock(company, branch, wh_out, oro)
    assert qty_out == Decimal("500.0000")
    assert avg_out == Decimal("58.400000")
    # Rendimiento dentro de tolerancia (50% esperado) → SIN alerta.
    assert not Alert.objects.filter(company=company, alert_type="YIELD_ANOMALY").exists()


# ===========================================================================
# Antifraude de báscula: rendimiento fuera de rango → alerta CRITICAL
# ===========================================================================

@pytest.mark.django_db
def test_rendimiento_anomalo_dispara_alerta():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh_in, wh_out, _pergamino, _oro, recipe = _setup(req, company, branch, actor)

    order = ben.create_order(
        company=company, recipe=recipe, input_warehouse=wh_in, output_warehouse=wh_out,
        input_qty=Decimal("1000.00"), actor=actor,
    )
    ben.start_order(request=req, actor=actor, order=order)
    # 30% real vs 50% esperado (tolerancia 5pp) → alerta.
    ben.close_order(request=req, actor=actor, order=order, output_qty=Decimal("300.00"))
    alert = Alert.objects.get(company=company, alert_type="YIELD_ANOMALY")
    assert alert.severity == "CRITICAL"
    assert order.reference in alert.title


# ===========================================================================
# Validaciones y estados ilegales
# ===========================================================================

@pytest.mark.django_db
def test_salida_no_puede_superar_entrada():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh_in, wh_out, _p, _o, recipe = _setup(req, company, branch, actor)
    order = ben.create_order(company=company, recipe=recipe, input_warehouse=wh_in,
                             output_warehouse=wh_out, input_qty=Decimal("100.00"), actor=actor)
    ben.start_order(request=req, actor=actor, order=order)
    with pytest.raises(BeneficioError) as exc:
        ben.close_order(request=req, actor=actor, order=order, output_qty=Decimal("150.00"))
    assert exc.value.code == "BEN_OUTPUT_EXCEEDS_INPUT"


@pytest.mark.django_db
def test_start_sin_stock_suficiente_falla():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh_in, wh_out, _p, _o, recipe = _setup(req, company, branch, actor, pergamino_lb="50.00")
    order = ben.create_order(company=company, recipe=recipe, input_warehouse=wh_in,
                             output_warehouse=wh_out, input_qty=Decimal("100.00"), actor=actor)
    with pytest.raises(Exception):  # el kernel rechaza stock negativo
        ben.start_order(request=req, actor=actor, order=order)
    order.refresh_from_db()
    assert order.status == OrderStatus.DRAFT  # transaccional: no quedó a medias


@pytest.mark.django_db
def test_cancelar_solo_borrador_y_cerrar_solo_en_proceso():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh_in, wh_out, _p, _o, recipe = _setup(req, company, branch, actor)
    order = ben.create_order(company=company, recipe=recipe, input_warehouse=wh_in,
                             output_warehouse=wh_out, input_qty=Decimal("100.00"), actor=actor)
    with pytest.raises(BeneficioError) as exc:
        ben.close_order(request=req, actor=actor, order=order, output_qty=Decimal("50.00"))
    assert exc.value.code == "BEN_ORDER_STATE"

    ben.cancel_order(order=order)
    order.refresh_from_db()
    assert order.status == OrderStatus.CANCELLED

    order2 = ben.create_order(company=company, recipe=recipe, input_warehouse=wh_in,
                              output_warehouse=wh_out, input_qty=Decimal("100.00"), actor=actor)
    ben.start_order(request=req, actor=actor, order=order2)
    with pytest.raises(BeneficioError) as exc:
        ben.cancel_order(order=order2)
    assert exc.value.code == "BEN_ORDER_STATE"


@pytest.mark.django_db
def test_receta_valida_items():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    _wh_in, _wh_out, pergamino, _oro, _recipe = _setup(req, company, branch, actor)
    with pytest.raises(BeneficioError) as exc:
        ben.create_recipe(
            company=company, code="X", name="x", input_item=pergamino, output_item=pergamino,
            expected_yield_pct=Decimal("50.00"),
        )
    assert exc.value.code == "BEN_ITEMS_EQUAL"
