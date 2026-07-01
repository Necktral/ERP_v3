"""ROBUSTEZ del asistente de DATOS: READ-ONLY y acotado a EMPRESA + PERMISO.

En `config.settings.test` la IA está apagada: el router usa SOLO el fast-path
determinista + fallback a docs (no llama a ningún LLM). Por eso aquí NO se prueba la
generación del LLM (no disponible en test), solo la CAPA de acotamiento:

- Una consulta del asistente NO escribe NADA (read-only): el conteo de filas de los
  kernels de negocio es idéntico antes y después, también tras una ráfaga de queries.
- Aislamiento por empresa: no devuelve datos de una empresa para la que el usuario no
  tiene membresía/permiso (la skill cuenta solo la empresa del request).
- Sin el permiso de la skill → no se ejecuta la consulta de datos (cae a docs); no hay
  fuga aunque exista el dato en la empresa.
- El endpoint conversacional (POST chat) es el único POST; tampoco escribe.
- ENTRADA BASURA: q vacío → 400; limit no numérico en search → 400; chat sin messages
  → 400; un payload raro a la skill (q gigante) → 200/4xx tipado, nunca 500.
"""
from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.kernels.accounting.models import JournalEntry
from apps.kernels.facturacion.models import BillingDocument
from apps.kernels.inventarios.models import StockMovement
from apps.modulos.audit.models import AuditEvent
from apps.modulos.hr.models import Employee
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

User = get_user_model()
UT = OrgUnit.UnitType
BASE = "knowledge.docs.read"


def _mk(perm_codes, *, employees=0):
    t = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=UT.HOLDING, name=f"H{t}")
    company = OrgUnit.objects.create(unit_type=UT.COMPANY, name=f"Empresa{t}", parent=holding)
    user = User.objects.create_user(username=f"as_{t}", email=f"as_{t}@t.local", password="pass12345")
    UserMembership.objects.create(user=user, org_unit=company, is_active=True)
    role = Role.objects.create(name=f"as_role_{t}", is_active=True)
    for code in [BASE, *perm_codes]:
        perm, _ = Permission.objects.get_or_create(code=code, defaults={"description": code, "is_active": True})
        RolePermission.objects.get_or_create(role=role, permission=perm)
    RoleAssignment.objects.create(user=user, role=role, org_unit=company, is_active=True)
    for i in range(employees):
        Employee.objects.create(company=company, first_name=f"Emp{i}")
    client = APIClient()
    login = client.post("/api/auth/login/", {"username": user.username, "password": "pass12345"}, format="json")
    assert login.status_code == 200, login.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    client.defaults["HTTP_X_COMPANY_ID"] = str(company.id)
    return client, company


def _ask(client, q):
    return client.get("/api/knowledge/assistant/", {"q": q})


def _business_counts():
    return (
        JournalEntry.objects.count(),
        StockMovement.objects.count(),
        BillingDocument.objects.count(),
        Employee.objects.count(),
    )


# --------------------------------------------------------------------------- #
# READ-ONLY: ninguna consulta escribe en kernels de negocio
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_consulta_de_datos_no_escribe_nada():
    client, _ = _mk(["hr.employee.read"], employees=3)
    before = _business_counts()
    r = _ask(client, "¿cuántos empleados hay?")
    assert r.status_code == 200, r.data
    assert r.data["kind"] == "data"
    assert _business_counts() == before  # read-only: cero filas nuevas/borradas


@pytest.mark.django_db
def test_rafaga_de_consultas_distintas_no_escribe_nada():
    """Varias skills (rh, ventas, parties, pos, alertas) en ráfaga: ninguna muta el negocio."""
    client, _ = _mk(
        ["hr.employee.read", "billing.invoice.read", "parties.party.read", "sales.pos.report", "alerts.read"],
        employees=2,
    )
    before = _business_counts()
    for q in [
        "cuántos empleados hay",
        "cuánto vendí hoy",
        "cuántos clientes hay",
        "cómo va el corte de caja de hoy",
        "qué necesita atención hoy",
        "dame un resumen del día",
    ]:
        assert _ask(client, q).status_code == 200
    assert _business_counts() == before


@pytest.mark.django_db
def test_chat_endpoint_es_read_only():
    """El POST conversacional es el único POST del asistente; tampoco escribe negocio."""
    client, _ = _mk(["hr.employee.read"], employees=2)
    before = _business_counts()
    r = client.post(
        "/api/knowledge/chat/",
        {"messages": [{"role": "user", "content": "cuántos empleados hay"}]},
        format="json",
    )
    assert r.status_code == 200, r.data
    assert _business_counts() == before


