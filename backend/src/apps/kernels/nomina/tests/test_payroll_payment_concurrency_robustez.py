"""Tests de ROBUSTEZ — CONCURRENCIA en el pago del neto (Sala de Pago).

Superficie: PayrollPaymentView → register_payroll_payment_idempotent.

La idempotencia se apoya en `entry.payments.filter(reference=key).first()` SIN
lock (`select_for_update`) y SIN constraint único `(entry, reference)` en BD
(payroll_payments.py:102-110). El guard de sobrepago (`amount > remaining`,
services payroll_payments.py:48-53) tampoco bloquea filas: lee un `aggregate`
sin lock.

Hipótesis de fragilidad: dos requests SIMULTÁNEOS con la MISMA idempotency_key
(reintento de red de la cola offline mientras el primero sigue en vuelo, o doble
click) pueden ambos pasar el chequeo de "no existe aún" y AMBOS crear un pago →
DOBLE PAGO del mismo neto, sin que ninguna excepción los detenga.

Gate: tras `N` envíos concurrentes de la misma clave debe quedar EXACTAMENTE 1
PayrollPayment para esa línea (idempotencia real), y la suma pagada nunca debe
superar el neto. Si quedan 2+ → doble pago (CRÍTICO).

Patrón de concurrencia tomado de test_integration_idempotency_concurrency.py /
test_cash_session_double_close_concurrent (ThreadPoolExecutor + close_old_connections).
"""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connections
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
    u = User.objects.create_user(
        username=f"u_{uuid.uuid4().hex[:8]}", email=f"e_{uuid.uuid4().hex[:8]}@t.com", password="x"
    )
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


@pytest.mark.django_db(transaction=True)
def test_payroll_payment_concurrent_same_key_no_double_pay():
    """CRÍTICO (doble pago): N envíos SIMULTÁNEOS del pago del neto con la MISMA
    idempotency_key deben dejar EXACTAMENTE 1 PayrollPayment para la línea.

    Sin lock ni constraint único, la ventana entre `filter(reference=key).first()`
    y el `create()` permite que varios hilos creen pagos duplicados (doble pago).
    """
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=["nomina.payment.register"])
    period, sheet, entry = _approved_entry(company, branch, client.user)

    net = entry.net_to_pay or Decimal("0.00")
    assert net > 0, f"neto inesperado: {net}"

    url = f"{BASE}/periods/{period.id}/sheets/{sheet.id}/entries/{entry.id}/pay/"
    key = f"dev-conc-{uuid.uuid4().hex}"
    body = {"payment_method": "CASH", "amount": str(net), "idempotency_key": key}

    def _worker(_: int) -> int:
        close_old_connections()
        try:
            r = client.post(url, body, format="json")
            return int(r.status_code)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(_worker, range(8)))
    connections.close_all()

    assert all(s != 500 for s in statuses), f"500 en pago concurrente: {statuses}"

    payments = PayrollPayment.objects.filter(entry=entry)
    total_paid = sum((p.amount for p in payments), Decimal("0.00"))

    # Invariante de robustez financiera:
    assert payments.count() == 1, (
        f"DOBLE PAGO: misma idempotency_key produjo {payments.count()} pagos "
        f"(total C${total_paid}) para un neto de C${net}. statuses={statuses}"
    )
    assert total_paid <= net, f"sobrepago: pagado C${total_paid} > neto C${net}"


@pytest.mark.django_db(transaction=True)
def test_payroll_payment_concurrent_distinct_keys_no_overpay():
    """CRÍTICO (sobrepago): N envíos SIMULTÁNEOS del pago del neto COMPLETO con
    claves DISTINTAS no deben permitir pagar MÁS que el neto.

    El guard `amount > remaining` lee un aggregate sin lock; bajo concurrencia
    varios hilos leen remaining=net y todos crean su pago → total > neto.
    Esperado: uno gana, el resto recibe 422 (sobrepago). La suma nunca supera el neto.
    """
    company, branch = _scope()
    client = _client(company=company, branch=branch, perms=["nomina.payment.register"])
    period, sheet, entry = _approved_entry(company, branch, client.user)

    net = entry.net_to_pay or Decimal("0.00")
    assert net > 0

    url = f"{BASE}/periods/{period.id}/sheets/{sheet.id}/entries/{entry.id}/pay/"

    def _worker(i: int) -> int:
        close_old_connections()
        try:
            body = {"payment_method": "CASH", "amount": str(net), "idempotency_key": f"k-{i}-{uuid.uuid4().hex}"}
            r = client.post(url, body, format="json")
            return int(r.status_code)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(_worker, range(8)))
    connections.close_all()

    assert all(s != 500 for s in statuses), f"500 en pago concurrente: {statuses}"

    payments = PayrollPayment.objects.filter(entry=entry)
    total_paid = sum((p.amount for p in payments), Decimal("0.00"))
    assert total_paid <= net, (
        f"SOBREPAGO concurrente: pagado C${total_paid} > neto C${net} "
        f"({payments.count()} pagos). statuses={statuses}"
    )
