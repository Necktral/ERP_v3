"""Tests del precio de venta por artículo (A1 del programa de completitud):
- sale_price + default_tax_rate en crear/leer/actualizar
- lookup exacto por código de barras (?barcode=) para el escáner POS
- validaciones (precio negativo, tasa fuera de 0-1) y permisos del PATCH
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.kernels.inventarios.models import InventoryItem
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

User = get_user_model()

PERMS = [
    "inventory.item.create",
    "inventory.item.read",
    "inventory.item.update",
]


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


@pytest.mark.django_db
def test_create_item_with_price_and_read_back():
    company, branch = _mk_scope()
    c = _client(company, branch)

    r = c.post(
        "/api/inventory/items/",
        {
            "sku": "GAS-25LB",
            "name": "Cilindro de gas 25 lb",
            "barcode": "7501031311309",
            "sale_price": "850.00",
            "default_tax_rate": "0.15",
        },
        format="json",
    )
    assert r.status_code == 201, r.data
    assert Decimal(r.data["sale_price"]) == Decimal("850.0000")
    assert Decimal(r.data["default_tax_rate"]) == Decimal("0.1500")

    # Sin precio: queda null (no se inventa 0).
    r2 = c.post("/api/inventory/items/", {"sku": "SRV-FLETE", "name": "Flete local"}, format="json")
    assert r2.status_code == 201
    assert r2.data["sale_price"] is None
    assert Decimal(r2.data["default_tax_rate"]) == Decimal("0.1500")


@pytest.mark.django_db
def test_barcode_exact_lookup_for_scanner():
    company, branch = _mk_scope()
    c = _client(company, branch)

    c.post(
        "/api/inventory/items/",
        {"sku": "A-1", "name": "Arroz 96/4", "barcode": "111222333", "sale_price": "32.50"},
        format="json",
    )
    c.post(
        "/api/inventory/items/",
        {"sku": "A-2", "name": "Azúcar", "barcode": "1112223334"},
        format="json",
    )

    # Exacto: NO matchea el barcode más largo que lo contiene.
    r = c.get("/api/inventory/items/?barcode=111222333")
    assert r.status_code == 200
    assert r.data["count"] == 1
    assert r.data["results"][0]["sku"] == "A-1"
    assert Decimal(r.data["results"][0]["sale_price"]) == Decimal("32.5000")

    # Barcode inexistente: 0 resultados (la caja muestra "no encontrado").
    r = c.get("/api/inventory/items/?barcode=999999999")
    assert r.data["count"] == 0


@pytest.mark.django_db
def test_patch_updates_price_and_audits_nothing_else():
    company, branch = _mk_scope()
    c = _client(company, branch)

    r = c.post("/api/inventory/items/", {"sku": "P-1", "name": "Café molido", "sale_price": "120.00"}, format="json")
    item_id = r.data["id"]

    r = c.patch(f"/api/inventory/items/{item_id}/", {"sale_price": "135.00"}, format="json")
    assert r.status_code == 200, r.data
    assert Decimal(r.data["sale_price"]) == Decimal("135.0000")
    # El resto queda intacto.
    assert r.data["sku"] == "P-1"
    assert r.data["name"] == "Café molido"

    item = InventoryItem.objects.get(id=item_id)
    assert item.sale_price == Decimal("135.0000")


@pytest.mark.django_db
def test_price_validations():
    company, branch = _mk_scope()
    c = _client(company, branch)

    r = c.post("/api/inventory/items/", {"sku": "N-1", "name": "X", "sale_price": "-5"}, format="json")
    assert r.status_code in (400, 422)

    r = c.post("/api/inventory/items/", {"sku": "N-2", "name": "X", "default_tax_rate": "1.5"}, format="json")
    assert r.status_code in (400, 422)


@pytest.mark.django_db
def test_patch_requires_update_permission():
    company, branch = _mk_scope()
    reader = _client(company, branch, perms=["inventory.item.read", "inventory.item.create"])

    r = reader.post("/api/inventory/items/", {"sku": "R-1", "name": "Sólo lectura"}, format="json")
    item_id = r.data["id"]

    r = reader.patch(f"/api/inventory/items/{item_id}/", {"sale_price": "10.00"}, format="json")
    assert r.status_code == 403
