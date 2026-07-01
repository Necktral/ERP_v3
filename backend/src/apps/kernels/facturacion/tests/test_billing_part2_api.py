"""Tests de la parte 2 de facturación expuesta por API (A4 del programa de completitud):

- Abonos (pagos múltiples): UNPAID → PARTIAL → PAID y reversa.
- Nota de crédito vinculada con REINGRESO de inventario (devolución física).
- Cotización → factura.
- Pedidos con aprobación de crédito SoD (maker ≠ checker → 409).
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.kernels.facturacion.models import BillingDocument, DocStatus, DocType, PaymentStatus
from apps.kernels.inventarios.models import InventoryItem, StockBalance, UoM
from apps.kernels.inventarios.services import create_warehouse, post_receive
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

User = get_user_model()

BILLING_PERMS = [
    "billing.doc.read",
    "billing.doc.create",
    "billing.doc.issue",
    "billing.payment.read",
    "billing.payment.create",
    "billing.payment.reverse",
    "billing.credit_note.issue",
    "billing.order.read",
    "billing.order.create",
    "billing.order.submit",
    "billing.order.approve",
]


def _scope():
    t = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H{t}", code=f"H-{t}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, parent=holding, name=f"C{t}", code=f"C-{t}")
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, parent=company, name=f"B{t}", code=f"B-{t}")
    return company, branch


def _client(company, branch, perms=BILLING_PERMS):
    username = f"u_{uuid.uuid4().hex[:10]}"
    user = User.objects.create_user(username=username, email=f"{username}@t.local", password="x")
    UserMembership.objects.create(user=user, org_unit=company, is_active=True)
    UserMembership.objects.create(user=user, org_unit=branch, is_active=True)

    role = Role.objects.create(name=f"r_{uuid.uuid4().hex[:8]}", is_active=True)
    for p in perms:
        perm, _ = Permission.objects.get_or_create(code=p, defaults={"description": p, "is_active": True})
        RolePermission.objects.get_or_create(role=role, permission=perm)
    RoleAssignment.objects.create(user=user, role=role, org_unit=company, is_active=True)
    RoleAssignment.objects.create(user=user, role=role, org_unit=branch, is_active=True)

    c = APIClient()
    login = c.post("/api/auth/login/", {"username": username, "password": "x"}, format="json")
    assert login.status_code == 200
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    c.defaults["HTTP_X_COMPANY_ID"] = str(company.id)
    c.defaults["HTTP_X_BRANCH_ID"] = str(branch.id)
    return c, user


def _issued_invoice(c, *, lines=None, total_check=None) -> int:
    lines = lines or [{"description": "Servicio", "quantity": "1", "unit_price": "100", "tax_rate": "0.15"}]
    r = c.post("/api/billing/docs/", {
        "doc_type": "INVOICE", "customer_name": "Cliente Demo",
        "is_fiscal": False, "lines": lines,
        "idempotency_key": f"inv-{uuid.uuid4().hex}",
    }, format="json")
    assert r.status_code == 201, r.data
    doc_id = r.data["id"]
    r = c.post(f"/api/billing/docs/{doc_id}/issue/", {}, format="json")
    assert r.status_code == 200, r.data
    if total_check is not None:
        doc = BillingDocument.objects.get(id=doc_id)
        assert doc.total == Decimal(total_check)
    return doc_id


# ---------------------------------------------------------------------------
# Abonos
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_partial_payments_lifecycle():
    company, branch = _scope()
    c, _ = _client(company, branch)
    doc_id = _issued_invoice(c, total_check="115.00")

    # Abono parcial → PARTIAL
    r = c.post(f"/api/billing/docs/{doc_id}/payments/", {
        "payment_method": "CASH", "amount": "50.00",
    }, format="json")
    assert r.status_code == 201, r.data
    assert r.data["payment_status"] == PaymentStatus.PARTIAL
    assert r.data["amount_paid"] == "50.00"

    # Segundo abono completa → PAID
    r = c.post(f"/api/billing/docs/{doc_id}/payments/", {
        "payment_method": "TRANSFER", "amount": "65.00", "reference": "TX-9",
    }, format="json")
    assert r.status_code == 201
    assert r.data["payment_status"] == PaymentStatus.PAID

    # Historial
    r = c.get(f"/api/billing/docs/{doc_id}/payments/")
    assert r.status_code == 200
    assert len(r.data["results"]) == 2
    payment_id = r.data["results"][0]["id"]

    # Reversa → vuelve a PARTIAL
    r = c.post(f"/api/billing/docs/{doc_id}/payments/{payment_id}/reverse/", {
        "reason": "error de caja",
    }, format="json")
    assert r.status_code == 200
    assert r.data["doc_payment_status"] == PaymentStatus.PARTIAL


@pytest.mark.django_db
def test_payments_require_permission():
    company, branch = _scope()
    reader, _ = _client(company, branch, perms=["billing.doc.read", "billing.doc.create", "billing.doc.issue"])
    doc_id = _issued_invoice(reader)

    r = reader.post(f"/api/billing/docs/{doc_id}/payments/", {
        "payment_method": "CASH", "amount": "10.00",
    }, format="json")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Nota de crédito vinculada + restock
# ---------------------------------------------------------------------------

def _stock(company, branch, wh_id, item_id):
    bal = StockBalance.objects.filter(company=company, branch=branch, warehouse_id=wh_id, item_id=item_id).first()
    return bal.qty_on_hand if bal else Decimal("0.0000")


@pytest.mark.django_db
def test_credit_note_with_restock_restores_inventory():
    company, branch = _scope()
    c, user = _client(company, branch)

    req = SimpleNamespace(company=company, branch=branch, user=user, META={}, headers={},
                          path="/t/", method="POST", request_id=f"r-{uuid.uuid4().hex[:8]}")
    wh = create_warehouse(request=req, company=company, branch=branch, actor_user=user, name="Bodega", code="W1")
    item = InventoryItem.objects.create(company=company, sku=f"S{uuid.uuid4().hex[:6]}", name="Frijol", uom=UoM.UNIT)
    post_receive(request=req, actor=user, warehouse_id=wh.id, item_id=item.id,
                 qty=Decimal("10"), unit_cost=Decimal("20"), idempotency_key=f"rc-{uuid.uuid4().hex}")

    # Factura con inventario: stock 10 → 7
    r = c.post("/api/billing/docs/", {
        "doc_type": "INVOICE", "customer_name": "Cliente Dev",
        "is_fiscal": False,
        "lines": [{"description": "Frijol", "quantity": "3", "unit_price": "40", "tax_rate": "0",
                   "inventory_item_id": item.id, "warehouse_id": wh.id}],
        "idempotency_key": f"inv-{uuid.uuid4().hex}",
    }, format="json")
    doc_id = r.data["id"]
    r = c.post(f"/api/billing/docs/{doc_id}/issue/", {"apply_inventory": True}, format="json")
    assert r.status_code == 200, r.data
    assert _stock(company, branch, wh.id, item.id) == Decimal("7.0000")

    # Nota de crédito TOTAL con reingreso: stock 7 → 10
    r = c.post(f"/api/billing/docs/{doc_id}/credit-note/", {
        "reason": "producto devuelto", "restock": True,
    }, format="json")
    assert r.status_code == 201, r.data
    assert r.data["total"] == "120.00"
    assert _stock(company, branch, wh.id, item.id) == Decimal("10.0000")

    original = BillingDocument.objects.get(id=doc_id)
    assert original.credited_total == Decimal("120.00")

    # Segunda NC: ya no hay saldo acreditable → 422
    r = c.post(f"/api/billing/docs/{doc_id}/credit-note/", {
        "reason": "doble devolución", "restock": True,
    }, format="json")
    assert r.status_code == 422


@pytest.mark.django_db
def test_partial_credit_note_cannot_restock():
    company, branch = _scope()
    c, _ = _client(company, branch)
    doc_id = _issued_invoice(c)

    r = c.post(f"/api/billing/docs/{doc_id}/credit-note/", {
        "reason": "parcial",
        "restock": True,
        "lines": [{"description": "Servicio", "quantity": "1", "unit_price": "10", "tax_rate": "0"}],
    }, format="json")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Cotización → Factura
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_convert_quote_to_invoice():
    company, branch = _scope()
    c, _ = _client(company, branch)

    r = c.post("/api/billing/docs/", {
        "doc_type": "QUOTE", "customer_name": "Prospecto",
        "is_fiscal": False,
        "lines": [{"description": "Urea 46%", "quantity": "5", "unit_price": "950", "tax_rate": "0.15"}],
        "idempotency_key": f"q-{uuid.uuid4().hex}",
    }, format="json")
    assert r.status_code == 201
    quote_id = r.data["id"]

    r = c.post(f"/api/billing/docs/{quote_id}/convert/", {}, format="json")
    assert r.status_code == 201, r.data
    invoice_id = r.data["doc_id"]
    assert invoice_id != quote_id

    inv = BillingDocument.objects.get(id=invoice_id)
    quote = BillingDocument.objects.get(id=quote_id)
    assert inv.doc_type == DocType.INVOICE
    assert inv.status == DocStatus.DRAFT
    assert inv.total == quote.total
    assert inv.source_type == "FROM_QUOTE"
    assert inv.source_id == str(quote_id)

    # No se convierte una factura (solo QUOTE)
    r = c.post(f"/api/billing/docs/{invoice_id}/convert/", {}, format="json")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Pedidos + crédito SoD
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_order_credit_flow_enforces_sod():
    company, branch = _scope()
    maker, _ = _client(company, branch)
    checker, _ = _client(company, branch)

    r = maker.post("/api/billing/orders/", {
        "customer_name": "Don Encargo",
        "lines": [{"description": "Bomba de mochila", "quantity": "2", "unit_price": "1500", "tax_rate": "0.15"}],
        "notes": "pedido especial",
    }, format="json")
    assert r.status_code == 201, r.data
    order_id = r.data["order_id"]
    assert r.data["status"] == "DRAFT"

    r = maker.post(f"/api/billing/orders/{order_id}/submit-credit/", {
        "request_notes": "cliente conocido",
    }, format="json")
    assert r.status_code == 200, r.data
    approval_id = r.data["approval_id"]
    assert r.data["status"] == "PENDING_APPROVAL"

    # SoD: el mismo usuario que solicitó NO puede resolver → 409
    r = maker.post(f"/api/billing/credit-approvals/{approval_id}/resolve/", {
        "approved": True,
    }, format="json")
    assert r.status_code == 409

    # Otro usuario con permiso de checker aprueba.
    r = checker.post(f"/api/billing/credit-approvals/{approval_id}/resolve/", {
        "approved": True, "resolution_notes": "ok gerencia",
    }, format="json")
    assert r.status_code == 200, r.data
    assert r.data["status"] == "APPROVED"

    # El pedido quedó aprobado y listado.
    r = maker.get("/api/billing/orders/?status=APPROVED")
    assert r.status_code == 200
    assert any(o["id"] == order_id and o["credit_status"] == "APPROVED" for o in r.data["results"])
