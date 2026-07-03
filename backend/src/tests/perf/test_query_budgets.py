"""
Presupuestos de queries (ratchet) — red de regresión N+1. Nace en la oleada 0.

Convención: cada oleada añade aquí los budgets de sus rutas calientes.
Un budget NUNCA se borra; solo se baja. Si un cambio legítimo necesita
subir un número, se documenta en el propio test el porqué (y se considera
si el cambio en verdad debe costar más queries).

También viven aquí los tests del memo RBAC por-request (oleada 0): la 2ª
evaluación de permisos del mismo request no debe tocar la BD.
"""
from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.modulos.common.permissions import rbac_permission
from apps.modulos.iam.models import OrgUnit
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission
from apps.modulos.rbac.selectors import get_effective_permissions_for_scope_cached
from tests.helpers.operational_auth import create_operational_api_actor

User = get_user_model()

# --- Budgets (ratchet: solo se bajan) --------------------------------------
# GET /api/inventory/items/ autenticado con RBAC: auth JWT + contexto
# company/branch + permisos efectivos (memoizados) + listado.
# Medido en O0: 10 queries; presupuesto = medido + 2 de margen.
BUDGET_INVENTORY_ITEMS_LIST = 12


def _mk_org():
    s = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H_{s}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name=f"C_{s}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, name=f"B_{s}", parent=company)
    return holding, company, branch


def _mk_user_with_perm(company, code: str):
    username = f"perf_{uuid.uuid4().hex[:8]}"
    user = User.objects.create_user(username=username, email=f"{username}@test.local", password="pass12345")
    role = Role.objects.create(name=f"r_{uuid.uuid4().hex[:8]}", is_active=True)
    perm = Permission.objects.create(code=code, is_active=True)
    RolePermission.objects.create(role=role, permission=perm)
    RoleAssignment.objects.create(user=user, role=role, org_unit=company, is_active=True)
    return user


# ---------------------------------------------------------------------------
# Memo RBAC por-request (oleada 0)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_rbac_memo_segunda_evaluacion_cero_queries(django_assert_num_queries):
    _, company, branch = _mk_org()
    code = f"perf.read_{uuid.uuid4().hex[:6]}"
    user = _mk_user_with_perm(company, code)

    raw = APIRequestFactory().get("/")
    first = get_effective_permissions_for_scope_cached(
        request=raw, user=user, company=company, branch=branch
    )
    assert code in first

    with django_assert_num_queries(0):
        second = get_effective_permissions_for_scope_cached(
            request=raw, user=user, company=company, branch=branch
        )
    assert second == first


@pytest.mark.django_db
def test_rbac_memo_sin_bleed_entre_requests():
    _, company_a, _ = _mk_org()
    _, company_b, _ = _mk_org()
    code_a = f"perf.a_{uuid.uuid4().hex[:6]}"
    code_b = f"perf.b_{uuid.uuid4().hex[:6]}"
    user_a = _mk_user_with_perm(company_a, code_a)
    user_b = _mk_user_with_perm(company_b, code_b)

    factory = APIRequestFactory()
    raw_a = factory.get("/")
    perms_a = get_effective_permissions_for_scope_cached(request=raw_a, user=user_a, company=company_a)

    # Un request nuevo NO hereda el memo: su primera evaluación consulta la BD.
    raw_b = factory.get("/")
    with CaptureQueriesContext(connection) as ctx:
        perms_b = get_effective_permissions_for_scope_cached(request=raw_b, user=user_b, company=company_b)
    assert len(ctx.captured_queries) > 0
    assert perms_a == {code_a}
    assert perms_b == {code_b}

    # Mismo request, scope distinto → key distinta en el memo (no colisiona).
    perms_cross = get_effective_permissions_for_scope_cached(request=raw_a, user=user_a, company=company_b)
    assert perms_cross == set()


@pytest.mark.django_db
def test_rbac_override_no_pasa_por_memo():
    _, company, branch = _mk_org()
    user = _mk_user_with_perm(company, f"perf.x_{uuid.uuid4().hex[:6]}")

    raw = APIRequestFactory().get("/")
    request = Request(raw)
    request.user = user
    request.company = company
    request.branch = branch
    request.rbac_effective_permissions_override = ["demo.override"]

    permission = rbac_permission("demo.override")()
    assert permission.has_permission(request, view=None) is True
    # El camino override no crea ni contamina el memo por-request.
    assert not hasattr(raw, "_rbac_perms_memo")


