"""Tests del asistente de DATOS (router + skills read-only acotadas por empresa y permiso).

Hermético: en `config.settings.test` la IA está apagada, así que el router usa SOLO el
fast-path determinista (palabras clave) y el fallback a documentación — sin llamar al LLM.
"""
from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.modulos.hr.models import Employee
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.knowledge.ingest import ingest_corpus
from apps.modulos.org.models import CompanyModule
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
    r = client.get("/api/knowledge/assistant/", {"q": q})
    assert r.status_code == 200, r.data
    return r.data


def _enable_modules(company, *codes):
    """Habilita módulos de la empresa (override ON) para que el resumen los muestre."""
    for code in codes:
        CompanyModule.objects.update_or_create(
            company=company, module_code=code, defaults={"is_enabled": True}
        )


@pytest.mark.django_db
def test_pregunta_de_datos_cuenta_empleados():
    client, _ = _mk(["hr.employee.read"], employees=3)
    data = _ask(client, "¿cuántos empleados hay?")
    assert data["kind"] == "data"
    assert data["skill"] == "rh.empleados_total"
    assert "3" in data["answer"]
    assert data["data"]["total"] == 3


@pytest.mark.django_db
def test_skill_acotada_a_la_empresa_del_request():
    # Empresa A con 2 empleados; otra empresa con 5 NO debe contarse.
    client, company_a = _mk(["hr.employee.read"], employees=2)
    otra = OrgUnit.objects.create(
        unit_type=UT.COMPANY, name="OtraCo", parent=OrgUnit.objects.create(unit_type=UT.HOLDING, name="H2")
    )
    for i in range(5):
        Employee.objects.create(company=otra, first_name=f"X{i}")
    data = _ask(client, "cuántos empleados hay")
    assert data["kind"] == "data"
    assert data["data"]["total"] == 2  # solo los de la empresa del request


@pytest.mark.django_db
def test_seguridad_sin_permiso_no_devuelve_datos():
    # Usuario SIN hr.employee.read: la skill no está disponible → NO se ejecuta (cae a docs).
    client, _ = _mk([], employees=3)  # solo knowledge.docs.read
    data = _ask(client, "cuántos empleados hay")
    assert data["kind"] != "data"
    assert data.get("skill") is None


@pytest.mark.django_db
def test_pregunta_de_como_va_a_documentacion(tmp_path):
    # Una pregunta de "cómo" sin skill de datos → kind=docs (búsqueda en el manual).
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "caja.md").write_text(
        "# Cierre de caja\n\nEl cierre de caja diario requiere conteo y aprobación.\n",
        encoding="utf-8",
    )
    ingest_corpus(root=tmp_path)
    client, _ = _mk(["hr.employee.read"])
    data = _ask(client, "cómo se hace el cierre de caja")
    assert data["kind"] == "docs"
    assert data["results"]  # el retrieval determinista encontró el fragmento


@pytest.mark.django_db
def test_ventas_de_hoy_sin_facturas_es_cero():
    client, _ = _mk(["billing.invoice.read"])
    data = _ask(client, "cuánto vendí hoy")
    assert data["kind"] == "data"
    assert data["skill"] == "ventas.hoy"
    assert data["data"]["total"] == "0.00"


@pytest.mark.django_db
def test_parties_cuenta_clientes():
    from apps.modulos.parties.models import Party, PartyRole

    client, company = _mk(["parties.party.read"])
    p = Party.objects.create(company=company, party_type=Party.PartyType.NATURAL, display_name="Cliente Uno")
    PartyRole.objects.create(party=p, role=PartyRole.Role.CUSTOMER, is_active=True)
    data = _ask(client, "cuántos clientes hay")
    assert data["kind"] == "data"
    assert data["skill"] == "parties.clientes"
    assert data["data"]["total"] == 1


@pytest.mark.django_db
def test_pos_corte_sin_tickets_es_cero():
    client, _ = _mk(["sales.pos.report"])
    data = _ask(client, "cómo va el corte de caja de hoy")
    assert data["kind"] == "data"
    assert data["skill"] == "pos.corte_hoy"
    assert data["data"]["tickets"] == 0


