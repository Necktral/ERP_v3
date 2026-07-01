"""API del pagador — pago del neto (idempotente) + resumen de la sala de pago."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.kernels.nomina.models import (
    PayrollEntry,
    PayrollPayment,
    PayrollPeriod,
    PayrollSheet,
    PeriodStatus,
    PeriodType,
    SalaryType,
)
from apps.kernels.nomina.services import compute_entry, create_default_nicaragua_config
from apps.modulos.hr.models import Employee
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

User = get_user_model()
BASE = "/api/nomina"


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


def _approved_entry(company, branch, actor):
    req = SimpleNamespace(user=actor, META={}, company=company, branch=None, _request=None,
                          ctx=None, request_id="", path="", method="POST")
    create_default_nicaragua_config(request=req, actor=actor, company=company, fiscal_year=2026)
    period = PayrollPeriod.objects.create(
        company=company, year=2026, month=6, period_type=PeriodType.SECOND_HALF,
        start_date=date(2026, 6, 16), end_date=date(2026, 6, 30), working_days=15,
        status=PeriodStatus.APPROVED,
    )
    sheet = PayrollSheet.objects.create(period=period, branch=branch, sheet_name="FINCA", has_inss=True)
    emp = Employee.objects.create(company=company, employee_code="E-1", first_name="Ana", last_name="Lopez", is_active=True)
    entry = PayrollEntry.objects.create(
        sheet=sheet, employee=emp, full_name="Ana Lopez", has_inss=True,
        salary_type=SalaryType.MONTHLY, base_salary_nio=Decimal("12000.00"),
        days_in_period=15, days_worked=Decimal("15.00"),
    )
    compute_entry(entry=entry)
    return period, sheet, entry


@pytest.mark.django_db
def test_pay_endpoint_registra_y_es_idempotente():
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=["nomina.payment.register"])
    period, sheet, entry = _approved_entry(company, branch, client.user)

    url = f"{BASE}/periods/{period.id}/sheets/{sheet.id}/entries/{entry.id}/pay/"
    body = {"payment_method": "CASH", "amount": "100.00", "idempotency_key": "dev-abc-1"}

    r1 = client.post(url, body, format="json")
    assert r1.status_code == 201, r1.data
    r2 = client.post(url, body, format="json")  # replay del mismo comando offline
    assert r2.status_code == 201, r2.data

    # Idempotente: un solo pago, mismo id.
    assert PayrollPayment.objects.filter(entry=entry).count() == 1
    assert r1.data["id"] == r2.data["id"]


@pytest.mark.django_db
def test_pay_endpoint_rechaza_sobrepago():
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=["nomina.payment.register"])
    period, sheet, entry = _approved_entry(company, branch, client.user)

    url = f"{BASE}/periods/{period.id}/sheets/{sheet.id}/entries/{entry.id}/pay/"
    r = client.post(url, {"payment_method": "CASH", "amount": str(entry.net_to_pay + Decimal("1000"))}, format="json")
    assert r.status_code == 422, r.data


@pytest.mark.django_db
def test_pay_endpoint_sin_permiso_403():
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=["nomina.payment.read"])  # solo lectura
    period, sheet, entry = _approved_entry(company, branch, client.user)

    url = f"{BASE}/periods/{period.id}/sheets/{sheet.id}/entries/{entry.id}/pay/"
    r = client.post(url, {"payment_method": "CASH", "amount": "100.00"}, format="json")
    assert r.status_code == 403, r.data


@pytest.mark.django_db
def test_pay_summary_endpoint_lista_al_empleado():
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=["nomina.payment.read"])
    period, sheet, entry = _approved_entry(company, branch, client.user)

    r = client.get(f"{BASE}/periods/{period.id}/pay-summary/")
    assert r.status_code == 200, r.data
    assert r.data["count"] == 1
    assert r.data["results"][0]["full_name"] == "Ana Lopez"
    assert r.data["results"][0]["planillas"] == ["CON INSS"]


@pytest.mark.django_db
def test_pay_summary_sin_permiso_403():
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=["nomina.entry.read"])  # no payment.read
    period, sheet, entry = _approved_entry(company, branch, client.user)

    r = client.get(f"{BASE}/periods/{period.id}/pay-summary/")
    assert r.status_code == 403, r.data
