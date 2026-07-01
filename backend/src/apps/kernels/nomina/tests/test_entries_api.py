"""API de entradas de planilla — contrato de salario para jornaleros (DAILY).

El caso real de la hacienda: 95% del personal gana JORNAL DIARIO. El cliente
manda el jornal tal cual (daily_rate_nio) y el kernel lo lleva a la base
mensual (mes de 30 días). Bug detectado en prueba E2E: mandar el jornal como
base_salary_nio lo dividía entre 30 (C$250 → C$8.33/día).
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.kernels.nomina.models import (
    EmployeeInssEnrollment,
    InssRegime,
    PayrollPeriod,
    PayrollSheet,
    PeriodType,
)
from apps.kernels.nomina.services import create_default_nicaragua_config
from apps.modulos.hr.models import Employee, EmploymentAssignment, JobPosition
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

User = get_user_model()

BASE = "/api/nomina"

ENTRY_PERMS = ["nomina.entry.create", "nomina.entry.read"]


def _scope():
    t = uuid.uuid4().hex[:8]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H{t}", code=f"H-{t}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, parent=holding, name=f"C{t}", code=f"C-{t}")
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, parent=company, name=f"B{t}", code=f"B-{t}")
    return company, branch


def _client(*, company, branch, perms):
    u = User.objects.create_user(username=f"u_{uuid.uuid4().hex[:8]}", email=f"e_{uuid.uuid4().hex[:8]}@t.com", password="x")
    UserMembership.objects.create(user=u, org_unit=company, is_active=True)
    UserMembership.objects.create(user=u, org_unit=branch, is_active=True)
    role = Role.objects.create(name=f"r_{uuid.uuid4().hex[:8]}", is_active=True)
    for p in perms:
        perm, _ = Permission.objects.get_or_create(code=p, defaults={"description": p, "is_active": True})
        RolePermission.objects.get_or_create(role=role, permission=perm)
    RoleAssignment.objects.create(user=u, role=role, org_unit=company, is_active=True)
    RoleAssignment.objects.create(user=u, role=role, org_unit=branch, is_active=True)
    c = APIClient()
    login = c.post("/api/auth/login/", {"username": u.username, "password": "x"}, format="json")
    assert login.status_code == 200, login.data
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    c.defaults["HTTP_X_COMPANY_ID"] = str(company.id)
    c.defaults["HTTP_X_BRANCH_ID"] = str(branch.id)
    c.user = u
    return c


def _sheet(company, actor):
    req = SimpleNamespace(user=actor, META={}, company=company, branch=None, _request=None,
                          ctx=None, request_id="", path="", method="POST")
    create_default_nicaragua_config(request=req, actor=actor, company=company, fiscal_year=2026)
    period = PayrollPeriod.objects.create(
        company=company, year=2026, month=6, period_type=PeriodType.FIRST_HALF,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 15), working_days=15,
    )
    sheet = PayrollSheet.objects.create(period=period, sheet_name="Planilla general", has_inss=True)
    return period, sheet


@pytest.mark.django_db
def test_jornalero_daily_rate_se_respeta_tal_cual():
    """Jornal C$250 × 12 días = C$3,000 de salario del período (no C$250/30)."""
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=ENTRY_PERMS)
    period, sheet = _sheet(company, client.user)

    resp = client.post(
        f"{BASE}/periods/{period.id}/sheets/{sheet.id}/entries/",
        {
            "full_name": "Juan Jornalero",
            "has_inss": True,
            "salary_type": "DAILY",
            "payment_frequency": "FIRST_HALF",
            "daily_rate_nio": "250.00",
            "days_in_period": 15,
            "days_worked": "12.00",
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert Decimal(resp.data["daily_rate_nio"]) == Decimal("250.000000")
    assert Decimal(resp.data["base_salary_nio"]) == Decimal("7500.00")
    assert Decimal(resp.data["quincenal_salary"]) == Decimal("3000.00")
    # Provisiones = 8.33% de lo devengado EN el período (regla de la planilla real
    # de la carpeta excel/: ZOILA 5040→420, MARVIN 3300→275), no el doble mensual.
    assert Decimal(resp.data["vacation_provision"]) == Decimal("250.00")
    assert Decimal(resp.data["thirteenth_month_provision"]) == Decimal("250.00")
    # INSS laboral 7% del básico devengado y neto = básico - retenciones.
    assert Decimal(resp.data["inss_laboral"]) == Decimal("210.00")
    assert Decimal(resp.data["net_to_pay"]) == Decimal("2790.00")


@pytest.mark.django_db
def test_jornal_y_mensual_a_la_vez_se_rechaza():
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=ENTRY_PERMS)
    period, sheet = _sheet(company, client.user)

    resp = client.post(
        f"{BASE}/periods/{period.id}/sheets/{sheet.id}/entries/",
        {
            "full_name": "Doble Salario",
            "salary_type": "DAILY",
            "daily_rate_nio": "250.00",
            "base_salary_nio": "9000.00",
            "days_worked": "12.00",
        },
        format="json",
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_jornal_en_mensual_se_rechaza():
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=ENTRY_PERMS)
    period, sheet = _sheet(company, client.user)

    resp = client.post(
        f"{BASE}/periods/{period.id}/sheets/{sheet.id}/entries/",
        {
            "full_name": "Mensual Confundido",
            "salary_type": "MONTHLY",
            "daily_rate_nio": "250.00",
            "days_worked": "15.00",
        },
        format="json",
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_entrada_desde_expediente_autollena_todo():
    """Con employee_id la entrada copia cédula/INSS/género/cargo/jornal del expediente HR."""
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=ENTRY_PERMS)
    period, sheet = _sheet(company, client.user)

    emp = Employee.objects.create(
        company=company, employee_code="E-100",
        first_name="Maria", last_name="Garcia Rivas",
        cedula="241-150590-0003B", inss_number="7305067", gender="F",
        salary_type="DAILY", daily_rate_nio=Decimal("250.00"),
    )
    pos = JobPosition.objects.create(company=company, name="Cortadora")
    EmploymentAssignment.objects.create(employee=emp, position=pos, branch=branch)

    resp = client.post(
        f"{BASE}/periods/{period.id}/sheets/{sheet.id}/entries/",
        {"employee_id": emp.id, "days_in_period": 15, "days_worked": "12.00"},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["full_name"] == "Maria Garcia Rivas"
    assert resp.data["cedula"] == "241-150590-0003B"
    assert resp.data["inss_number"] == "7305067"
    assert resp.data["gender"] == "F"
    assert resp.data["cargo"] == "Cortadora"
    assert resp.data["has_inss"] is True  # sin afiliación registrada → AFILIADO por defecto
    assert resp.data["salary_type"] == "DAILY"
    assert Decimal(resp.data["daily_rate_nio"]) == Decimal("250.000000")
    assert Decimal(resp.data["quincenal_salary"]) == Decimal("3000.00")


@pytest.mark.django_db
def test_entrada_desde_expediente_respeta_afiliacion_inss():
    """La afiliación NOT_AFFILIATED vigente del kernel manda sobre el default."""
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=ENTRY_PERMS)
    period, sheet = _sheet(company, client.user)

    emp = Employee.objects.create(
        company=company, first_name="Pedro", last_name="Sin Inss",
        salary_type="DAILY", daily_rate_nio=Decimal("200.00"),
    )
    EmployeeInssEnrollment.objects.create(
        company=company, employee=emp, regime=InssRegime.NOT_AFFILIATED,
        effective_from=date(2026, 1, 1),
    )

    resp = client.post(
        f"{BASE}/periods/{period.id}/sheets/{sheet.id}/entries/",
        {"employee_id": emp.id, "days_worked": "10.00"},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["has_inss"] is False
    assert Decimal(resp.data["inss_laboral"]) == Decimal("0.00")


@pytest.mark.django_db
def test_entrada_empleado_de_otra_empresa_se_rechaza():
    company, branch = _scope()
    other_company, _ = _scope()
    client = _client(company=company, branch=branch, perms=ENTRY_PERMS)
    period, sheet = _sheet(company, client.user)

    ajeno = Employee.objects.create(company=other_company, first_name="Ajeno")
    resp = client.post(
        f"{BASE}/periods/{period.id}/sheets/{sheet.id}/entries/",
        {"employee_id": ajeno.id, "days_worked": "10.00"},
        format="json",
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_entrada_manual_sin_nombre_se_rechaza():
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=ENTRY_PERMS)
    period, sheet = _sheet(company, client.user)

    resp = client.post(
        f"{BASE}/periods/{period.id}/sheets/{sheet.id}/entries/",
        {"salary_type": "DAILY", "daily_rate_nio": "250.00", "days_worked": "10.00"},
        format="json",
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_mensual_sigue_igual():
    """El camino MONTHLY no cambia: base mensual directa."""
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=ENTRY_PERMS)
    period, sheet = _sheet(company, client.user)

    resp = client.post(
        f"{BASE}/periods/{period.id}/sheets/{sheet.id}/entries/",
        {
            "full_name": "Empleada Mensual",
            "salary_type": "MONTHLY",
            "payment_frequency": "FIRST_HALF",
            "base_salary_nio": "15000.00",
            "days_in_period": 15,
            "days_worked": "15.00",
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert Decimal(resp.data["quincenal_salary"]) == Decimal("7500.00")


# ---------------------------------------------------------------------------
# Edición / borrado de una línea (PATCH/DELETE) — el "Editar línea" del frontend
# ---------------------------------------------------------------------------

def _crear_jornalero(client, period, sheet, *, days_worked="12.00"):
    """Jornalero DAILY C$250 × 12 días → quincenal 3000, INSS 210, neto 2790."""
    resp = client.post(
        f"{BASE}/periods/{period.id}/sheets/{sheet.id}/entries/",
        {
            "full_name": "Juan Jornalero",
            "has_inss": True,
            "salary_type": "DAILY",
            "payment_frequency": "FIRST_HALF",
            "daily_rate_nio": "250.00",
            "days_in_period": 15,
            "days_worked": days_worked,
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    return resp.data


@pytest.mark.django_db
def test_patch_recalcula_extras_y_deducciones():
    """Editar la línea con horas extra + otros ingresos + adelanto recalcula los totales."""
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=ENTRY_PERMS)
    period, sheet = _sheet(company, client.user)
    entry = _crear_jornalero(client, period, sheet)
    assert Decimal(entry["net_to_pay"]) == Decimal("2790.00")  # punto de partida

    resp = client.patch(
        f"{BASE}/periods/{period.id}/sheets/{sheet.id}/entries/{entry['id']}/",
        {"overtime_hours": "4.00", "other_income": "500.00", "advance_deduction": "300.00"},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    # Horas extra: (250/8) × 2 × 4 = 250
    assert Decimal(resp.data["overtime_amount"]) == Decimal("250.00")
    assert Decimal(resp.data["other_income"]) == Decimal("500.00")
    assert Decimal(resp.data["advance_deduction"]) == Decimal("300.00")
    # Ingresos: 3000 + vac 250 + 13vo 250 + extra 250 + otros 500 = 4250
    assert Decimal(resp.data["total_income"]) == Decimal("4250.00")
    # Devengado en efectivo: 3000 + 250 + 500 = 3750 ; retenciones: INSS 210 + adelanto 300 = 510
    assert Decimal(resp.data["net_to_pay"]) == Decimal("3240.00")


@pytest.mark.django_db
def test_patch_solo_corrige_dias():
    """Corregir días trabajados (10 en vez de 12) recalcula salario, INSS y neto."""
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=ENTRY_PERMS)
    period, sheet = _sheet(company, client.user)
    entry = _crear_jornalero(client, period, sheet)

    resp = client.patch(
        f"{BASE}/periods/{period.id}/sheets/{sheet.id}/entries/{entry['id']}/",
        {"days_worked": "10.00"},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    assert Decimal(resp.data["quincenal_salary"]) == Decimal("2500.00")
    assert Decimal(resp.data["inss_laboral"]) == Decimal("175.00")
    assert Decimal(resp.data["net_to_pay"]) == Decimal("2325.00")


@pytest.mark.django_db
def test_patch_bloqueado_si_planilla_no_borrador():
    """Una planilla enviada/aprobada es estable: no se editan sus líneas (409)."""
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=ENTRY_PERMS)
    period, sheet = _sheet(company, client.user)
    entry = _crear_jornalero(client, period, sheet)

    sheet.status = "SUBMITTED"
    sheet.save(update_fields=["status"])

    resp = client.patch(
        f"{BASE}/periods/{period.id}/sheets/{sheet.id}/entries/{entry['id']}/",
        {"other_income": "500.00"},
        format="json",
    )
    assert resp.status_code == 409, resp.data


@pytest.mark.django_db
def test_patch_y_delete_exigen_permiso_de_escritura():
    """Con solo nomina.entry.read no se puede editar ni quitar una línea (403)."""
    company, branch = _scope()
    creador = _client(company=company, branch=branch, perms=ENTRY_PERMS)
    period, sheet = _sheet(company, creador.user)
    entry = _crear_jornalero(creador, period, sheet)

    lector = _client(company=company, branch=branch, perms=["nomina.entry.read"])
    url = f"{BASE}/periods/{period.id}/sheets/{sheet.id}/entries/{entry['id']}/"
    assert lector.patch(url, {"other_income": "500.00"}, format="json").status_code == 403
    assert lector.delete(url).status_code == 403


@pytest.mark.django_db
def test_delete_quita_la_linea():
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=ENTRY_PERMS)
    period, sheet = _sheet(company, client.user)
    entry = _crear_jornalero(client, period, sheet)

    resp = client.delete(f"{BASE}/periods/{period.id}/sheets/{sheet.id}/entries/{entry['id']}/")
    assert resp.status_code == 204

    listado = client.get(f"{BASE}/periods/{period.id}/sheets/{sheet.id}/entries/")
    assert listado.status_code == 200
    assert all(e["id"] != entry["id"] for e in listado.data["results"])


@pytest.mark.django_db
def test_delete_bloqueado_si_planilla_no_borrador():
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=ENTRY_PERMS)
    period, sheet = _sheet(company, client.user)
    entry = _crear_jornalero(client, period, sheet)

    sheet.status = "APPROVED"
    sheet.save(update_fields=["status"])

    resp = client.delete(f"{BASE}/periods/{period.id}/sheets/{sheet.id}/entries/{entry['id']}/")
    assert resp.status_code == 409, resp.data