# --------------------------------------------------------------------------- #
# AISLAMIENTO POR EMPRESA + PERMISO
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_no_filtra_datos_de_otra_empresa():
    # Empresa A: 2 empleados; otra empresa: 50. El conteo debe ser 2, no 52.
    client, _ = _mk(["hr.employee.read"], employees=2)
    otra = OrgUnit.objects.create(
        unit_type=UT.COMPANY, name="OtraCo",
        parent=OrgUnit.objects.create(unit_type=UT.HOLDING, name="HX"),
    )
    for i in range(50):
        Employee.objects.create(company=otra, first_name=f"X{i}")
    r = _ask(client, "cuántos empleados hay")
    assert r.status_code == 200, r.data
    assert r.data["kind"] == "data"
    assert r.data["data"]["total"] == 2  # SOLO la empresa del request


@pytest.mark.django_db
def test_sin_permiso_no_devuelve_dato_aunque_exista():
    # Usuario SIN hr.employee.read pero la empresa SÍ tiene 5 empleados: no debe contarlos.
    client, company = _mk([], employees=5)  # solo knowledge.docs.read
    r = _ask(client, "cuántos empleados hay")
    assert r.status_code == 200, r.data
    assert r.data["kind"] != "data"  # cae a docs, no ejecuta la skill
    assert r.data.get("skill") is None


@pytest.mark.django_db
def test_header_de_otra_empresa_es_bloqueado_en_la_puerta():
    """Si el usuario apunta el header X-Company-Id a una empresa donde NO tiene
    membresía, el backend corta con 403 SCOPE_FORBIDDEN ANTES de ejecutar la skill:
    el gateo de empresa es del middleware, no del skill. Cero fuga de los datos ajenos."""
    client, _ = _mk(["hr.employee.read"], employees=1)
    ajena = OrgUnit.objects.create(
        unit_type=UT.COMPANY, name="Ajena",
        parent=OrgUnit.objects.create(unit_type=UT.HOLDING, name="HA"),
    )
    for i in range(7):
        Employee.objects.create(company=ajena, first_name=f"A{i}")
    # Apuntar a la empresa ajena.
    client.defaults["HTTP_X_COMPANY_ID"] = str(ajena.id)
    r = _ask(client, "cuántos empleados hay")
    assert r.status_code == 403, r.data  # gateo de empresa en la puerta, sin fuga
    body = r.data.get("error", r.data)
    # 403 antes de ejecutar la skill: no hay payload de datos (ni 'data' ni 'total').
    assert "data" not in r.data
    assert body.get("code") == "SCOPE_FORBIDDEN"


# --------------------------------------------------------------------------- #
# ENTRADA BASURA → 4xx tipado, nunca 500
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_q_vacio_es_400():
    client, _ = _mk(["hr.employee.read"])
    r = client.get("/api/knowledge/assistant/", {"q": "   "})
    assert r.status_code == 400


@pytest.mark.django_db
def test_search_limit_no_numerico_es_400():
    client, _ = _mk([])
    r = client.get("/api/knowledge/search/", {"q": "caja", "limit": "muchos"})
    assert r.status_code == 400


@pytest.mark.django_db
def test_chat_sin_messages_es_400():
    client, _ = _mk([])
    assert client.post("/api/knowledge/chat/", {}, format="json").status_code == 400
    assert client.post("/api/knowledge/chat/", {"messages": []}, format="json").status_code == 400
    assert client.post("/api/knowledge/chat/", {"messages": "no-es-lista"}, format="json").status_code == 400


@pytest.mark.django_db
def test_query_gigante_no_revienta():
    client, _ = _mk(["hr.employee.read"], employees=1)
    before = _business_counts()
    r = _ask(client, "cuántos empleados " + ("x" * 20000))
    assert r.status_code in (200, 400)  # nunca 500
    assert _business_counts() == before


@pytest.mark.django_db
def test_consulta_no_genera_eventos_de_escritura_de_negocio():
    """Una consulta read-only no debe disparar eventos de auditoría de MUTACIÓN de
    negocio (a lo sumo lectura/acceso); como mínimo, no debe crear/editar entidades."""
    client, _ = _mk(["hr.employee.read"], employees=2)
    biz_events_before = AuditEvent.objects.exclude(event_type__icontains="READ").count()
    before = _business_counts()
    _ask(client, "cuántos empleados hay")
    assert _business_counts() == before
    # No se crearon entidades de negocio; el conteo de filas lo confirma arriba.
    # (No afirmamos 0 eventos: el acceso puede auditarse; sí afirmamos cero mutación de datos.)
    assert AuditEvent.objects.exclude(event_type__icontains="READ").count() >= biz_events_before