# ---------------------------------------------------------------------------
# Budgets de endpoints (ratchet)
# ---------------------------------------------------------------------------

def _mk_request(company, branch, user):
    from types import SimpleNamespace

    return SimpleNamespace(
        company=company, branch=branch, user=user, META={}, headers={},
        path="/perf/", method="POST", request_id=f"req-{uuid.uuid4().hex[:8]}",
    )


@pytest.mark.query_budget
@pytest.mark.django_db
def test_budget_create_draft_queries_constantes_en_lineas():
    """Oleada 1: crear un documento de venta cuesta las mismas queries con 2
    líneas que con 40 (bulk_create — sin INSERT por línea)."""
    from apps.kernels.facturacion.services import create_draft

    _, company, branch = _mk_org()
    user = _mk_user_with_perm(company, f"perf.bill_{uuid.uuid4().hex[:6]}")
    request = _mk_request(company, branch, user)

    def crear(n_lineas: int) -> int:
        lines = [
            {"description": f"L{i}", "quantity": "1", "unit_price": "10.00", "tax_rate": "0.15"}
            for i in range(n_lineas)
        ]
        with CaptureQueriesContext(connection) as ctx:
            create_draft(
                request=request, actor=user, doc_type="INVOICE", series="A",
                currency="NIO", customer_name="Perf", customer_ref="P-1",
                is_fiscal=False, lines=lines, idempotency_key=f"perf-{uuid.uuid4().hex}",
            )
        return len(ctx.captured_queries)

    crear(1)  # warmup: paga las queries one-time (content types, caches de sesión)
    q_chico, q_grande = crear(2), crear(40)
    assert q_grande == q_chico, (
        f"create_draft escala en queries con las líneas: {q_chico} con 2 vs {q_grande} con 40"
    )


@pytest.mark.query_budget
@pytest.mark.django_db
def test_budget_create_remision_queries_constantes_en_lineas():
    """Oleada 1: crear una remisión cuesta las mismas queries con 2 líneas que
    con 40 (carga de ítems en 1 query + bulk_create de líneas)."""
    from apps.kernels.inventarios.models import InventoryItem, RemisionOriginType, Warehouse
    from apps.kernels.inventarios.remisiones import create_remision

    _, company, branch = _mk_org()
    user = _mk_user_with_perm(company, f"perf.rem_{uuid.uuid4().hex[:6]}")
    request = _mk_request(company, branch, user)
    wh = Warehouse.objects.create(company=company, branch=branch, name="WH", code=f"W{uuid.uuid4().hex[:4]}")
    items = [
        InventoryItem.objects.create(company=company, sku=f"S-{uuid.uuid4().hex[:6]}", name=f"I{i}")
        for i in range(40)
    ]

    def crear(n_lineas: int) -> int:
        lines = [
            {"item_id": items[i].id, "qty_dispatched": "5", "unit_cost": "1.25"}
            for i in range(n_lineas)
        ]
        with CaptureQueriesContext(connection) as ctx:
            create_remision(
                request=request, actor=user, origin_type=RemisionOriginType.PURCHASE,
                dest_warehouse_id=wh.id, source_module="BILLING", source_type="INVOICE",
                source_id="perf", lines=lines,
            )
        return len(ctx.captured_queries)

    crear(1)  # warmup: paga las queries one-time (content types, caches de sesión)
    q_chico, q_grande = crear(2), crear(40)
    assert q_grande == q_chico, (
        f"create_remision escala en queries con las líneas: {q_chico} con 2 vs {q_grande} con 40"
    )


@pytest.mark.query_budget
@pytest.mark.django_db
def test_budget_listado_inventario_items(settings):
    _, company, branch = _mk_org()
    client, _user = create_operational_api_actor(
        company=company, branch=branch, perm_codes=["inventory.item.read"]
    )

    with CaptureQueriesContext(connection) as ctx:
        resp = client.get("/api/inventory/items/")
    assert resp.status_code == 200

    total = len(ctx.captured_queries)
    print(f"[query_budget] GET /api/inventory/items/ -> {total} queries (presupuesto {BUDGET_INVENTORY_ITEMS_LIST})")
    assert total <= BUDGET_INVENTORY_ITEMS_LIST, (
        f"GET /api/inventory/items/ hizo {total} queries; presupuesto "
        f"{BUDGET_INVENTORY_ITEMS_LIST}. Si el aumento es legítimo, documenta el "
        "porqué aquí y considera si de verdad debe costar más."
    )
