"""Tests de órdenes de compra formales (Ola B): ciclo de vida, SoD maker≠checker,
costos por proveedor, recepciones parciales que postean inventario real, idempotencia.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import uuid
from decimal import Decimal
from threading import Barrier
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connections

from apps.kernels.inventarios.models import InventoryItem, StockBalance, StockMovement, UoM
from apps.kernels.inventarios.services import create_warehouse
from apps.modulos.compras.models import (
    PurchaseOrder,
    PurchaseOrderStatus,
    PurchaseReceipt,
    SupplierItemPrice,
)
from apps.modulos.compras.services import ProcurementError, create_purchase_draft
from apps.modulos.compras.services_orders import (
    ProcurementSoDError,
    approve_purchase_order,
    cancel_purchase_order,
    create_purchase_order,
    mark_purchase_order_sent,
    receive_purchase_order,
    submit_purchase_order,
)
from apps.modulos.iam.models import OrgUnit
from apps.modulos.parties.models import Party

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


def _req(company, branch, actor):
    return SimpleNamespace(
        company=company, branch=branch, user=actor,
        request_id="", headers={}, META={}, path="", method="POST",
    )


def _supplier(company, name="Proveedor Sur"):
    return Party.objects.create(
        company=company, party_type=Party.PartyType.JURIDICAL, display_name=name
    )


def _item(company, *, tax="0.15", **extra):
    return InventoryItem.objects.create(
        company=company, sku=f"SKU{uuid.uuid4().hex[:6]}", name="Cemento 42.5kg",
        uom=UoM.UNIT, default_tax_rate=Decimal(tax), **extra,
    )


def _warehouse(req, company, branch, actor):
    return create_warehouse(
        request=req, company=company, branch=branch, actor_user=actor, name="Central", code="W1"
    )


def _order_to_sent(req, actor, other, supplier, item, *, qty="10", cost="100.00"):
    """OC creada por `actor`, aprobada por `other`, marcada enviada."""
    res = create_purchase_order(
        request=req, actor=actor, supplier_party_id=supplier.id,
        lines=[{"item_id": item.id, "qty": qty, "unit_cost": cost}],
    )
    submit_purchase_order(request=req, actor=actor, order_id=res["order_id"])
    approve_purchase_order(request=req, actor=other, order_id=res["order_id"])
    mark_purchase_order_sent(request=req, actor=other, order_id=res["order_id"])
    return PurchaseOrder.objects.get(id=res["order_id"])


# ---------------------------------------------------------------------------
# Ciclo de vida y SoD
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_create_order_assigns_number_and_totals():
    company, branch = _scope()
    actor = _actor()
    req = _req(company, branch, actor)
    supplier = _supplier(company)
    item = _item(company, tax="0.15")

    res = create_purchase_order(
        request=req, actor=actor, supplier_party_id=supplier.id,
        lines=[{"item_id": item.id, "qty": "10", "unit_cost": "100.00"}],
    )
    order = PurchaseOrder.objects.get(id=res["order_id"])
    assert order.number == 1  # numerada al crear (referencia inmediata)
    assert order.status == PurchaseOrderStatus.DRAFT
    assert order.subtotal == Decimal("1000.00")
    assert order.tax_total == Decimal("150.00")
    assert order.total == Decimal("1150.00")
    line = order.lines.get()
    assert line.tax_rate == Decimal("0.1500")  # IVA por defecto del artículo


@pytest.mark.django_db
def test_create_order_is_idempotent():
    company, branch = _scope()
    actor = _actor()
    req = _req(company, branch, actor)
    supplier = _supplier(company)
    item = _item(company)

    kwargs = dict(
        request=req, actor=actor, supplier_party_id=supplier.id,
        lines=[{"item_id": item.id, "qty": "5", "unit_cost": "10.00"}],
        idempotency_key="OC-IDEM-1",
    )
    r1 = create_purchase_order(**kwargs)
    r2 = create_purchase_order(**kwargs)
    assert r2["duplicate"] is True
    assert r2["order_id"] == r1["order_id"]
    assert PurchaseOrder.objects.filter(company=company).count() == 1


@pytest.mark.django_db
def test_line_cost_falls_back_to_supplier_price_then_errors():
    company, branch = _scope()
    actor = _actor()
    req = _req(company, branch, actor)
    supplier = _supplier(company)
    item = _item(company, tax="0")

    # Sin costo explícito ni precio del proveedor → error claro.
    with pytest.raises(ProcurementError, match="PROCUREMENT_LINE_COST_REQUIRED"):
        create_purchase_order(
            request=req, actor=actor, supplier_party_id=supplier.id,
            lines=[{"item_id": item.id, "qty": "1"}],
        )

    # Con precio ACORDADO el costo sale solo.
    SupplierItemPrice.objects.create(
        company=company, supplier_party=supplier, item=item,
        agreed_price=Decimal("80.00"), last_cost=Decimal("90.00"),
    )
    res = create_purchase_order(
        request=req, actor=actor, supplier_party_id=supplier.id,
        lines=[{"item_id": item.id, "qty": "2"}],
    )
    order = PurchaseOrder.objects.get(id=res["order_id"])
    assert order.lines.get().unit_cost == Decimal("80.00")  # acordado > último costo


@pytest.mark.django_db
def test_sod_submitter_cannot_approve():
    company, branch = _scope()
    actor = _actor()
    other = _actor()
    req = _req(company, branch, actor)
    supplier = _supplier(company)
    item = _item(company)

    res = create_purchase_order(
        request=req, actor=actor, supplier_party_id=supplier.id,
        lines=[{"item_id": item.id, "qty": "1", "unit_cost": "10"}],
    )
    submit_purchase_order(request=req, actor=actor, order_id=res["order_id"])

    with pytest.raises(ProcurementSoDError, match="PROCUREMENT_SOD_SELF_APPROVAL"):
        approve_purchase_order(request=req, actor=actor, order_id=res["order_id"])

    out = approve_purchase_order(request=req, actor=other, order_id=res["order_id"])
    assert out["status"] == PurchaseOrderStatus.APPROVED


@pytest.mark.django_db
def test_create_purchase_draft_rejects_sequence_only_doc_types():
    company, branch = _scope()
    actor = _actor()
    req = _req(company, branch, actor)
    # PURCHASE_ORDER existe en el TextChoices SOLO para numeración: no es un documento.
    with pytest.raises(ProcurementError, match="invalid doc_type"):
        create_purchase_draft(
            request=req, actor=actor, doc_type="PURCHASE_ORDER", series="P", currency="NIO",
            supplier_name="", supplier_ref="", external_ref="",
            subtotal=Decimal("1"), tax_total=Decimal("0"), total=Decimal("1"),
        )


# ---------------------------------------------------------------------------
# Recepciones parciales (postean inventario real)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_partial_receipts_post_stock_and_walk_states():
    company, branch = _scope()
    actor = _actor()
    other = _actor()
    req = _req(company, branch, actor)
    supplier = _supplier(company)
    item = _item(company)
    wh = _warehouse(req, company, branch, actor)
    order = _order_to_sent(req, actor, other, supplier, item, qty="10", cost="100.00")
    line = order.lines.get()

    out1 = receive_purchase_order(
        request=req, actor=actor, order_id=order.id, warehouse_id=wh.id,
        lines=[{"order_line_id": line.id, "qty": "4"}], idempotency_key="RC-1",
    )
    assert out1["order_status"] == PurchaseOrderStatus.PARTIALLY_RECEIVED

    bal = StockBalance.objects.get(company=company, branch=branch, warehouse=wh, item=item)
    assert bal.qty_on_hand == Decimal("4.0000")
    mov = StockMovement.objects.get(id=out1["lines"][0]["movement_id"])
    assert mov.source_module == "PROCUREMENT"
    assert mov.source_type == "PO_RECEIPT"
    assert mov.unit_cost == Decimal("100.0000")

    # Último costo del proveedor actualizado automáticamente.
    price = SupplierItemPrice.objects.get(company=company, supplier_party=supplier, item=item)
    assert price.last_cost == Decimal("100.0000")
    assert price.last_receipt_at is not None

    out2 = receive_purchase_order(
        request=req, actor=actor, order_id=order.id, warehouse_id=wh.id,
        lines=[{"order_line_id": line.id, "qty": "6", "unit_cost": "110.00"}],
        idempotency_key="RC-2",
    )
    assert out2["order_status"] == PurchaseOrderStatus.RECEIVED
    bal.refresh_from_db()
    assert bal.qty_on_hand == Decimal("10.0000")
    price.refresh_from_db()
    assert price.last_cost == Decimal("110.0000")  # costo real de la última recepción


@pytest.mark.django_db
def test_over_receipt_is_rejected():
    company, branch = _scope()
    actor = _actor()
    other = _actor()
    req = _req(company, branch, actor)
    supplier = _supplier(company)
    item = _item(company)
    wh = _warehouse(req, company, branch, actor)
    order = _order_to_sent(req, actor, other, supplier, item, qty="10")
    line = order.lines.get()

    receive_purchase_order(
        request=req, actor=actor, order_id=order.id, warehouse_id=wh.id,
        lines=[{"order_line_id": line.id, "qty": "4"}], idempotency_key="RC-OVER-1",
    )
    with pytest.raises(ProcurementError, match="PROCUREMENT_OVER_RECEIPT"):
        receive_purchase_order(
            request=req, actor=actor, order_id=order.id, warehouse_id=wh.id,
            lines=[{"order_line_id": line.id, "qty": "7"}],  # pendiente: 6
            idempotency_key="RC-OVER-2",
        )
    # Rollback total: ni recepción ni stock.
    line.refresh_from_db()
    assert line.qty_received == Decimal("4.0000")


@pytest.mark.django_db
def test_receive_is_idempotent_by_key():
    company, branch = _scope()
    actor = _actor()
    other = _actor()
    req = _req(company, branch, actor)
    supplier = _supplier(company)
    item = _item(company)
    wh = _warehouse(req, company, branch, actor)
    order = _order_to_sent(req, actor, other, supplier, item, qty="10")
    line = order.lines.get()

    kwargs = dict(
        request=req, actor=actor, order_id=order.id, warehouse_id=wh.id,
        lines=[{"order_line_id": line.id, "qty": "4"}], idempotency_key="RC-IDEM",
    )
    r1 = receive_purchase_order(**kwargs)
    r2 = receive_purchase_order(**kwargs)  # reintento de red

    assert r2["duplicate"] is True
    assert r2["receipt_id"] == r1["receipt_id"]
    assert PurchaseReceipt.objects.filter(company=company).count() == 1
    line.refresh_from_db()
    assert line.qty_received == Decimal("4.0000")  # sin doble conteo
    bal = StockBalance.objects.get(company=company, branch=branch, warehouse=wh, item=item)
    assert bal.qty_on_hand == Decimal("4.0000")


@pytest.mark.django_db(transaction=True)
def test_receive_same_order_concurrently_serializes_quantities_and_inventory():
    """U17: dos recepciones compatibles no pierden updates ni duplican stock."""
    company, branch = _scope()
    actor = _actor()
    other = _actor()
    req = _req(company, branch, actor)
    supplier = _supplier(company)
    item = _item(company)
    warehouse = _warehouse(req, company, branch, actor)
    order = _order_to_sent(req, actor, other, supplier, item, qty="10")
    line_id = order.lines.get().id
    barrier = Barrier(2)

    def receive(index: int):
        close_old_connections()
        barrier.wait(timeout=10)
        result = receive_purchase_order(
            request=req,
            actor=actor,
            order_id=order.id,
            warehouse_id=warehouse.id,
            lines=[{"order_line_id": line_id, "qty": "5"}],
            idempotency_key=f"RC-CONCURRENT-{index}",
        )
        close_old_connections()
        return result

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(receive, range(2)))
    finally:
        connections.close_all()

    order.refresh_from_db()
    line = order.lines.get(id=line_id)
    balance = StockBalance.objects.get(company=company, branch=branch, warehouse=warehouse, item=item)
    assert order.status == PurchaseOrderStatus.RECEIVED
    assert line.qty_received == Decimal("10.0000")
    assert balance.qty_on_hand == Decimal("10.0000")
    assert len({result["receipt_id"] for result in results}) == 2
    assert len({result["number"] for result in results}) == 2


@pytest.mark.django_db(transaction=True)
def test_purchase_order_numbers_are_unique_under_concurrent_creation():
    """U17: la primera creacion concurrente de la secuencia OC no duplica numero."""
    company, branch = _scope()
    actor = _actor()
    req = _req(company, branch, actor)
    supplier = _supplier(company)
    item = _item(company)
    barrier = Barrier(2)

    def create(index: int):
        close_old_connections()
        barrier.wait(timeout=10)
        result = create_purchase_order(
            request=req,
            actor=actor,
            supplier_party_id=supplier.id,
            lines=[{"item_id": item.id, "qty": "1", "unit_cost": "10"}],
            idempotency_key=f"OC-CONCURRENT-{index}",
        )
        close_old_connections()
        return result

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, range(2)))
    finally:
        connections.close_all()

    assert {result["number"] for result in results} == {1, 2}
    assert PurchaseOrder.objects.filter(company=company, branch=branch).count() == 2


@pytest.mark.django_db
def test_cancel_blocked_when_received_and_ok_without_receipts():
    company, branch = _scope()
    actor = _actor()
    other = _actor()
    req = _req(company, branch, actor)
    supplier = _supplier(company)
    item = _item(company)
    wh = _warehouse(req, company, branch, actor)

    # Sin recepciones: cancela bien.
    res = create_purchase_order(
        request=req, actor=actor, supplier_party_id=supplier.id,
        lines=[{"item_id": item.id, "qty": "1", "unit_cost": "10"}],
    )
    out = cancel_purchase_order(request=req, actor=actor, order_id=res["order_id"], reason="ya no")
    assert out["status"] == PurchaseOrderStatus.CANCELLED

    # Con mercadería recibida NO se cancela (se cierra).
    order = _order_to_sent(req, actor, other, supplier, item, qty="10")
    line = order.lines.get()
    receive_purchase_order(
        request=req, actor=actor, order_id=order.id, warehouse_id=wh.id,
        lines=[{"order_line_id": line.id, "qty": "2"}], idempotency_key="RC-CXL",
    )
    with pytest.raises(ProcurementError, match="PROCUREMENT_ORDER_HAS_RECEIPTS"):
        cancel_purchase_order(request=req, actor=actor, order_id=order.id)
