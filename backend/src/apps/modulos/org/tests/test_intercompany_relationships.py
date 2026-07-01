"""Tests del registro SIMPLE de relaciones intercompañía (sin montos ni cuentas).

Solo declara pares de empresas + tipo + nota + activo, acotado al holding del
usuario. Escritura exige `org.module.manage` ("habilitar la opción").
"""
from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.org.models import IntercompanyRelationship
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

User = get_user_model()
UT = OrgUnit.UnitType
URL = "/api/org/intercompany-relationships/"

READ_WRITE = ["org.module.read", "org.module.manage"]
READ_ONLY = ["org.module.read"]


def _holding(tag):
    return OrgUnit.objects.create(unit_type=UT.HOLDING, name=f"H_{tag}")


def _company(holding, tag):
    return OrgUnit.objects.create(unit_type=UT.COMPANY, name=f"C_{tag}", parent=holding)


def _client(*, memberships, perm_codes):
    username = f"ic_{uuid.uuid4().hex[:8]}"
    user = User.objects.create_user(username=username, email=f"{username}@t.local", password="pass12345")
    for ou in memberships:
        UserMembership.objects.create(user=user, org_unit=ou, is_active=True)
    role = Role.objects.create(name=f"role_{uuid.uuid4().hex[:8]}", is_active=True)
    for code in perm_codes:
        perm, _ = Permission.objects.get_or_create(code=code, defaults={"description": code, "is_active": True})
        RolePermission.objects.get_or_create(role=role, permission=perm)
    for ou in memberships:
        RoleAssignment.objects.create(user=user, role=role, org_unit=ou, is_active=True)
    client = APIClient()
    login = client.post("/api/auth/login/", {"username": user.username, "password": "pass12345"}, format="json")
    assert login.status_code == 200, login.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data.get('access')}")
    client.defaults["HTTP_X_COMPANY_ID"] = str(memberships[0].id)
    return client


def _two_companies():
    h = _holding(uuid.uuid4().hex[:6])
    return h, _company(h, "FINCA"), _company(h, "COMI")


@pytest.mark.django_db
def test_create_relationship():
    _, finca, comi = _two_companies()
    client = _client(memberships=[finca, comi], perm_codes=READ_WRITE)
    r = client.post(
        URL,
        {"company_a_id": finca.id, "company_b_id": comi.id,
         "relationship_type": "CXC", "note": "Trabajadores compran a crédito"},
        format="json",
    )
    assert r.status_code == 201, r.data
    assert r.data["company_a_id"] == finca.id
    assert r.data["company_b_id"] == comi.id
    assert r.data["relationship_type"] == "CXC"
    assert r.data["relationship_type_label"] == "Cuenta por cobrar (CxC)"
    assert r.data["is_active"] is True
    assert IntercompanyRelationship.objects.filter(company_a=finca, company_b=comi).count() == 1


@pytest.mark.django_db
def test_create_requires_distinct_companies():
    _, finca, comi = _two_companies()
    client = _client(memberships=[finca, comi], perm_codes=READ_WRITE)
    r = client.post(
        URL, {"company_a_id": finca.id, "company_b_id": finca.id, "relationship_type": "OTHER"}, format="json"
    )
    assert r.status_code == 400, r.data


@pytest.mark.django_db
def test_create_requires_same_holding():
    _, finca, comi = _two_companies()
    other_h = _holding(uuid.uuid4().hex[:6])
    ajena = _company(other_h, "AJENA")
    # el usuario tiene acceso a ajena (membresía) pero es de OTRO holding
    client = _client(memberships=[finca, ajena], perm_codes=READ_WRITE)
    r = client.post(
        URL, {"company_a_id": finca.id, "company_b_id": ajena.id, "relationship_type": "OTHER"}, format="json"
    )
    assert r.status_code == 400, r.data


@pytest.mark.django_db
def test_list_only_accessible_holding():
    _, finca, comi = _two_companies()
    client = _client(memberships=[finca, comi], perm_codes=READ_WRITE)
    client.post(URL, {"company_a_id": finca.id, "company_b_id": comi.id, "relationship_type": "INVENTORY"}, format="json")
    r = client.get(URL)
    assert r.status_code == 200, r.data
    assert r.data["count"] == 1
    assert r.data["results"][0]["relationship_type"] == "INVENTORY"


@pytest.mark.django_db
def test_toggle_active_and_dedup():
    _, finca, comi = _two_companies()
    client = _client(memberships=[finca, comi], perm_codes=READ_WRITE)
    created = client.post(
        URL, {"company_a_id": finca.id, "company_b_id": comi.id, "relationship_type": "CXC"}, format="json"
    ).data
    # Toggle a inactivo
    u = client.patch(f"{URL}{created['id']}/", {"is_active": False}, format="json")
    assert u.status_code == 200, u.data
    assert u.data["is_active"] is False
    # Duplicado del mismo (a,b,tipo) -> 409
    dup = client.post(
        URL, {"company_a_id": finca.id, "company_b_id": comi.id, "relationship_type": "CXC"}, format="json"
    )
    assert dup.status_code == 409, dup.data


@pytest.mark.django_db
def test_write_requires_manage_permission():
    _, finca, comi = _two_companies()
    client = _client(memberships=[finca, comi], perm_codes=READ_ONLY)
    r = client.post(
        URL, {"company_a_id": finca.id, "company_b_id": comi.id, "relationship_type": "OTHER"}, format="json"
    )
    assert r.status_code == 403, r.data


@pytest.mark.django_db
def test_delete_relationship():
    _, finca, comi = _two_companies()
    client = _client(memberships=[finca, comi], perm_codes=READ_WRITE)
    created = client.post(
        URL, {"company_a_id": finca.id, "company_b_id": comi.id, "relationship_type": "OTHER"}, format="json"
    ).data
    d = client.delete(f"{URL}{created['id']}/")
    assert d.status_code == 204
    assert not IntercompanyRelationship.objects.filter(id=created["id"]).exists()
