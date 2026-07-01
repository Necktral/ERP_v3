"""Tests de ROBUSTEZ (finder de bordes) sobre FLOTA (fleet) y ESTACIÓN (fuel).

Mismo patrón cazado en la ola previa: `int(<entrada cruda>)` sin guard.

  - fleet.RunAlertsView.post (views.py:298): `int(request.data.get("horizon_days", 30))`
    sin try → con `horizon_days="abc"` levanta ValueError → 500. Es un POST que
    dispara alertas de mantenimiento (rama operativa).
  - fuel.FuelDispenseCreateView.get (views.py:143): `int(shift_id)` sobre el query
    param crudo → `?shift_id=abc` → 500.
  - fuel.FuelSaleCreateView.get (views.py:220): idéntico `int(shift_id)` → 500.

Gate honesto: 4xx, NUNCA 500.
"""
from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from rest_framework.test import APIClient

from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

User = get_user_model()


def _mk_company(name: str) -> tuple[OrgUnit, OrgUnit]:
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H-{name}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name=f"C-{name}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, name=f"B-{name}", parent=company)
    return company, branch


def _client(*, company: OrgUnit, branch: OrgUnit | None, perm_codes: list[str]) -> tuple[APIClient, AbstractBaseUser]:
    username = f"u_{uuid.uuid4().hex[:10]}"
    user = User.objects.create_user(username=username, email=f"{username}@t.com", password="pass12345")
    UserMembership.objects.create(user=user, org_unit=company, is_active=True)
    if branch is not None:
        UserMembership.objects.create(user=user, org_unit=branch, is_active=True)

    role = Role.objects.create(name=f"role_{uuid.uuid4().hex[:8]}", is_active=True)
    for code in perm_codes:
        perm, _ = Permission.objects.get_or_create(code=code, defaults={"description": code, "is_active": True})
        if not perm.is_active:
            perm.is_active = True
            perm.save(update_fields=["is_active"])
        RolePermission.objects.get_or_create(role=role, permission=perm)
    RoleAssignment.objects.create(user=user, role=role, org_unit=company, is_active=True)
    if branch is not None:
        RoleAssignment.objects.create(user=user, role=role, org_unit=branch, is_active=True)

    client = APIClient()
    login = client.post(
        "/api/auth/login/",
        {"username": username, "password": "pass12345"},
        format="json",
        HTTP_X_AUTH_TRANSPORT="header",
    )
    assert login.status_code == 200, login.content
    access = login.data.get("access") if isinstance(login.data, dict) else None
    if isinstance(access, str) and access:
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {access}"
    client.defaults["HTTP_X_AUTH_TRANSPORT"] = "header"
    client.defaults["HTTP_X_COMPANY_ID"] = str(company.id)
    if branch is not None:
        client.defaults["HTTP_X_BRANCH_ID"] = str(branch.id)
    return client, user


# ===========================================================================
# 1. FLEET — RunAlertsView.post: int(horizon_days) CRUDO sobre request.data
# ===========================================================================
@pytest.mark.django_db
def test_fleet_run_alerts_garbage_horizon_no_500():
    """ALTO (500): POST /api/fleet/alerts/run/ {"horizon_days": "abc"} →
    int('abc') ValueError sin try → 500. Debe ser 4xx."""
    company_a, branch_a = _mk_company(f"A-fla-{uuid.uuid4().hex[:4]}")
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["fleet.maintenance.manage"])
    resp = client.post("/api/fleet/alerts/run/", {"horizon_days": "abc"}, format="json")
    assert resp.status_code != 500, f"500 con horizon_days basura: {resp.content!r}"
    assert 400 <= resp.status_code < 500, resp.status_code


@pytest.mark.django_db
def test_fleet_run_alerts_horizon_list_no_500():
    """ALTO (500): horizon_days como lista → int([]) TypeError sin try → 500."""
    company_a, branch_a = _mk_company(f"A-fla2-{uuid.uuid4().hex[:4]}")
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["fleet.maintenance.manage"])
    resp = client.post("/api/fleet/alerts/run/", {"horizon_days": []}, format="json")
    assert resp.status_code != 500, f"500 con horizon_days lista: {resp.content!r}"
    assert 400 <= resp.status_code < 500, resp.status_code


@pytest.mark.django_db
def test_fleet_run_alerts_valid_horizon_not_500():
    """CONTROL: horizon_days numérico válido no debe ser 500 (200/4xx ok)."""
    company_a, branch_a = _mk_company(f"A-flaok-{uuid.uuid4().hex[:4]}")
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["fleet.maintenance.manage"])
    resp = client.post("/api/fleet/alerts/run/", {"horizon_days": 30}, format="json")
    assert resp.status_code != 500, resp.content


# ===========================================================================
# 2. FUEL — FuelDispenseCreateView.get: int(shift_id) CRUDO sobre query param
# ===========================================================================
@pytest.mark.django_db
def test_fuel_dispenses_list_garbage_shift_id_no_500():
    """ALTO (500): GET /api/fuel/dispenses/?shift_id=abc → int('abc') → 500.
    Debe ser 4xx (o ignorar el filtro y devolver 200, pero nunca 500)."""
    company_a, branch_a = _mk_company(f"A-fd-{uuid.uuid4().hex[:4]}")
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["fuel.dispense.read"])
    resp = client.get("/api/fuel/dispenses/?shift_id=abc")
    assert resp.status_code != 500, f"500 con shift_id basura: {resp.content!r}"
    assert resp.status_code in (200, 400, 422), resp.status_code


# ===========================================================================
# 3. FUEL — FuelSaleCreateView.get: int(shift_id) CRUDO sobre query param
# ===========================================================================
@pytest.mark.django_db
def test_fuel_sales_list_garbage_shift_id_no_500():
    """ALTO (500): GET /api/fuel/sales/?shift_id=abc → int('abc') → 500."""
    company_a, branch_a = _mk_company(f"A-fs-{uuid.uuid4().hex[:4]}")
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["fuel.sale.read"])
    resp = client.get("/api/fuel/sales/?shift_id=abc")
    assert resp.status_code != 500, f"500 con shift_id basura: {resp.content!r}"
    assert resp.status_code in (200, 400, 422), resp.status_code


@pytest.mark.django_db
def test_fuel_dispenses_list_valid_shift_id_not_500():
    """CONTROL: shift_id numérico (aunque inexistente) no debe ser 500."""
    company_a, branch_a = _mk_company(f"A-fdok-{uuid.uuid4().hex[:4]}")
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["fuel.dispense.read"])
    resp = client.get("/api/fuel/dispenses/?shift_id=999999")
    assert resp.status_code != 500, resp.content
