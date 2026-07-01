"""Tests de la API de administración de listas de precios (§12).

Cubre CRUD de lista, upsert/borrado de tramos, asignación a party y a segmento con XOR,
conflicto de asignación activa única por party, gating RBAC (read vs write) y el lazo
end-to-end: tras crear lista+tramo+asignación, ``resolve_sale_price`` devuelve el precio
listado (el precio lo resuelve el servidor, esta API solo administra).
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.kernels.inventarios.models import InventoryItem, UoM
from apps.kernels.inventarios.pricing import resolve_sale_price
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.parties.models import Party
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

User = get_user_model()

PERMS = ["inventory.pricelist.read", "inventory.pricelist.write"]


def _mk_scope():
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H-{uuid.uuid4().hex[:6]}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name=f"C-{uuid.uuid4().hex[:6]}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, name=f"B-{uuid.uuid4().hex[:6]}", parent=company)
    return company, branch


def _client(company, branch, perms=None):
    username = f"u_{uuid.uuid4().hex[:10]}"
    user = User.objects.create_user(username=username, password="x")
    UserMembership.objects.create(user=user, org_unit=company, is_active=True)
    UserMembership.objects.create(user=user, org_unit=branch, is_active=True)

    role = Role.objects.create(name=f"r_{uuid.uuid4().hex[:8]}", is_active=True)
    for p in (perms if perms is not None else PERMS):
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
    return c


def _item(company, *, sale="100.00"):
    return InventoryItem.objects.create(
        company=company, sku=f"S{uuid.uuid4().hex[:6]}", name="Aceite", uom=UoM.UNIT,
        sale_price=Decimal(sale),
    )


@pytest.mark.django_db
def test_create_and_read_pricelist():
    company, branch = _mk_scope()
    c = _client(company, branch)

    r = c.post("/api/inventory/pricelists/", {"name": "VIP", "currency": "usd"}, format="json")
    assert r.status_code == 201, r.data
    assert r.data["name"] == "VIP"
    assert r.data["currency"] == "USD"  # normalizado
    assert r.data["is_active"] is True
    assert r.data["items"] == [] and r.data["assignments"] == []

    pl_id = r.data["id"]
    r = c.get(f"/api/inventory/pricelists/{pl_id}/")
    assert r.status_code == 200
    assert r.data["name"] == "VIP"

    # Nombre duplicado en la misma empresa → 409.
    r = c.post("/api/inventory/pricelists/", {"name": "VIP"}, format="json")
    assert r.status_code == 409
    assert r.data["error"]["message"] == "PRICELIST_NAME_CONFLICT"


@pytest.mark.django_db
def test_tramos_upsert_and_delete():
    company, branch = _mk_scope()
    c = _client(company, branch)
    item = _item(company)
    pl_id = c.post("/api/inventory/pricelists/", {"name": "L1"}, format="json").data["id"]

    # Alta de tramo (201).
    r = c.post(f"/api/inventory/pricelists/{pl_id}/items/",
               {"item_id": item.id, "min_qty": "0", "price": "80.00"}, format="json")
    assert r.status_code == 201, r.data
    line_id = r.data["id"]

    # Upsert mismo (item, min_qty) → actualiza precio (200, no duplica).
    r = c.post(f"/api/inventory/pricelists/{pl_id}/items/",
               {"item_id": item.id, "min_qty": "0", "price": "75.00"}, format="json")
    assert r.status_code == 200, r.data
    assert r.data["id"] == line_id
    assert Decimal(r.data["price"]) == Decimal("75.0000")

    r = c.get(f"/api/inventory/pricelists/{pl_id}/items/")
    assert len(r.data["results"]) == 1

    # Ítem inexistente → 404.
    r = c.post(f"/api/inventory/pricelists/{pl_id}/items/",
               {"item_id": 999999, "price": "10"}, format="json")
    assert r.status_code == 404 and r.data["error"]["message"] == "INVENTORY_ITEM_NOT_FOUND"

    # Borrado de tramo.
    r = c.delete(f"/api/inventory/pricelists/{pl_id}/items/{line_id}/")
    assert r.status_code == 204
    assert c.get(f"/api/inventory/pricelists/{pl_id}/items/").data["results"] == []


@pytest.mark.django_db
def test_assignment_party_segment_xor_and_conflict():
    company, branch = _mk_scope()
    c = _client(company, branch)
    party = Party.objects.create(company=company, party_type=Party.PartyType.NATURAL, display_name="Cliente")
    pl_a = c.post("/api/inventory/pricelists/", {"name": "A"}, format="json").data["id"]
    pl_b = c.post("/api/inventory/pricelists/", {"name": "B"}, format="json").data["id"]

    # XOR: ni party ni segmento → 400/422.
    r = c.post(f"/api/inventory/pricelists/{pl_a}/assignments/", {}, format="json")
    assert r.status_code in (400, 422)
    # XOR: ambos → 400/422.
    r = c.post(f"/api/inventory/pricelists/{pl_a}/assignments/",
               {"party_id": party.id, "segment": "EMPLOYEE"}, format="json")
    assert r.status_code in (400, 422)

    # Asignar a segmento (normaliza mayúsculas).
    r = c.post(f"/api/inventory/pricelists/{pl_a}/assignments/", {"segment": "employee"}, format="json")
    assert r.status_code == 201 and r.data["segment"] == "EMPLOYEE"

    # Asignar a party.
    r = c.post(f"/api/inventory/pricelists/{pl_a}/assignments/", {"party_id": party.id}, format="json")
    assert r.status_code == 201, r.data
    assign_id = r.data["id"]

    # Mismo party activo en OTRA lista → conflicto (única asignación activa por party/empresa).
    r = c.post(f"/api/inventory/pricelists/{pl_b}/assignments/", {"party_id": party.id}, format="json")
    assert r.status_code == 409 and r.data["error"]["message"] == "PRICELIST_ASSIGNMENT_CONFLICT"

    # Party inexistente → 404.
    r = c.post(f"/api/inventory/pricelists/{pl_a}/assignments/", {"party_id": 999999}, format="json")
    assert r.status_code == 404 and r.data["error"]["message"] == "PARTY_NOT_FOUND"

    # Desasignar (soft) → libera para reasignar.
    r = c.delete(f"/api/inventory/pricelists/{pl_a}/assignments/{assign_id}/")
    assert r.status_code == 204
    r = c.post(f"/api/inventory/pricelists/{pl_b}/assignments/", {"party_id": party.id}, format="json")
    assert r.status_code == 201


@pytest.mark.django_db
def test_patch_deactivate_and_currency_filter():
    company, branch = _mk_scope()
    c = _client(company, branch)
    c.post("/api/inventory/pricelists/", {"name": "NIO-1", "currency": "NIO"}, format="json")
    usd_id = c.post("/api/inventory/pricelists/", {"name": "USD-1", "currency": "USD"}, format="json").data["id"]

    r = c.get("/api/inventory/pricelists/?currency=USD")
    assert r.data["count"] == 1 and r.data["results"][0]["id"] == usd_id

    r = c.patch(f"/api/inventory/pricelists/{usd_id}/", {"is_active": False}, format="json")
    assert r.status_code == 200 and r.data["is_active"] is False
    assert c.get("/api/inventory/pricelists/?is_active=true").data["count"] == 1


@pytest.mark.django_db
def test_write_requires_write_permission():
    company, branch = _mk_scope()
    reader = _client(company, branch, perms=["inventory.pricelist.read"])
    r = reader.post("/api/inventory/pricelists/", {"name": "X"}, format="json")
    assert r.status_code == 403


@pytest.mark.django_db
def test_end_to_end_resolver_uses_listed_price():
    company, branch = _mk_scope()
    c = _client(company, branch)
    item = _item(company, sale="100.00")
    party = Party.objects.create(company=company, party_type=Party.PartyType.NATURAL, display_name="VIP")

    pl_id = c.post("/api/inventory/pricelists/", {"name": "VIP", "currency": "NIO"}, format="json").data["id"]
    c.post(f"/api/inventory/pricelists/{pl_id}/items/",
           {"item_id": item.id, "min_qty": "0", "price": "80.00"}, format="json")
    c.post(f"/api/inventory/pricelists/{pl_id}/assignments/", {"party_id": party.id}, format="json")

    # El servidor resuelve el precio listado para ese cliente.
    assert resolve_sale_price(company=company, item=item, qty=Decimal("1"), party=party) == Decimal("80.00")
    # Sin party cae al precio base.
    assert resolve_sale_price(company=company, item=item, qty=Decimal("1")) == Decimal("100.00")