# --- Ola 1: tesorería y libros (payments / accounting / intercompany) ---


@pytest.mark.django_db
def test_payments_arqueo_caja_sin_sesiones():
    client, _ = _mk(["payments.cash_session.read"])
    data = _ask(client, "cómo va el arqueo de caja de hoy")
    assert data["kind"] == "data"
    assert data["skill"] == "payments.caja_hoy"
    assert data["data"]["abiertas"] == 0


@pytest.mark.django_db
def test_accounting_periodo_abierto():
    from apps.kernels.accounting.models import FiscalPeriod

    client, company = _mk(["accounting.period.read"])
    FiscalPeriod.objects.create(company=company, year=2026, month=6, status=FiscalPeriod.Status.OPEN)
    data = _ask(client, "cuál es el período fiscal abierto")
    assert data["kind"] == "data"
    assert data["skill"] == "accounting.periodo_abierto"
    assert data["data"]["abiertos"] == [{"anio": 2026, "mes": 6}]


@pytest.mark.django_db
def test_intercompany_sin_permiso_no_devuelve_datos():
    # Sin accounting.intercompany.read la skill no está disponible → cae a docs.
    client, _ = _mk(["payments.intent.read"])
    data = _ask(client, "hay cruces entre empresas pendientes")
    assert data["kind"] != "data"
    assert data.get("skill") is None


# --- Ola 2: vertical de café (financiamiento / beneficio) ---


@pytest.mark.django_db
def test_financiamiento_prestamos_activos_sin_datos():
    client, _ = _mk(["financing.loan.read"])
    data = _ask(client, "cuántos préstamos activos hay")
    assert data["kind"] == "data"
    assert data["skill"] == "financiamiento.prestamos_activos"
    assert data["data"] == {"activos": 0, "saldo_nio": "0.00", "saldo_usd": "0.00"}


@pytest.mark.django_db
def test_beneficio_ordenes_en_proceso_es_cero():
    client, _ = _mk(["beneficio.order.read"])
    data = _ask(client, "cuántas órdenes de beneficio hay en proceso")
    assert data["kind"] == "data"
    assert data["skill"] == "beneficio.ordenes_proceso"
    assert data["data"]["en_proceso"] == 0


# --- Ola 3: campo y flota (finca / fleet) ---


@pytest.mark.django_db
def test_finca_ordenes_trabajo_cuenta_por_estado():
    from apps.modulos.finca.models import Labor, Plot, WorkOrder

    client, company = _mk(["finca.work.read"])
    UT = OrgUnit.UnitType
    finca = OrgUnit.objects.create(unit_type=UT.BRANCH, name="Finca La Esperanza", parent=company)
    plot = Plot.objects.create(finca=finca, code="L1", area_manzanas="10.00")
    labor = Labor.objects.create(company=company, code="POD", name="Poda")
    WorkOrder.objects.create(finca=finca, plot=plot, labor=labor, status=WorkOrder.Status.PLANNED, jornales="3.00")
    WorkOrder.objects.create(finca=finca, plot=plot, labor=labor, status=WorkOrder.Status.DONE, jornales="2.00")
    data = _ask(client, "cuántas órdenes de trabajo hay")
    assert data["kind"] == "data"
    assert data["skill"] == "finca.ordenes_trabajo"
    assert data["data"]["total"] == 2
    assert data["data"]["planificadas"] == 1
    assert data["data"]["hechas"] == 1
    assert data["data"]["jornales"] == "5.00"


@pytest.mark.django_db
def test_fleet_combustible_periodo_sin_datos():
    client, _ = _mk(["fleet.cost.read"])
    data = _ask(client, "cuánto combustible consumió la flota este mes")
    assert data["kind"] == "data"
    assert data["skill"] == "fleet.combustible_periodo"
    assert data["data"]["litros"] == "0.00"
    assert data["data"]["costo"] == "0.00"


