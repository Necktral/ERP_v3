"""Autorización de supervisor en caja (override de precio/descuento).

Cuando el cajero NO tiene `sales.pos.price_override`, un supervisor que SÍ lo tiene se
reautentica y emite un GRANT firmado y efímero; la venta lo adjunta y el descuento
queda habilitado SOLO para esa caja/sucursal/cajero. Todo queda auditado.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.kernels.inventarios.models import InventoryItem, UoM
from apps.kernels.inventarios.services import create_warehouse, post_receive
from apps.kernels.payments.services import open_cash_session_for_scope
from apps.modulos.audit.models import AuditEvent
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission
from apps.modulos.ventas.services import (
    SalesError,
    grant_pos_override,
    verify_pos_override_grant,
)
from types import SimpleNamespace

User = get_user_model()
UT = OrgUnit.UnitType


def _scope():
    t = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=UT.HOLDING, name=f"H{t}", code=f"H-{t}")
    company = OrgUnit.objects.create(unit_type=UT.COMPANY, parent=holding, name=f"C{t}", code=f"C-{t}")
    branch = OrgUnit.objects.create(unit_type=UT.BRANCH, parent=company, name=f"B{t}", code=f"B-{t}")
    return holding, company, branch


def _req(company, branch, user):
    return SimpleNamespace(
        company=company, branch=branch, user=user, META={}, headers={},
        path="/test/sales/", method="POST", request_id=f"req-{uuid.uuid4().hex[:8]}",
    )


def _seed_item(req, company, branch, actor, *, price="100.00", tax="0", qty="10"):
    wh = create_warehouse(request=req, company=company, branch=branch, actor_user=actor, name="Bodega", code="W1")
    item = InventoryItem.objects.create(
        company=company, sku=f"SKU{uuid.uuid4().hex[:6]}", name="Aceite 1L", uom=UoM.UNIT,
        barcode=f"75{uuid.uuid4().hex[:10]}",
        sale_price=Decimal(price), default_tax_rate=Decimal(tax),
    )
    post_receive(
        request=req, actor=actor, warehouse_id=wh.id, item_id=item.id,
        qty=Decimal(qty), unit_cost=Decimal("60"), idempotency_key=f"rcv-{uuid.uuid4().hex}",
    )
    return wh, item


def _client(company, branch, perms, *, password="x"):
    username = f"u_{uuid.uuid4().hex[:10]}"
    user = User.objects.create_user(username=username, email=f"{username}@t.local", password=password)
    UserMembership.objects.create(user=user, org_unit=company, is_active=True)
    UserMembership.objects.create(user=user, org_unit=branch, is_active=True)

    role = Role.objects.create(name=f"r_{uuid.uuid4().hex[:8]}", is_active=True)
    for p in perms:
        perm, _ = Permission.objects.get_or_create(code=p, defaults={"description": p, "is_active": True})
        RolePermission.objects.get_or_create(role=role, permission=perm)
    RoleAssignment.objects.create(user=user, role=role, org_unit=company, is_active=True)
    RoleAssignment.objects.create(user=user, role=role, org_unit=branch, is_active=True)

    c = APIClient()
    login = c.post("/api/auth/login/", {"username": username, "password": password}, format="json")
    assert login.status_code == 200
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    c.defaults["HTTP_X_COMPANY_ID"] = str(company.id)
    c.defaults["HTTP_X_BRANCH_ID"] = str(branch.id)
    return c, user


@pytest.mark.django_db
def test_supervisor_grant_lets_cashier_without_permission_apply_discount():
    _h, company, branch = _scope()
    seeder = _user_only()
    req = _req(company, branch, seeder)
    wh, item = _seed_item(req, company, branch, seeder, price="100.00", tax="0")

    # Cajero: solo vende, NO puede override.
    c_caja, cajero = _client(company, branch, perms=["sales.pos.sell"], password="cajaPASS1")
    open_cash_session_for_scope(company=company, branch=branch, actor=cajero)

    # Supervisor: tiene el permiso de override.
    _c_sup, supervisor = _client(
        company, branch, perms=["sales.pos.sell", "sales.pos.price_override"], password="superPASS1"
    )

    # Sin autorización, el descuento es rechazado (422).
    r = c_caja.post("/api/sales/pos-sale/", {
        "warehouse_id": wh.id, "idempotency_key": "OVR-NO",
        "lines": [{"inventory_item_id": item.id, "quantity": "1", "discount_pct": "0.10"}],
        "payments": [{"method": "CASH", "amount": "90.00"}],
    }, format="json")
    assert r.status_code == 422
    assert r.data["error"]["message"] == "SALES_PRICE_OVERRIDE_FORBIDDEN"

    # El supervisor autoriza desde la caja del cajero.
    g = c_caja.post("/api/sales/pos-override/", {
        "supervisor_username": supervisor.get_username(),
        "supervisor_password": "superPASS1",
        "reason": "Cliente mayorista de confianza",
    }, format="json")
    assert g.status_code == 201, g.data
    grant = g.data["grant"]
    assert g.data["authorized_by_id"] == supervisor.id

    # Con el grant, el mismo descuento ahora pasa: total 100 × 0.90 = 90.00.
    r = c_caja.post("/api/sales/pos-sale/", {
        "warehouse_id": wh.id, "idempotency_key": "OVR-OK",
        "override_grant": grant,
        "lines": [{"inventory_item_id": item.id, "quantity": "1", "discount_pct": "0.10"}],
        "payments": [{"method": "CASH", "amount": "90.00"}],
    }, format="json")
    assert r.status_code == 201, r.data
    assert r.data["total"] == "90.00"

    # Quedó auditado: el supervisor concedió y el override se usó atado a la factura.
    assert AuditEvent.objects.filter(
        event_type="SALES_POS_OVERRIDE_GRANTED", actor_user=supervisor
    ).exists()
    assert AuditEvent.objects.filter(
        event_type="SALES_POS_OVERRIDE_USED", subject_id=str(r.data["doc_id"])
    ).exists()


@pytest.mark.django_db
def test_grant_rejects_bad_credentials_and_unauthorized_supervisor():
    _h, company, branch = _scope()
    c_caja, cajero = _client(company, branch, perms=["sales.pos.sell"], password="cajaPASS1")

    # Supervisor sin el permiso de override.
    _c, no_sup = _client(company, branch, perms=["sales.pos.sell"], password="weakSup1")

    # Contraseña incorrecta → 401.
    r = c_caja.post("/api/sales/pos-override/", {
        "supervisor_username": no_sup.get_username(),
        "supervisor_password": "INCORRECTA",
        "reason": "motivo válido",
    }, format="json")
    assert r.status_code == 401
    assert r.data["error"]["message"] == "SALES_OVERRIDE_BAD_CREDENTIALS"

    # Credenciales correctas pero sin permiso de override → 403.
    r = c_caja.post("/api/sales/pos-override/", {
        "supervisor_username": no_sup.get_username(),
        "supervisor_password": "weakSup1",
        "reason": "motivo válido",
    }, format="json")
    assert r.status_code == 403
    assert r.data["error"]["message"] == "SALES_OVERRIDE_NOT_AUTHORIZED"


@pytest.mark.django_db
def test_cashier_cannot_authorize_themselves():
    _h, company, branch = _scope()
    # El cajero tiene el permiso de override pero igual no puede autoSerse: SoD.
    c_caja, cajero = _client(
        company, branch, perms=["sales.pos.sell", "sales.pos.price_override"], password="selfPASS1"
    )
    r = c_caja.post("/api/sales/pos-override/", {
        "supervisor_username": cajero.get_username(),
        "supervisor_password": "selfPASS1",
        "reason": "intento de auto-autorización",
    }, format="json")
    assert r.status_code == 422
    assert r.data["error"]["message"] == "SALES_OVERRIDE_SELF"


@pytest.mark.django_db
def test_verify_grant_rejects_tampering_and_cross_scope():
    _h, company, branch = _scope()
    _h2, company2, branch2 = _scope()
    seeder = _user_only()
    cajero = _user_only()

    # Grant válido para (company, branch, cajero).
    grant = grant_pos_override(
        request=_req(company, branch, seeder), actor=cajero,
        supervisor_username=_make_supervisor(company, branch).get_username(),
        supervisor_password="supPASS1", reason="motivo válido",
    )["grant"]

    # Verifica bien en su propio scope.
    assert isinstance(verify_pos_override_grant(grant=grant, company=company, branch=branch, cashier=cajero), int)

    # Otra empresa → inválido.
    with pytest.raises(SalesError) as exc:
        verify_pos_override_grant(grant=grant, company=company2, branch=branch2, cashier=cajero)
    assert str(exc.value) == "SALES_OVERRIDE_INVALID"

    # Grant manipulado → inválido.
    with pytest.raises(SalesError) as exc:
        verify_pos_override_grant(grant=grant + "x", company=company, branch=branch, cashier=cajero)
    assert str(exc.value) == "SALES_OVERRIDE_INVALID"


# --- helpers locales ---------------------------------------------------------------

def _user_only():
    t = uuid.uuid4().hex[:8]
    return User.objects.create_user(username=f"u_{t}", email=f"u_{t}@t.local", password="pass12345")


def _make_supervisor(company, branch):
    username = f"sup_{uuid.uuid4().hex[:8]}"
    user = User.objects.create_user(username=username, email=f"{username}@t.local", password="supPASS1")
    role = Role.objects.create(name=f"sup_{uuid.uuid4().hex[:6]}", is_active=True)
    perm, _ = Permission.objects.get_or_create(
        code="sales.pos.price_override", defaults={"description": "x", "is_active": True}
    )
    RolePermission.objects.get_or_create(role=role, permission=perm)
    RoleAssignment.objects.create(user=user, role=role, org_unit=company, is_active=True)
    RoleAssignment.objects.create(user=user, role=role, org_unit=branch, is_active=True)
    return user
