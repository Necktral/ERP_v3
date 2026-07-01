"""Robustez: query-params / body numéricos MALFORMADOS no deben tirar 500.

Patrón frágil detectado por lectura: varias vistas hacen `int(query_param)` o
`int(request.data.get(...))` SIN try/except. El exception handler global
(`config.drf_exception_handler.custom_exception_handler`) solo normaliza
`APIException` de DRF; un `ValueError`/`TypeError` crudo NO es APIException →
con DEBUG=False (producción) responde **500**. Modelo correcto ya existe en el
mismo repo (financiamiento/knowledge/hr capturan (TypeError, ValueError) → 400).

En el entorno de test, DEBUG_PROPAGATE_EXCEPTIONS=True hace que la excepción
cruda se PROPAGUE: el test fallará con ERROR (la misma causa-raíz que produce el
500 en prod). Por eso afirmamos status 4xx; si el endpoint está frágil, el test
revienta y delata el archivo:línea.
"""
from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

User = get_user_model()


def _mk_company(name: str) -> tuple[OrgUnit, OrgUnit]:
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H-{name}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name=f"C-{name}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, name=f"B-{name}", parent=company)
    return company, branch


def _client(*, company: OrgUnit, branch: OrgUnit | None, perm_codes: list[str]) -> APIClient:
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
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {access}"
    client.defaults["HTTP_X_AUTH_TRANSPORT"] = "header"
    client.defaults["HTTP_X_COMPANY_ID"] = str(company.id)
    if branch is not None:
        client.defaults["HTTP_X_BRANCH_ID"] = str(branch.id)
    return client


def _assert_4xx_not_500(resp):
    assert resp.status_code != 500, f"500 con entrada malformada: {resp.content!r}"
    assert 400 <= resp.status_code < 500, (resp.status_code, resp.content)


# ---------------------------------------------------------------------------
# INVENTARIO — lecturas calientes con int(query_param) sin proteger
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_inventory_stock_warehouse_id_garbage_no_500():
    """BUG: StockSummaryView (inventarios/views.py:305) hace int(warehouse_id)
    crudo. ?warehouse_id=abc → ValueError → 500 en prod."""
    c, b = _mk_company(f"stk-{uuid.uuid4().hex[:4]}")
    client = _client(company=c, branch=b, perm_codes=["inventory.balance.read"])
    resp = client.get("/api/inventory/stock/?warehouse_id=abc")
    _assert_4xx_not_500(resp)


@pytest.mark.django_db
def test_inventory_stock_item_id_garbage_no_500():
    """BUG: StockSummaryView (inventarios/views.py:309) int(item_id) crudo."""
    c, b = _mk_company(f"stk2-{uuid.uuid4().hex[:4]}")
    client = _client(company=c, branch=b, perm_codes=["inventory.balance.read"])
    resp = client.get("/api/inventory/stock/?item_id=NaN")
    _assert_4xx_not_500(resp)


@pytest.mark.django_db
def test_inventory_lotstock_warehouse_id_garbage_no_500():
    """BUG: LotStockView (inventarios/views.py:342) int(warehouse_id) crudo."""
    c, b = _mk_company(f"lot-{uuid.uuid4().hex[:4]}")
    client = _client(company=c, branch=b, perm_codes=["inventory.balance.read"])
    resp = client.get("/api/inventory/stock/lots/?item_id=1&warehouse_id=xyz")
    _assert_4xx_not_500(resp)


@pytest.mark.django_db
def test_inventory_lotstock_item_id_garbage_no_500():
    """BUG: LotStockView (inventarios/views.py:336) int(item_id) crudo."""
    c, b = _mk_company(f"lot2-{uuid.uuid4().hex[:4]}")
    client = _client(company=c, branch=b, perm_codes=["inventory.balance.read"])
    resp = client.get("/api/inventory/stock/lots/?item_id=abc")
    _assert_4xx_not_500(resp)


@pytest.mark.django_db
def test_inventory_kardex_item_id_garbage_no_500():
    """BUG: KardexView (inventarios/views.py:364) int(item_id) crudo."""
    c, b = _mk_company(f"kdx-{uuid.uuid4().hex[:4]}")
    client = _client(company=c, branch=b, perm_codes=["inventory.movement.read"])
    resp = client.get("/api/inventory/kardex/?item_id=abc")
    _assert_4xx_not_500(resp)


@pytest.mark.django_db
def test_inventory_kardex_warehouse_id_garbage_no_500():
    """BUG: KardexView (inventarios/views.py:370) int(warehouse_id) crudo."""
    c, b = _mk_company(f"kdx2-{uuid.uuid4().hex[:4]}")
    client = _client(company=c, branch=b, perm_codes=["inventory.movement.read"])
    resp = client.get("/api/inventory/kardex/?item_id=1&warehouse_id=xyz")
    _assert_4xx_not_500(resp)


@pytest.mark.django_db
def test_inventory_balance_ids_garbage_no_500():
    """BUG: BalanceView (inventarios/views.py:409) int(warehouse_id)/int(item_id)."""
    c, b = _mk_company(f"bal-{uuid.uuid4().hex[:4]}")
    client = _client(company=c, branch=b, perm_codes=["inventory.balance.read"])
    resp = client.get("/api/inventory/balances/?warehouse_id=foo&item_id=bar")
    _assert_4xx_not_500(resp)


@pytest.mark.django_db
def test_inventory_valuation_warehouse_id_garbage_no_500():
    """BUG: InventoryValuationView (views_counting.py:211) int(warehouse_id)."""
    c, b = _mk_company(f"val-{uuid.uuid4().hex[:4]}")
    client = _client(company=c, branch=b, perm_codes=["inventory.balance.read"])
    resp = client.get("/api/inventory/valuation/?warehouse_id=zzz")
    _assert_4xx_not_500(resp)


# ---------------------------------------------------------------------------
# FLEET — RunAlerts int(request.data) sin proteger
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_fleet_run_alerts_horizon_garbage_no_500():
    """BUG: RunAlertsView (fleet/views.py:298) int(request.data['horizon_days'])."""
    c, b = _mk_company(f"fleet-{uuid.uuid4().hex[:4]}")
    client = _client(company=c, branch=b, perm_codes=["fleet.maintenance.manage"])
    resp = client.post("/api/fleet/alerts/run/", {"horizon_days": "muchos"}, format="json")
    _assert_4xx_not_500(resp)


# ---------------------------------------------------------------------------
# CONTABILIDAD — BudgetVsActual int(month_from/to) sin proteger
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_accounting_budget_vs_actual_month_garbage_no_500():
    """BUG: BudgetVsActualView (accounting/views_ola_e.py:261) int(month_from)
    crudo dentro de try que solo atrapa AccountingPlusError → ValueError → 500."""
    c, b = _mk_company(f"bva-{uuid.uuid4().hex[:4]}")
    client = _client(company=c, branch=b, perm_codes=["accounting.budget.read"])
    resp = client.get("/api/accounting/budgets/1/vs-actual/?month_from=ene&month_to=dic")
    _assert_4xx_not_500(resp)
