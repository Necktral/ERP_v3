"""Tests del conteo físico (Ola C): hoja con snapshot → captura → varianzas →
aprobación SoD (quien cuenta no aprueba) → ajustes PHYSICAL_COUNT reales al kardex.
También la valorización (Σ existencia × costo promedio).
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.inventarios.counting import (
    InventoryCountError,
    InventoryCountSoDError,
    approve_physical_count,
    cancel_physical_count,
    capture_physical_count,
    create_physical_count,
    inventory_valuation,
)
from apps.kernels.inventarios.models import (
    InventoryItem,
    MovementType,
    PhysicalCountStatus,
    StockBalance,
    StockMovement,
    UoM,
)
from apps.kernels.inventarios.services import create_warehouse, post_receive
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


def _setup_stock(req, company, branch, actor, *, items=2):
    """Bodega con `items` artículos (10 uds a C$60 c/u)."""
    wh = create_warehouse(
        request=req, company=company, branch=branch, actor_user=actor, name="Central", code="W1"
    )
    out = []
    for i in range(items):
        item = InventoryItem.objects.create(
            company=company, sku=f"SKU{uuid.uuid4().hex[:6]}", name=f"Art {i}",
            uom=UoM.UNIT, category="Abarrotes",
        )
        post_receive(
            request=req, actor=actor, warehouse_id=wh.id, item_id=item.id,
            qty=Decimal("10"), unit_cost=Decimal("60"), idempotency_key=f"rcv-{item.id}",
        )
        out.append(item)
    return wh, out


@pytest.mark.django_db
def test_count_sheet_snapshots_expected_quantities():
    company, branch = _scope()
    actor = _actor()
    req = _req(company, branch, actor)
    wh, (i1, i2) = _setup_stock(req, company, branch, actor)

    sheet = create_physical_count(request=req, actor=actor, warehouse_id=wh.id, notes="mensual")
    assert sheet["status"] == PhysicalCountStatus.OPEN
    assert len(sheet["lines"]) == 2
    assert all(ln["qty_expected"] == "10.0000" for ln in sheet["lines"])
    assert all(ln["qty_counted"] is None for ln in sheet["lines"])


@pytest.mark.django_db
def test_count_sheet_requires_stock_rows():
    company, branch = _scope()
    actor = _actor()
    req = _req(company, branch, actor)
    wh = create_warehouse(
        request=req, company=company, branch=branch, actor_user=actor, name="Vacía", code="W2"
    )
    with pytest.raises(InventoryCountError, match="INVENTORY_COUNT_NO_ITEMS"):
        create_physical_count(request=req, actor=actor, warehouse_id=wh.id)


@pytest.mark.django_db
def test_partial_capture_keeps_sheet_open_then_full_capture_counts():
    company, branch = _scope()
    actor = _actor()
    req = _req(company, branch, actor)
    wh, (i1, i2) = _setup_stock(req, company, branch, actor)
    sheet = create_physical_count(request=req, actor=actor, warehouse_id=wh.id)
    l1, l2 = sheet["lines"][0], sheet["lines"][1]

    partial = capture_physical_count(
        request=req, actor=actor, count_id=sheet["id"],
        lines=[{"line_id": l1["id"], "qty_counted": "8"}],
    )
    assert partial["status"] == PhysicalCountStatus.OPEN
    assert partial["pending_lines"] == 1

    full = capture_physical_count(
        request=req, actor=actor, count_id=sheet["id"],
        lines=[{"line_id": l2["id"], "qty_counted": "10"}],
    )
    assert full["status"] == PhysicalCountStatus.COUNTED
    by_id = {ln["id"]: ln for ln in full["lines"]}
    assert by_id[l1["id"]]["variance"] == "-2.0000"  # contó 8, esperaba 10
    assert by_id[l2["id"]]["variance"] == "0.0000"


@pytest.mark.django_db
def test_sod_counter_cannot_approve_and_other_posts_adjustments():
    company, branch = _scope()
    counter = _actor()
    approver = _actor()
    req = _req(company, branch, counter)
    wh, (i1, i2) = _setup_stock(req, company, branch, counter)
    sheet = create_physical_count(request=req, actor=counter, warehouse_id=wh.id)
    l1, l2 = sheet["lines"][0], sheet["lines"][1]

    capture_physical_count(
        request=req, actor=counter, count_id=sheet["id"],
        lines=[
            {"line_id": l1["id"], "qty_counted": "7"},   # faltante de 3
            {"line_id": l2["id"], "qty_counted": "10"},  # cuadra
        ],
    )

    # SoD: quien contó no aprueba.
    with pytest.raises(InventoryCountSoDError, match="INVENTORY_COUNT_SOD_SELF_APPROVAL"):
        approve_physical_count(request=req, actor=counter, count_id=sheet["id"])

    req_ap = _req(company, branch, approver)
    out = approve_physical_count(request=req_ap, actor=approver, count_id=sheet["id"])
    assert out["status"] == PhysicalCountStatus.POSTED
    assert out["adjusted_lines"] == 1  # solo la línea con varianza

    item1_id = int(l1["item_id"])
    bal = StockBalance.objects.get(company=company, branch=branch, warehouse=wh, item_id=item1_id)
    assert bal.qty_on_hand == Decimal("7.0000")  # fijado en lo contado

    mov = StockMovement.objects.get(
        company=company, item_id=item1_id, movement_type=MovementType.PHYSICAL_COUNT
    )
    assert mov.qty_delta == Decimal("-3.0000")
    assert mov.unit_cost == Decimal("60.000000")  # varianza valorizada al costo promedio

    # La línea que cuadró NO genera movimiento.
    assert not StockMovement.objects.filter(
        company=company, item_id=int(l2["item_id"]), movement_type=MovementType.PHYSICAL_COUNT
    ).exists()

    # Un POSTED no se re-aprueba (y no duplica ajustes).
    with pytest.raises(InventoryCountError, match="INVENTORY_COUNT_NOT_COUNTED"):
        approve_physical_count(request=req_ap, actor=approver, count_id=sheet["id"])
    assert StockMovement.objects.filter(
        company=company, movement_type=MovementType.PHYSICAL_COUNT
    ).count() == 1


@pytest.mark.django_db
def test_no_adjust_when_stock_moved_but_count_matches_current():
    """El stock cambió DESPUÉS del snapshot; si lo contado coincide con la
    existencia actual, no hay nada que ajustar (varianza informativa ≠ ajuste)."""
    company, branch = _scope()
    counter = _actor()
    approver = _actor()
    req = _req(company, branch, counter)
    wh, (i1,) = _setup_stock(req, company, branch, counter, items=1)
    sheet = create_physical_count(request=req, actor=counter, warehouse_id=wh.id)
    line = sheet["lines"][0]

    # Entran 5 más después de generar la hoja (snapshot quedó en 10).
    post_receive(
        request=req, actor=counter, warehouse_id=wh.id, item_id=i1.id,
        qty=Decimal("5"), unit_cost=Decimal("60"), idempotency_key=f"rcv2-{i1.id}",
    )
    capture_physical_count(
        request=req, actor=counter, count_id=sheet["id"],
        lines=[{"line_id": line["id"], "qty_counted": "15"}],
    )
    out = approve_physical_count(
        request=_req(company, branch, approver), actor=approver, count_id=sheet["id"]
    )
    assert out["adjusted_lines"] == 0
    bal = StockBalance.objects.get(company=company, branch=branch, warehouse=wh, item=i1)
    assert bal.qty_on_hand == Decimal("15.0000")


@pytest.mark.django_db
def test_cancel_and_cross_company_scoping():
    company, branch = _scope()
    company2, branch2 = _scope()
    actor = _actor()
    req = _req(company, branch, actor)
    wh, _items = _setup_stock(req, company, branch, actor, items=1)
    sheet = create_physical_count(request=req, actor=actor, warehouse_id=wh.id)

    # Desde OTRA empresa la hoja no existe.
    req2 = _req(company2, branch2, actor)
    with pytest.raises(InventoryCountError, match="INVENTORY_COUNT_NOT_FOUND"):
        capture_physical_count(
            request=req2, actor=actor, count_id=sheet["id"],
            lines=[{"line_id": 1, "qty_counted": "1"}],
        )

    out = cancel_physical_count(request=req, actor=actor, count_id=sheet["id"])
    assert out["status"] == PhysicalCountStatus.CANCELLED
    with pytest.raises(InventoryCountError, match="INVENTORY_COUNT_NOT_OPEN"):
        capture_physical_count(
            request=req, actor=actor, count_id=sheet["id"],
            lines=[{"line_id": 1, "qty_counted": "1"}],
        )


@pytest.mark.django_db
def test_valuation_aggregates_by_warehouse_and_category():
    company, branch = _scope()
    actor = _actor()
    req = _req(company, branch, actor)
    wh, (i1, i2) = _setup_stock(req, company, branch, actor)  # 2 items × 10 × C$60
    # Un item de otra categoría en otra bodega: 4 × C$25 = 100.
    wh2 = create_warehouse(
        request=req, company=company, branch=branch, actor_user=actor, name="Anexa", code="W9"
    )
    i3 = InventoryItem.objects.create(
        company=company, sku=f"SKU{uuid.uuid4().hex[:6]}", name="Lubricante",
        uom=UoM.UNIT, category="Taller",
    )
    post_receive(
        request=req, actor=actor, warehouse_id=wh2.id, item_id=i3.id,
        qty=Decimal("4"), unit_cost=Decimal("25"), idempotency_key=f"rcv-{i3.id}",
    )

    val = inventory_valuation(company=company, branch=branch)
    assert val["total_value"] == "1300.00"  # 2×600 + 100

    by_wh = {g["warehouse_id"]: g for g in val["by_warehouse"]}
    assert by_wh[wh.id]["value"] == "1200.00"
    assert by_wh[wh2.id]["value"] == "100.00"

    by_cat = {g["category"]: g for g in val["by_category"]}
    assert by_cat["Abarrotes"]["value"] == "1200.00"
    assert by_cat["Taller"]["value"] == "100.00"

    # Filtro por bodega.
    solo_w2 = inventory_valuation(company=company, branch=branch, warehouse_id=wh2.id)
    assert solo_w2["total_value"] == "100.00"
    assert len(solo_w2["detail"]) == 1
