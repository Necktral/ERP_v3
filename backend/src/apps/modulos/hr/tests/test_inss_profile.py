"""Tests del toggle de INSS en el perfil del empleado (RH).

El perfil expone `pays_inss` que **delega** en la afiliación fechada maestra
(`nomina.EmployeeInssEnrollment`) — sin campo nuevo en Employee y sin tocar el cálculo.
Cambiar el régimen exige `nomina.inss.manage`; el resto del perfil solo `hr.employee.update`.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.kernels.nomina.models import EmployeeInssEnrollment, InssRegime
from apps.modulos.audit.models import AuditEvent
from apps.modulos.hr.models import Employee
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

User = get_user_model()
UT = OrgUnit.UnitType

HR_FULL = ["hr.employee.read", "hr.employee.create", "hr.employee.update", "nomina.inss.manage"]
HR_NO_INSS = ["hr.employee.read", "hr.employee.create", "hr.employee.update"]


def _mk_org():
    s = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=UT.HOLDING, name=f"H_{s}")
    company = OrgUnit.objects.create(unit_type=UT.COMPANY, name=f"C_{s}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=UT.BRANCH, name=f"B_{s}", parent=company)
    return holding, company, branch


def _client_with_perms(*, company, branch, perm_codes):
    uname = f"api_{uuid.uuid4().hex[:8]}"
    user = User.objects.create_user(username=uname, email=f"{uname}@t.local", password="pass12345")
    UserMembership.objects.create(user=user, org_unit=company, is_active=True)
    UserMembership.objects.create(user=user, org_unit=branch, is_active=True)
    role = Role.objects.create(name=f"role_{uuid.uuid4().hex[:8]}", is_active=True)
    for code in perm_codes:
        perm, _ = Permission.objects.get_or_create(code=code, defaults={"description": code, "is_active": True})
        RolePermission.objects.get_or_create(role=role, permission=perm)
    RoleAssignment.objects.create(user=user, role=role, org_unit=company, is_active=True)
    RoleAssignment.objects.create(user=user, role=role, org_unit=branch, is_active=True)

    client = APIClient()
    login = client.post(
        "/api/auth/login/", {"username": user.username, "password": "pass12345"}, format="json"
    )
    assert login.status_code == 200, login.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data.get('access')}")
    client.defaults["HTTP_X_COMPANY_ID"] = str(company.id)
    client.defaults["HTTP_X_BRANCH_ID"] = str(branch.id)
    return client


@pytest.mark.django_db
def test_create_pays_inss_false_creates_not_affiliated_enrollment():
    _, company, branch = _mk_org()
    client = _client_with_perms(company=company, branch=branch, perm_codes=HR_FULL)
    r = client.post("/api/hr/employees/", {"first_name": "Juan", "pays_inss": False}, format="json")
    assert r.status_code == 201, r.data
    emp = Employee.objects.get(id=r.data["id"])
    assert EmployeeInssEnrollment.resolve_for(emp, timezone.localdate()) == InssRegime.NOT_AFFILIATED

    p = client.get(f"/api/hr/employees/{emp.id}/profile/")
    assert p.status_code == 200, p.data
    assert p.data["pays_inss"] is False


@pytest.mark.django_db
def test_create_default_pays_inss_true_no_redundant_enrollment():
    _, company, branch = _mk_org()
    client = _client_with_perms(company=company, branch=branch, perm_codes=HR_FULL)
    r = client.post("/api/hr/employees/", {"first_name": "Ana"}, format="json")
    assert r.status_code == 201, r.data
    emp = Employee.objects.get(id=r.data["id"])
    # Default cotiza: resolve_for ya da AFFILIATED, sin registro redundante.
    assert EmployeeInssEnrollment.objects.filter(employee=emp).count() == 0
    assert EmployeeInssEnrollment.resolve_for(emp, timezone.localdate()) == InssRegime.AFFILIATED

    p = client.get(f"/api/hr/employees/{emp.id}/profile/")
    assert p.data["pays_inss"] is True


@pytest.mark.django_db
def test_create_pays_inss_false_without_perm_forbidden():
    """Crear sin cotizar también exige nomina.inss.manage (no se evade por la puerta de creación)."""
    _, company, branch = _mk_org()
    client = _client_with_perms(company=company, branch=branch, perm_codes=HR_NO_INSS)
    r = client.post("/api/hr/employees/", {"first_name": "Noé", "pays_inss": False}, format="json")
    assert r.status_code == 403, r.data
    assert "pays_inss" in r.data["error"]["details"]
    assert not Employee.objects.filter(company=company, first_name="Noé").exists()


@pytest.mark.django_db
def test_update_flip_inss_creates_dated_enrollment_and_audit():
    _, company, branch = _mk_org()
    client = _client_with_perms(company=company, branch=branch, perm_codes=HR_FULL)
    emp_id = client.post("/api/hr/employees/", {"first_name": "Luis"}, format="json").data["id"]

    u = client.patch(f"/api/hr/employees/{emp_id}/", {"pays_inss": False}, format="json")
    assert u.status_code == 200, u.data
    assert u.data["pays_inss"] is False

    emp = Employee.objects.get(id=emp_id)
    today = timezone.localdate()
    assert EmployeeInssEnrollment.resolve_for(emp, today) == InssRegime.NOT_AFFILIATED
    assert EmployeeInssEnrollment.objects.filter(employee=emp, effective_from=today).count() == 1
    assert AuditEvent.objects.filter(
        event_type="NOMINA_EMPLOYEE_INSS_REGIME_CHANGED",
        subject_type="EMPLOYEE_INSS_ENROLLMENT",
    ).exists()


@pytest.mark.django_db
def test_update_inss_change_without_perm_forbidden():
    _, company, branch = _mk_org()
    admin = _client_with_perms(company=company, branch=branch, perm_codes=HR_FULL)
    emp_id = admin.post("/api/hr/employees/", {"first_name": "Eva"}, format="json").data["id"]

    clerk = _client_with_perms(company=company, branch=branch, perm_codes=HR_NO_INSS)
    u = clerk.patch(f"/api/hr/employees/{emp_id}/", {"pays_inss": False}, format="json")
    assert u.status_code == 403, u.data
    assert "pays_inss" in u.data["error"]["details"]
    # No cambió el régimen.
    emp = Employee.objects.get(id=emp_id)
    assert EmployeeInssEnrollment.resolve_for(emp, timezone.localdate()) == InssRegime.AFFILIATED


@pytest.mark.django_db
def test_update_other_fields_without_inss_perm_ok():
    """Sin nomina.inss.manage se puede editar el resto del perfil (no se manda pays_inss)."""
    _, company, branch = _mk_org()
    clerk = _client_with_perms(company=company, branch=branch, perm_codes=HR_NO_INSS)
    emp_id = clerk.post("/api/hr/employees/", {"first_name": "Pio"}, format="json").data["id"]
    u = clerk.patch(f"/api/hr/employees/{emp_id}/", {"phone": "88990011"}, format="json")
    assert u.status_code == 200, u.data
    assert "pays_inss" not in u.data  # no se tocó INSS


@pytest.mark.django_db
def test_same_day_double_toggle_is_idempotent():
    _, company, branch = _mk_org()
    client = _client_with_perms(company=company, branch=branch, perm_codes=HR_FULL)
    emp_id = client.post("/api/hr/employees/", {"first_name": "Sol"}, format="json").data["id"]

    # Tres toggles el mismo día: no debe reventar por el unique (employee, effective_from).
    for value in (False, True, False):
        resp = client.patch(f"/api/hr/employees/{emp_id}/", {"pays_inss": value}, format="json")
        assert resp.status_code == 200, resp.data
        assert resp.data["pays_inss"] is value

    emp = Employee.objects.get(id=emp_id)
    today = timezone.localdate()
    assert EmployeeInssEnrollment.objects.filter(employee=emp, effective_from=today).count() == 1
    assert EmployeeInssEnrollment.resolve_for(emp, today) == InssRegime.NOT_AFFILIATED


@pytest.mark.django_db
def test_update_inss_retroactive_effective_from():
    """'No cotiza' con vigencia RETROACTIVA aplica a una planilla de un mes pasado."""
    _, company, branch = _mk_org()
    client = _client_with_perms(company=company, branch=branch, perm_codes=HR_FULL)
    emp_id = client.post("/api/hr/employees/", {"first_name": "Beto"}, format="json").data["id"]
    emp = Employee.objects.get(id=emp_id)
    # Sin afiliación: por default cotiza, incluso en una fecha pasada (abril).
    assert EmployeeInssEnrollment.resolve_for(emp, date(2026, 4, 16)) == InssRegime.AFFILIATED

    u = client.patch(
        f"/api/hr/employees/{emp_id}/",
        {"pays_inss": False, "inss_effective_from": "2026-01-01"},
        format="json",
    )
    assert u.status_code == 200, u.data
    # Ahora NO cotiza desde enero → la planilla de abril ya lo toma como SIN INSS.
    assert EmployeeInssEnrollment.resolve_for(emp, date(2026, 4, 16)) == InssRegime.NOT_AFFILIATED
    assert EmployeeInssEnrollment.objects.filter(employee=emp, effective_from=date(2026, 1, 1)).count() == 1


@pytest.mark.django_db
def test_create_with_retroactive_inss_effective_from():
    """Alta SIN cotizar con vigencia retroactiva crea la afiliación fechada en esa fecha."""
    _, company, branch = _mk_org()
    client = _client_with_perms(company=company, branch=branch, perm_codes=HR_FULL)
    r = client.post(
        "/api/hr/employees/",
        {"first_name": "Cora", "pays_inss": False, "inss_effective_from": "2026-01-01"},
        format="json",
    )
    assert r.status_code == 201, r.data
    emp = Employee.objects.get(id=r.data["id"])
    assert EmployeeInssEnrollment.resolve_for(emp, date(2026, 4, 16)) == InssRegime.NOT_AFFILIATED
    assert EmployeeInssEnrollment.objects.filter(employee=emp, effective_from=date(2026, 1, 1)).count() == 1


@pytest.mark.django_db
def test_update_complement_audit_after_snapshot_includes_fields():
    _, company, branch = _mk_org()
    client = _client_with_perms(company=company, branch=branch, perm_codes=HR_FULL)
    emp_id = client.post("/api/hr/employees/", {"first_name": "Rita"}, format="json").data["id"]

    u = client.patch(
        f"/api/hr/employees/{emp_id}/",
        {"salary_complement_enabled": True, "salary_complement_base_nio": "1500.00"},
        format="json",
    )
    assert u.status_code == 200, u.data

    ev = (
        AuditEvent.objects.filter(event_type="HR_EMPLOYEE_UPDATED", subject_id=str(emp_id))
        .order_by("-id")
        .first()
    )
    assert ev is not None
    assert ev.after_snapshot.get("salary_complement_enabled") is True
    assert ev.after_snapshot.get("salary_complement_base_nio") == "1500.00"
