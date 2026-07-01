"""Invariantes de negocio del kernel de inventarios (caza de bugs de cómputo).

Ataca, con números concretos:
- Costo promedio MÓVIL: dos recepciones a costos distintos -> avg ponderado exacto.
- Valorización = Σ qty_on_hand × avg_cost por bodega/categoría.
- Conteo físico vía post_adjust(PHYSICAL_COUNT) es IDEMPOTENTE (misma idempotency_key
  no duplica el movimiento ni vuelve a mover el saldo).
- Multi-empresa: el saldo/valor de una empresa no se mezcla con el de otra.

Reusa el estilo/fixtures de test_physical_count.py.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.inventarios.counting import inventory_valuation
from apps.kernels.inventarios.models import (
    InventoryItem,
    MovementType,
    StockBalance,
    StockMovement,
    UoM,
)
from apps.kernels.inventarios.services import (
    create_warehouse,
    post_adjust,
    post_receive,
)
from apps.modulos.iam.models import OrgUnit

User = get_user_model()


def _scope():
    s = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H_{s}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name=f"C_{s}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, name=f"B_{s}", parent=company)
    return company, branch


def _actor():
    t = uuid.uuid4().hex[:8]
    return User.objects.create_user(username=f"u_{t}", email=f"u_{t}@t.local", password="x")


def _req(company, branch, user):
    return SimpleNamespace(
        company=company, branch=branch, user=user,
        request_id="", headers={}, META={}, path="", method="POST",
    )


def _item(company, *, category="Abarrotes"):
    return InventoryItem.objects.create(
        company=company, sku=f"SKU{uuid.uuid4().hex[:6]}", name="Art",
        uom=UoM.UNIT, category=category,
    )


# --------------------------------------------------------------------------- #
# Costo promedio móvil — dos recepciones a costos distintos
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_moving_average_cost_two_receipts_different_costs():
    """Recibo A: 10 uds a C$60 (avg=60). Recibo B: 30 uds a C$100.
    avg ponderado = (10*60 + 30*100) / 40 = (600 + 3000)/40 = 3600/40 = 90.00.
    """
    company, branch = _scope()
    actor = _actor()
    req = _req(company, branch, actor)
    wh = create_warehouse(request=req, company=company, branch=branch, actor_user=actor, name="W", code="W1")
    item = _item(company)

    post_receive(request=req, actor=actor, warehouse_id=wh.id, item_id=item.id,
                 qty=Decimal("10"), unit_cost=Decimal("60"), idempotency_key=f"a-{item.id}")
    post_receive(request=req, actor=actor, warehouse_id=wh.id, item_id=item.id,
                 qty=Decimal("30"), unit_cost=Decimal("100"), idempotency_key=f"b-{item.id}")

    bal = StockBalance.objects.get(company=company, branch=branch, warehouse=wh, item=item)
    assert bal.qty_on_hand == Decimal("40.0000")
    assert bal.avg_cost == Decimal("90.000000"), (
        f"Costo promedio móvil incorrecto: esperado 90.000000, got {bal.avg_cost}"
    )


@pytest.mark.django_db
def test_valuation_equals_qty_times_avg_cost():
    """Valorización = qty_on_hand × avg_cost. Tras avg=90 con 40 uds -> 3600.00."""
    company, branch = _scope()
    actor = _actor()
    req = _req(company, branch, actor)
    wh = create_warehouse(request=req, company=company, branch=branch, actor_user=actor, name="W", code="W1")
    item = _item(company)
    post_receive(request=req, actor=actor, warehouse_id=wh.id, item_id=item.id,
                 qty=Decimal("10"), unit_cost=Decimal("60"), idempotency_key=f"a-{item.id}")
    post_receive(request=req, actor=actor, warehouse_id=wh.id, item_id=item.id,
                 qty=Decimal("30"), unit_cost=Decimal("100"), idempotency_key=f"b-{item.id}")

    val = inventory_valuation(company=company, branch=branch)
    assert val["total_value"] == "3600.00", f"Valorización esperada 3600.00, got {val['total_value']}"


# --------------------------------------------------------------------------- #
# Conteo físico vía post_adjust(PHYSICAL_COUNT) — idempotencia
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_physical_count_adjust_is_idempotent():
    """Reenviar el mismo conteo físico (misma idempotency_key) NO duplica el
    movimiento ni vuelve a mover el saldo: fija la existencia una sola vez."""
    company, branch = _scope()
    actor = _actor()
    req = _req(company, branch, actor)
    wh = create_warehouse(request=req, company=company, branch=branch, actor_user=actor, name="W", code="W1")
    item = _item(company)
    post_receive(request=req, actor=actor, warehouse_id=wh.id, item_id=item.id,
                 qty=Decimal("10"), unit_cost=Decimal("60"), idempotency_key=f"rcv-{item.id}")

    key = f"pc-{item.id}"
    # Conteo físico fija existencia en 7 (faltante de 3).
    post_adjust(request=req, actor=actor, warehouse_id=wh.id, item_id=item.id,
                new_qty_on_hand=Decimal("7"), idempotency_key=key,
                movement_type=MovementType.PHYSICAL_COUNT)
    bal = StockBalance.objects.get(company=company, branch=branch, warehouse=wh, item=item)
    assert bal.qty_on_hand == Decimal("7.0000")
    n_after_first = StockMovement.objects.filter(
        company=company, item=item, movement_type=MovementType.PHYSICAL_COUNT
    ).count()
    assert n_after_first == 1

    # Reenvío idéntico: idempotente -> ni nuevo movimiento ni cambio de saldo.
    post_adjust(request=req, actor=actor, warehouse_id=wh.id, item_id=item.id,
                new_qty_on_hand=Decimal("7"), idempotency_key=key,
                movement_type=MovementType.PHYSICAL_COUNT)
    bal.refresh_from_db()
    assert bal.qty_on_hand == Decimal("7.0000"), "El reenvío idempotente movió el saldo."
    n_after_second = StockMovement.objects.filter(
        company=company, item=item, movement_type=MovementType.PHYSICAL_COUNT
    ).count()
    assert n_after_second == 1, "El reenvío idempotente duplicó el movimiento PHYSICAL_COUNT."


# --------------------------------------------------------------------------- #
# Multi-empresa — saldos/valor no se mezclan
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_valuation_is_company_isolated():
    """La valorización de la empresa A no incluye stock de la empresa B."""
    company_a, branch_a = _scope()
    company_b, branch_b = _scope()
    actor = _actor()
    req_a = _req(company_a, branch_a, actor)
    req_b = _req(company_b, branch_b, actor)

    wh_a = create_warehouse(request=req_a, company=company_a, branch=branch_a, actor_user=actor, name="WA", code="WA")
    wh_b = create_warehouse(request=req_b, company=company_b, branch=branch_b, actor_user=actor, name="WB", code="WB")
    item_a = _item(company_a)
    item_b = _item(company_b)

    post_receive(request=req_a, actor=actor, warehouse_id=wh_a.id, item_id=item_a.id,
                 qty=Decimal("10"), unit_cost=Decimal("50"), idempotency_key=f"a-{item_a.id}")
    post_receive(request=req_b, actor=actor, warehouse_id=wh_b.id, item_id=item_b.id,
                 qty=Decimal("4"), unit_cost=Decimal("25"), idempotency_key=f"b-{item_b.id}")

    val_a = inventory_valuation(company=company_a, branch=branch_a)
    val_b = inventory_valuation(company=company_b, branch=branch_b)
    assert val_a["total_value"] == "500.00"  # 10×50, sin la mercadería de B
    assert val_b["total_value"] == "100.00"  # 4×25, sin la mercadería de A
