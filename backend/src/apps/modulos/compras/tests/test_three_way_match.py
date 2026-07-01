"""Tests del 3-way match (OC ↔ recepción ↔ factura del proveedor).

Restricción dura protegida aquí: la CxP NACE del flujo existente de PurchaseDocument
(ProcurementDocumentPosted → link_procurement_document_to_payable), no del match.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.inventarios.models import InventoryItem, UoM
from apps.kernels.inventarios.services import create_warehouse
from apps.kernels.portfolio.models import Payable
from apps.modulos.compras.models import PurchaseDocument
from apps.modulos.compras.services import post_purchase_document
from apps.modulos.compras.services_orders import (
    ProcurementMatchError,
    approve_purchase_order,
    create_invoice_for_order,
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


@pytest.fixture
def ctx(db):
    """OC de 10 × 100 + IVA 15% enviada y RECIBIDA completa (valor recibido 1150)."""
    company, branch = _scope()
    actor = _actor()
    other = _actor()
    req = _req(company, branch, actor)
    supplier = Party.objects.create(
        company=company, party_type=Party.PartyType.JURIDICAL, display_name="Distribuidora Norte"
    )
    item = InventoryItem.objects.create(
        company=company, sku=f"SKU{uuid.uuid4().hex[:6]}", name="Azúcar 50kg",
        uom=UoM.UNIT, default_tax_rate=Decimal("0.15"),
    )
    wh = create_warehouse(
        request=req, company=company, branch=branch, actor_user=actor, name="Central", code="W1"
    )
    res = create_purchase_order(
        request=req, actor=actor, supplier_party_id=supplier.id,
        lines=[{"item_id": item.id, "qty": "10", "unit_cost": "100.00"}],
    )
    submit_purchase_order(request=req, actor=actor, order_id=res["order_id"])
    approve_purchase_order(request=req, actor=other, order_id=res["order_id"])
    mark_purchase_order_sent(request=req, actor=other, order_id=res["order_id"])
    order_id = res["order_id"]
    from apps.modulos.compras.models import PurchaseOrder

    line = PurchaseOrder.objects.get(id=order_id).lines.get()
    receive_purchase_order(
        request=req, actor=actor, order_id=order_id, warehouse_id=wh.id,
        lines=[{"order_line_id": line.id, "qty": "10"}], idempotency_key="RC-M1",
    )
    return SimpleNamespace(
        company=company, branch=branch, actor=actor, req=req,
        supplier=supplier, item=item, wh=wh, order_id=order_id,
    )


def test_invoice_within_tolerance_creates_doc_and_payable_via_existing_flow(ctx):
    out = create_invoice_for_order(
        request=ctx.req, actor=ctx.actor, order_id=ctx.order_id,
        subtotal=Decimal("1000.00"), tax_total=Decimal("150.00"), total=Decimal("1150.00"),
        supplier_ref="FP-001",
    )
    assert out["pending_to_invoice"] == "1150.00"
    doc = PurchaseDocument.objects.get(id=out["doc_id"])
    assert doc.purchase_order_id == ctx.order_id

    # El posteo (flujo EXISTENTE) crea la CxP — el match no la duplica ni la crea.
    assert not Payable.objects.filter(
        reference_type="PROCUREMENT_DOC", reference_id=doc.id
    ).exists()
    post_purchase_document(request=ctx.req, actor=ctx.actor, doc_id=doc.id)
    payable = Payable.objects.get(reference_type="PROCUREMENT_DOC", reference_id=doc.id)
    assert payable.principal_amount == Decimal("1150.00")
    assert payable.party_id == ctx.supplier.id


def test_invoice_out_of_tolerance_is_rejected(ctx):
    # Desviación 150 sobre 1150 (>2%) → fuera de tolerancia.
    with pytest.raises(ProcurementMatchError, match="PROCUREMENT_MATCH_OUT_OF_TOLERANCE"):
        create_invoice_for_order(
            request=ctx.req, actor=ctx.actor, order_id=ctx.order_id,
            subtotal=Decimal("1130.43"), tax_total=Decimal("169.57"), total=Decimal("1300.00"),
        )
    assert not PurchaseDocument.objects.filter(purchase_order_id=ctx.order_id).exists()


def test_invoice_small_deviation_within_tolerance_passes(ctx):
    # 1150 ± 2% admite hasta 23.00 de desviación: 1170 pasa.
    out = create_invoice_for_order(
        request=ctx.req, actor=ctx.actor, order_id=ctx.order_id,
        subtotal=Decimal("1017.39"), tax_total=Decimal("152.61"), total=Decimal("1170.00"),
    )
    assert Decimal(out["deviation"]) == Decimal("20.00")


def test_match_override_requires_both_flag_and_permission(ctx):
    # Flag sin autorización (allow=False) NO bypassa el match.
    with pytest.raises(ProcurementMatchError):
        create_invoice_for_order(
            request=ctx.req, actor=ctx.actor, order_id=ctx.order_id,
            subtotal=Decimal("2000.00"), tax_total=Decimal("0.00"), total=Decimal("2000.00"),
            match_override=True, allow_match_override=False,
        )
    # Con flag + permiso pasa y queda auditado como override.
    out = create_invoice_for_order(
        request=ctx.req, actor=ctx.actor, order_id=ctx.order_id,
        subtotal=Decimal("2000.00"), tax_total=Decimal("0.00"), total=Decimal("2000.00"),
        match_override=True, allow_match_override=True,
    )
    assert out["override"] is True


def test_second_invoice_discounts_already_invoiced_drafts(ctx):
    # La primera factura (queda en DRAFT) ya consume el valor recibido…
    create_invoice_for_order(
        request=ctx.req, actor=ctx.actor, order_id=ctx.order_id,
        subtotal=Decimal("1000.00"), tax_total=Decimal("150.00"), total=Decimal("1150.00"),
    )
    # …así que una segunda por el mismo valor no tiene nada que facturar (anti doble factura).
    with pytest.raises(ProcurementMatchError, match="PROCUREMENT_MATCH_NOTHING_TO_INVOICE"):
        create_invoice_for_order(
            request=ctx.req, actor=ctx.actor, order_id=ctx.order_id,
            subtotal=Decimal("1000.00"), tax_total=Decimal("150.00"), total=Decimal("1150.00"),
        )


@pytest.mark.django_db
def test_invoice_with_nothing_received_is_rejected():
    company, branch = _scope()
    actor = _actor()
    other = _actor()
    req = _req(company, branch, actor)
    supplier = Party.objects.create(
        company=company, party_type=Party.PartyType.JURIDICAL, display_name="Prov sin entrega"
    )
    item = InventoryItem.objects.create(
        company=company, sku=f"SKU{uuid.uuid4().hex[:6]}", name="Alambre", uom=UoM.UNIT,
        default_tax_rate=Decimal("0"),
    )
    res = create_purchase_order(
        request=req, actor=actor, supplier_party_id=supplier.id,
        lines=[{"item_id": item.id, "qty": "10", "unit_cost": "100.00"}],
    )
    submit_purchase_order(request=req, actor=actor, order_id=res["order_id"])
    approve_purchase_order(request=req, actor=other, order_id=res["order_id"])
    mark_purchase_order_sent(request=req, actor=other, order_id=res["order_id"])

    with pytest.raises(ProcurementMatchError, match="PROCUREMENT_MATCH_NOTHING_TO_INVOICE"):
        create_invoice_for_order(
            request=req, actor=actor, order_id=res["order_id"],
            subtotal=Decimal("1000.00"), tax_total=Decimal("0.00"), total=Decimal("1000.00"),
        )
