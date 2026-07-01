"""Bordes de negocio de la Nota de Crédito con reingreso a stock (finder de bugs).

issue_credit_note(restock=True) debe revertir al kardex EXACTAMENTE la cantidad
que salió con el despacho de la factura original (ni de más ni de menos), al mismo
costo, y debe ser idempotente (reenviar la misma NC no reingresa dos veces).

Invariantes atacados:
  - El stock tras emitir factura (issue) baja por la cantidad vendida.
  - La NC con restock deja el stock EXACTAMENTE como antes de la venta.
  - Idempotencia: emitir la NC dos veces (misma idempotency_key) no duplica el reingreso.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.facturacion.credit_notes import issue_credit_note
from apps.kernels.facturacion.models import BillingDocument, DocStatus, DocType
from apps.kernels.facturacion.services import create_draft, issue_doc
from apps.kernels.inventarios.models import (
    InventoryItem,
    StockBalance,
    StockMovement,
    Warehouse,
)
from apps.kernels.inventarios.services import post_receive
from apps.modulos.iam.models import OrgUnit

User = get_user_model()


def _scope():
    t = uuid.uuid4().hex[:8]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H{t}", code=f"H-{t}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, parent=holding, name=f"C{t}", code=f"C-{t}")
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, parent=company, name=f"B{t}", code=f"B-{t}")
    user = User.objects.create_user(username=f"u_{t}", email=f"u_{t}@test.local", password="Secret123!")
    request = SimpleNamespace(
        company=company, branch=branch, user=user, META={}, headers={},
        path="/t/billing/", method="POST", request_id=f"req-{t}", data={},
    )
    return company, branch, user, request


def _wh_item(company, branch):
    wh = Warehouse.objects.create(company=company, branch=branch, name="Main", code=f"W{uuid.uuid4().hex[:5]}")
    item = InventoryItem.objects.create(company=company, sku=f"SKU-{uuid.uuid4().hex[:6]}", name="Item")
    return wh, item


def _qty(company, branch, wh, item) -> Decimal:
    bal = StockBalance.objects.filter(company=company, branch=branch, warehouse=wh, item=item).first()
    return bal.qty_on_hand if bal else Decimal("0.0000")


def _issued_invoice_with_inventory(request, actor, *, wh, item, qty, unit_price="100"):
    draft = create_draft(
        request=request, actor=actor, doc_type=DocType.INVOICE, series="A", currency="NIO",
        customer_name="Cliente Demo", customer_ref="C-001", is_fiscal=False,
        lines=[{
            "description": "Producto", "quantity": qty, "unit_price": unit_price, "tax_rate": "0.15",
            "inventory_item_id": item.id, "warehouse_id": wh.id,
        }],
        idempotency_key=f"inv-{uuid.uuid4().hex}",
    )
    issue_doc(
        request=request, actor=actor, doc_id=draft.doc_id,
        apply_inventory=True, idempotency_key=f"iss-{uuid.uuid4().hex}",
    )
    return BillingDocument.objects.get(id=draft.doc_id)


@pytest.mark.django_db
def test_nc_restock_reingresa_cantidad_exacta_al_kardex():
    company, branch, user, request = _scope()
    wh, item = _wh_item(company, branch)
    post_receive(
        request=request, actor=user, warehouse_id=wh.id, item_id=item.id,
        qty=Decimal("100.0000"), unit_cost=Decimal("12.000000"),
        idempotency_key=f"r-{uuid.uuid4().hex}",
    )
    assert _qty(company, branch, wh, item) == Decimal("100.0000")

    inv = _issued_invoice_with_inventory(request, user, wh=wh, item=item, qty="30")
    assert inv.status == DocStatus.ISSUED
    # La venta de 30 baja el stock a 70.
    assert _qty(company, branch, wh, item) == Decimal("70.0000")

    cn = issue_credit_note(
        request=request, actor=user, original_doc_id=inv.id,
        reason="devolución total", restock=True,
    )
    assert cn.doc_type == DocType.CREDIT_NOTE

    # El restock debe devolver EXACTAMENTE 30 → stock vuelve a 100.
    assert _qty(company, branch, wh, item) == Decimal("100.0000"), (
        f"BUG: el restock de la NC no devolvió la cantidad exacta; stock={_qty(company, branch, wh, item)} (esperado 100)"
    )


@pytest.mark.django_db
def test_nc_restock_es_idempotente_no_reingresa_dos_veces():
    company, branch, user, request = _scope()
    wh, item = _wh_item(company, branch)
    post_receive(
        request=request, actor=user, warehouse_id=wh.id, item_id=item.id,
        qty=Decimal("50.0000"), unit_cost=Decimal("8.000000"),
        idempotency_key=f"r-{uuid.uuid4().hex}",
    )
    inv = _issued_invoice_with_inventory(request, user, wh=wh, item=item, qty="20")
    assert _qty(company, branch, wh, item) == Decimal("30.0000")

    key = f"cn-{uuid.uuid4().hex}"
    cn1 = issue_credit_note(
        request=request, actor=user, original_doc_id=inv.id,
        reason="devolución", restock=True, idempotency_key=key,
    )
    assert _qty(company, branch, wh, item) == Decimal("50.0000")

    # Reenviar la MISMA NC (misma idempotency_key) no debe reingresar de nuevo.
    cn2 = issue_credit_note(
        request=request, actor=user, original_doc_id=inv.id,
        reason="devolución", restock=True, idempotency_key=key,
    )
    assert cn1.id == cn2.id
    assert _qty(company, branch, wh, item) == Decimal("50.0000"), (
        f"BUG: reenviar la NC duplicó el reingreso; stock={_qty(company, branch, wh, item)} (esperado 50)"
    )

    # Y exactamente UN movimiento de restock fue creado.
    restock_movs = StockMovement.objects.filter(
        company=company, branch=branch,
        source_module="BILLING", source_type="CREDIT_NOTE_RESTOCK", source_id=str(cn1.id),
    )
    assert restock_movs.count() == 1, (
        f"BUG: se crearon {restock_movs.count()} movimientos de restock (esperado 1)"
    )
