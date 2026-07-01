"""Tests de ROBUSTEZ (finder de bordes) sobre endpoints de CONTABILIDAD (Ola E).

Patrón cazado: vistas que hacen `int(query_param)` / `int(data)` CRUDO sobre la
entrada del usuario ANTES (o fuera) del try/except del servicio. Con un valor no
numérico (`?fiscal_year=abc`, `?month_from=x`) el `int()` lanza `ValueError`, que
escapa el try (que solo captura `AccountingPlusError`/`ValueError` DENTRO de la
llamada al servicio, no la conversión previa) → 500 con envelope de error interno.

Gate honesto: 4xx, NUNCA 500. (El proyecto mapea ValidationError de DRF a 422; un
422 NO es bug. El bug es el 500 / traceback por entrada cruda.)

Si la superficie se endurece, estos asserts seguirán pasando (4xx) — son gates
permanentes, no xfail.
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


# ---------------------------------------------------------------------------
# Helpers (mismo estilo que test_robustez_hot_endpoints.py)
# ---------------------------------------------------------------------------
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


def _mk_budget(client: APIClient) -> int:
    """Crea un presupuesto vía API y devuelve su id (para tener un objeto real)."""
    r = client.post(
        "/api/accounting/budgets/",
        {"fiscal_year": 2026, "name": f"Presup {uuid.uuid4().hex[:6]}", "currency": "NIO"},
        format="json",
    )
    assert r.status_code == 201, r.content
    return int(r.data["id"])


# ===========================================================================
# 1. YearEndView.get — int(fiscal_year) CRUDO sobre query param
#    views_ola_e.py:293  ->  get_year_end_status(... fiscal_year=int(fy))
# ===========================================================================
@pytest.mark.django_db
def test_year_end_status_garbage_fiscal_year_no_500():
    """ALTO (500): GET /api/accounting/year-end/?fiscal_year=abc → int('abc')
    ValueError fuera de cualquier try → 500. Debe ser 4xx."""
    company_a, branch_a = _mk_company(f"A-ye-{uuid.uuid4().hex[:4]}")
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["accounting.year_end.close"])
    resp = client.get("/api/accounting/year-end/?fiscal_year=no-es-anio")
    assert resp.status_code != 500, f"500 con fiscal_year basura: {resp.content!r}"
    assert 400 <= resp.status_code < 500, resp.status_code


# ===========================================================================
# 2. BudgetsView.get — int(fiscal_year) CRUDO sobre query param
#    views_ola_e.py:173  ->  list_budgets(... fiscal_year=int(fy) if fy else None)
# ===========================================================================
@pytest.mark.django_db
def test_budgets_list_garbage_fiscal_year_no_500():
    """ALTO (500): GET /api/accounting/budgets/?fiscal_year=xx → int('xx')
    ValueError sin guard → 500. Debe ser 4xx."""
    company_a, branch_a = _mk_company(f"A-bl-{uuid.uuid4().hex[:4]}")
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["accounting.budget.read"])
    resp = client.get("/api/accounting/budgets/?fiscal_year=dos-mil")
    assert resp.status_code != 500, f"500 con fiscal_year basura: {resp.content!r}"
    assert 400 <= resp.status_code < 500, resp.status_code


# ===========================================================================
# 3. BudgetVsActualView.get — int(month_from/month_to/cost_center_id) CRUDO
#    views_ola_e.py:261-263 — los int() están FUERA del try (solo el servicio
#    está protegido) → cualquier param no numérico → 500.
# ===========================================================================
@pytest.mark.django_db
def test_budget_vs_actual_garbage_month_from_no_500():
    """ALTO (500): GET budgets/<id>/vs-actual/?month_from=abc → int('abc')
    ValueError fuera del try → 500. Debe ser 4xx."""
    company_a, branch_a = _mk_company(f"A-bva1-{uuid.uuid4().hex[:4]}")
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["accounting.budget.read", "accounting.budget.manage"])
    budget_id = _mk_budget(client)
    resp = client.get(f"/api/accounting/budgets/{budget_id}/vs-actual/?month_from=abc")
    assert resp.status_code != 500, f"500 con month_from basura: {resp.content!r}"
    assert 400 <= resp.status_code < 500, resp.status_code


@pytest.mark.django_db
def test_budget_vs_actual_garbage_cost_center_id_no_500():
    """ALTO (500): GET budgets/<id>/vs-actual/?cost_center_id=xyz → int('xyz')
    ValueError fuera del try → 500. Debe ser 4xx."""
    company_a, branch_a = _mk_company(f"A-bva2-{uuid.uuid4().hex[:4]}")
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["accounting.budget.read", "accounting.budget.manage"])
    budget_id = _mk_budget(client)
    resp = client.get(f"/api/accounting/budgets/{budget_id}/vs-actual/?cost_center_id=xyz")
    assert resp.status_code != 500, f"500 con cost_center_id basura: {resp.content!r}"
    assert 400 <= resp.status_code < 500, resp.status_code


@pytest.mark.django_db
def test_budget_vs_actual_garbage_month_to_no_500():
    """ALTO (500): GET budgets/<id>/vs-actual/?month_to=trece-y-medio → 500."""
    company_a, branch_a = _mk_company(f"A-bva3-{uuid.uuid4().hex[:4]}")
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["accounting.budget.read", "accounting.budget.manage"])
    budget_id = _mk_budget(client)
    resp = client.get(f"/api/accounting/budgets/{budget_id}/vs-actual/?month_to=trece-y-medio")
    assert resp.status_code != 500, f"500 con month_to basura: {resp.content!r}"
    assert 400 <= resp.status_code < 500, resp.status_code


# ===========================================================================
# 4. POSITIVO (control): el camino numérico válido NO revienta (404/200/422),
#    para distinguir "el endpoint funciona" de "el endpoint está roto para todo".
# ===========================================================================
@pytest.mark.django_db
def test_budget_vs_actual_valid_params_not_500():
    """CONTROL: con months numéricos válidos no debe ser 500 (200/404/422 ok)."""
    company_a, branch_a = _mk_company(f"A-bvaok-{uuid.uuid4().hex[:4]}")
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["accounting.budget.read", "accounting.budget.manage"])
    budget_id = _mk_budget(client)
    resp = client.get(f"/api/accounting/budgets/{budget_id}/vs-actual/?month_from=1&month_to=12")
    assert resp.status_code != 500, resp.content