# --- Resumen del día (panel) ---


@pytest.mark.django_db
def test_resumen_dia_via_asistente_filtra_por_permiso():
    # Solo ventas + CxC permitidos Y sus módulos habilitados: el panel incluye ESAS
    # secciones y no las demás (doble gateo: permiso + módulo).
    client, company = _mk(["billing.invoice.read", "portfolio.receivable.read"])
    _enable_modules(company, "billing", "portfolio")
    data = _ask(client, "dame un resumen del día")
    assert data["kind"] == "data"
    assert data["skill"] == "sistema.resumen_dia"
    keys = [s["skill"] for s in data["data"]["secciones"]]
    assert keys == ["ventas.hoy", "cartera.cxc"]


@pytest.mark.django_db
def test_summary_endpoint_solo_secciones_permitidas():
    client, company = _mk(["billing.invoice.read"])
    _enable_modules(company, "billing")
    r = client.get("/api/knowledge/summary/")
    assert r.status_code == 200, r.data
    assert r.data["kind"] == "data"
    keys = [s["skill"] for s in r.data["data"]["secciones"]]
    assert keys == ["ventas.hoy"]  # sin más permisos/módulos, solo ventas


@pytest.mark.django_db
def test_summary_oculta_seccion_si_el_modulo_esta_deshabilitado():
    # Con el permiso pero el MÓDULO apagado, la sección NO aparece; al habilitarlo, sí.
    client, company = _mk(["portfolio.receivable.read"])
    CompanyModule.objects.create(company=company, module_code="portfolio", is_enabled=False)
    r = client.get("/api/knowledge/summary/")
    assert r.status_code == 200, r.data
    keys = [s["skill"] for s in r.data["data"]["secciones"]]
    assert "cartera.cxc" not in keys
    CompanyModule.objects.filter(company=company, module_code="portfolio").update(is_enabled=True)
    r2 = client.get("/api/knowledge/summary/")
    keys2 = [s["skill"] for s in r2.data["data"]["secciones"]]
    assert "cartera.cxc" in keys2


@pytest.mark.django_db
def test_summary_sin_permisos_de_negocio_es_vacio():
    client, _ = _mk([])  # solo knowledge.docs.read
    r = client.get("/api/knowledge/summary/")
    assert r.status_code == 200, r.data
    assert r.data["data"]["secciones"] == []
    assert "permiso" in r.data["answer"].lower()


# --- Supervisión: bitácora, alertas, errores del sistema, controles ---


@pytest.mark.django_db
def test_supervision_bitacora_rutea_con_permiso():
    client, _ = _mk(["audit.read"])
    data = _ask(client, "detállame la bitácora")
    assert data["kind"] == "data"
    assert data["skill"] == "auditoria.bitacora"


@pytest.mark.django_db
def test_supervision_bitacora_sin_permiso_no_es_data():
    client, _ = _mk([])  # solo knowledge.docs.read
    data = _ask(client, "detállame la bitácora")
    assert data["kind"] != "data"
    assert data.get("skill") is None


@pytest.mark.django_db
def test_supervision_alertas_pendientes_cuenta_abiertas():
    from apps.modulos.alertas.models import Alert, AlertSeverity, AlertStatus

    client, company = _mk(["alerts.read"])
    Alert.objects.create(
        company=company, alert_type="LOW_STOCK", severity=AlertSeverity.CRITICAL,
        title="Stock bajo", status=AlertStatus.OPEN,
    )
    data = _ask(client, "qué necesita atención hoy")
    assert data["kind"] == "data"
    assert data["skill"] == "alertas.pendientes"
    assert data["data"]["abiertas"] == 1
    assert data["data"]["criticas"] == 1


@pytest.mark.django_db
def test_supervision_controles_hallazgos_rutea():
    client, _ = _mk(["controls.findings.read"])
    data = _ask(client, "hay violaciones de segregación de funciones")
    assert data["kind"] == "data"
    assert data["skill"] == "controles.hallazgos"
