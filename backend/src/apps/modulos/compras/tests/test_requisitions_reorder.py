"""Tests de requisiciones (ciclo + SoD + conversión a OC) y sugerencia de reorden."""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.inventarios.models import InventoryItem, UoM
from apps.kernels.inventarios.services import create_warehouse, post_receive
from apps.modulos.compras.models import (
    PurchaseOrder,
    PurchaseRequisitionStatus,
    SupplierItemPrice,
)
from apps.modulos.compras.services import ProcurementError
from apps.modulos.compras.services_orders import (
    ProcurementSoDError,
    create_draft_orders_from_suggestions,
    reorder_suggestions,
)
from apps.modulos.compras.services_requisitions import (
    approve_requisition,
    convert_requisition_to_order,
    create_requisition,
    reject_requisition,
    submit_requisition,
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


def _item(company, **extra):
    return InventoryItem.objects.create(
        company=company, sku=f"SKU{uuid.uuid4().hex[:6]}", name="Insumo",
        uom=UoM.UNIT, default_tax_rate=Decimal("0"), **extra,
    )


# ---------------------------------------------------------------------------
# Requisiciones
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_requisition_full_cycle_to_order():
    company, branch = _scope()
    actor = _actor()
    approver = _actor()
    req = _req(company, branch, actor)
    supplier = Party.objects.create(
        company=company, party_type=Party.PartyType.JURIDICAL, display_name="Prov Req"
    )
    item = _item(company)
    SupplierItemPrice.objects.create(
        company=company, supplier_party=supplier, item=item, agreed_price=Decimal("25.00")
    )

    res = create_requisition(
        request=req, actor=actor,
        lines=[{"item_id": item.id, "qty": "8", "note": "para bodega"}], notes="urgente",
    )
    submit_requisition(request=req, actor=actor, requisition_id=res["requisition_id"])

    # SoD: quien pide no aprueba.
    with pytest.raises(ProcurementSoDError, match="PROCUREMENT_SOD_SELF_APPROVAL"):
        approve_requisition(request=req, actor=actor, requisition_id=res["requisition_id"])

    approve_requisition(request=req, actor=approver, requisition_id=res["requisition_id"])
    out = convert_requisition_to_order(
        request=req, actor=actor, requisition_id=res["requisition_id"],
        supplier_party_id=supplier.id,
    )
    assert out["status"] == PurchaseRequisitionStatus.CONVERTED

    order = PurchaseOrder.objects.get(id=out["order_id"])
    line = order.lines.get()
    assert line.qty_ordered == Decimal("8.0000")
    assert line.unit_cost == Decimal("25.00")  # precio acordado del proveedor


@pytest.mark.django_db
def test_requisition_reject_requires_reason():
    company, branch = _scope()
    actor = _actor()
    approver = _actor()
    req = _req(company, branch, actor)
    item = _item(company)

    res = create_requisition(request=req, actor=actor, lines=[{"item_id": item.id, "qty": "1"}])
    submit_requisition(request=req, actor=actor, requisition_id=res["requisition_id"])

    with pytest.raises(ProcurementError, match="PROCUREMENT_REASON_REQUIRED"):
        reject_requisition(
            request=req, actor=approver, requisition_id=res["requisition_id"], reason="  "
        )
    out = reject_requisition(
        request=req, actor=approver, requisition_id=res["requisition_id"],
        reason="No hay presupuesto este mes",
    )
    assert out["status"] == PurchaseRequisitionStatus.REJECTED

    # Una rechazada no se convierte.
    with pytest.raises(ProcurementError, match="PROCUREMENT_REQ_NOT_APPROVED"):
        convert_requisition_to_order(
            request=req, actor=actor, requisition_id=res["requisition_id"], supplier_party_id=1
        )


# ---------------------------------------------------------------------------
# Sugerencia de reorden
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_reorder_suggestions_formula_and_supplier():
    company, branch = _scope()
    actor = _actor()
    req = _req(company, branch, actor)
    wh = create_warehouse(
        request=req, company=company, branch=branch, actor_user=actor, name="Central", code="W1"
    )
    supplier_old = Party.objects.create(
        company=company, party_type=Party.PartyType.JURIDICAL, display_name="Prov viejo"
    )
    supplier_new = Party.objects.create(
        company=company, party_type=Party.PartyType.JURIDICAL, display_name="Prov reciente"
    )

    # Bajo reorden CON max_stock: sugerida = max_stock − existencia = 50 − 4 = 46.
    item_max = _item(company, reorder_point=Decimal("10"), max_stock_qty=Decimal("50"))
    # Bajo reorden SIN max_stock: sugerida = reorder×2 − existencia = 20 − 4 = 16.
    item_nomax = _item(company, reorder_point=Decimal("10"))
    # Sobre el punto de reorden: NO aparece.
    item_ok = _item(company, reorder_point=Decimal("2"))

    for it, qty in ((item_max, "4"), (item_nomax, "4"), (item_ok, "9")):
        post_receive(
            request=req, actor=actor, warehouse_id=wh.id, item_id=it.id,
            qty=Decimal(qty), unit_cost=Decimal("10"), idempotency_key=f"rcv-{it.id}",
        )

    from django.utils import timezone
    from datetime import timedelta

    SupplierItemPrice.objects.create(
        company=company, supplier_party=supplier_old, item=item_max,
        last_cost=Decimal("9.00"), last_receipt_at=timezone.now() - timedelta(days=30),
    )
    SupplierItemPrice.objects.create(
        company=company, supplier_party=supplier_new, item=item_max,
        last_cost=Decimal("9.50"), last_receipt_at=timezone.now(),
    )

    suggestions = {s["item_id"]: s for s in reorder_suggestions(company=company, branch=branch)}
    assert item_ok.id not in suggestions
    assert suggestions[item_max.id]["suggested_qty"] == "46"
    assert suggestions[item_nomax.id]["suggested_qty"] == "16"
    # Proveedor sugerido: el de la recepción MÁS RECIENTE.
    assert suggestions[item_max.id]["supplier_party_id"] == supplier_new.id
    assert suggestions[item_nomax.id]["supplier_party_id"] is None


@pytest.mark.django_db
def test_create_orders_from_suggestions_groups_by_supplier():
    company, branch = _scope()
    actor = _actor()
    req = _req(company, branch, actor)
    sup_a = Party.objects.create(
        company=company, party_type=Party.PartyType.JURIDICAL, display_name="Prov A"
    )
    sup_b = Party.objects.create(
        company=company, party_type=Party.PartyType.JURIDICAL, display_name="Prov B"
    )
    i1, i2, i3 = _item(company), _item(company), _item(company)
    for it, sup in ((i1, sup_a), (i2, sup_a), (i3, sup_b)):
        SupplierItemPrice.objects.create(
            company=company, supplier_party=sup, item=it, agreed_price=Decimal("5.00")
        )

    out = create_draft_orders_from_suggestions(
        request=req, actor=actor,
        items=[
            {"item_id": i1.id, "qty": "10", "supplier_party_id": sup_a.id},
            {"item_id": i2.id, "qty": "20", "supplier_party_id": sup_a.id},
            {"item_id": i3.id, "qty": "5", "supplier_party_id": sup_b.id},
        ],
    )
    assert len(out["orders"]) == 2  # una OC por proveedor
    by_supplier = {o["supplier_party_id"]: o for o in out["orders"]}
    assert by_supplier[sup_a.id]["lines"] == 2
    assert by_supplier[sup_b.id]["lines"] == 1
    order_a = PurchaseOrder.objects.get(id=by_supplier[sup_a.id]["order_id"])
    assert order_a.status == "DRAFT"
    assert order_a.lines.count() == 2
