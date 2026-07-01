"""Tests de vacaciones (Ola F): política, acumulación idempotente, registro directo,
días hábiles (excluye domingos/feriados), saldo insuficiente, anulación y ajuste."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.nomina.models import Holiday, HolidayDateKind, HolidayLegalType
from apps.modulos.hr.models import Employee, VacationRequest
from apps.modulos.hr.services_vacaciones import (
    VacationError,
    accrue_vacation_month,
    adjust_balance,
    cancel_vacation,
    get_or_create_vacation_policy,
    register_vacation,
    update_vacation_policy,
    vacation_balance,
    vacation_summary,
    _business_days,
)
from apps.modulos.iam.models import OrgUnit

User = get_user_model()
UT = OrgUnit.UnitType


def _mk_org():
    s = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=UT.HOLDING, name=f"H_{s}")
    company = OrgUnit.objects.create(unit_type=UT.COMPANY, name=f"C_{s}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=UT.BRANCH, name=f"B_{s}", parent=company)
    return holding, company, branch


def _mk_user():
    u = f"hr_{uuid.uuid4().hex[:8]}"
    return User.objects.create_user(username=u, email=f"{u}@t.local", password="pass12345")


def _mk_employee(company, **kw):
    return Employee.objects.create(company=company, first_name="Juan", last_name="Pérez", **kw)


@pytest.mark.django_db
def test_policy_default_is_legal_nicaragua():
    _, company, _ = _mk_org()
    policy = get_or_create_vacation_policy(company)
    assert policy.days_per_month == Decimal("2.50")


@pytest.mark.django_db
def test_accrual_is_idempotent():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    actor = _mk_user()
    created1 = accrue_vacation_month(company=company, year=2025, month=1, actor=actor)
    created2 = accrue_vacation_month(company=company, year=2025, month=1, actor=actor)
    assert created1 == 1
    assert created2 == 0  # idempotente: no duplica
    assert vacation_balance(emp) == Decimal("2.50")


@pytest.mark.django_db
def test_accrual_respects_cap():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    actor = _mk_user()
    update_vacation_policy(company=company, days_per_month=Decimal("2.5"), max_accrual_days=Decimal("4"), actor=actor)
    accrue_vacation_month(company=company, year=2025, month=1, actor=actor)  # +2.5 → 2.5
    accrue_vacation_month(company=company, year=2025, month=2, actor=actor)  # tope 4 → +1.5
    assert vacation_balance(emp) == Decimal("4.00")


@pytest.mark.django_db
def test_business_days_excludes_sundays():
    _, company, _ = _mk_org()
    # 2025-06-09 (lun) a 2025-06-15 (dom): 7 días calendario, 1 domingo → 6 hábiles.
    assert _business_days(company, date(2025, 6, 9), date(2025, 6, 15)) == 6


@pytest.mark.django_db
def test_business_days_excludes_company_holiday():
    _, company, _ = _mk_org()
    # Feriado de empresa el martes 2025-06-10.
    Holiday.objects.create(
        company=company,
        name="Feriado de prueba",
        legal_type=HolidayLegalType.EMPRESA,
        date_kind=HolidayDateKind.FIXED,
        month=6,
        day=10,
        applies_to_payroll=True,
        is_active=True,
    )
    # lun 09 a mié 11: 3 días, sin domingos, 1 feriado (mar 10) → 2 hábiles.
    assert _business_days(company, date(2025, 6, 9), date(2025, 6, 11)) == 2


@pytest.mark.django_db
def test_register_deducts_business_days():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    actor = _mk_user()
    adjust_balance(company=company, employee_id=emp.id, days=Decimal("30"), reason="Saldo inicial", actor=actor)
    req = register_vacation(
        company=company, employee_id=emp.id,
        start_date=date(2025, 6, 9), end_date=date(2025, 6, 15), actor=actor,
    )
    assert req.status == VacationRequest.Status.APROBADA
    assert req.business_days == Decimal("6.00")
    assert req.calendar_days == 7
    assert vacation_balance(emp) == Decimal("24.00")  # 30 - 6


@pytest.mark.django_db
def test_register_rejects_insufficient_balance():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    actor = _mk_user()
    adjust_balance(company=company, employee_id=emp.id, days=Decimal("3"), reason="poco", actor=actor)
    with pytest.raises(VacationError) as exc:
        register_vacation(
            company=company, employee_id=emp.id,
            start_date=date(2025, 6, 9), end_date=date(2025, 6, 15), actor=actor,
        )
    assert exc.value.code == "HR_VACATION_INSUFFICIENT_BALANCE"


@pytest.mark.django_db
def test_cancel_restores_balance():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    actor = _mk_user()
    adjust_balance(company=company, employee_id=emp.id, days=Decimal("30"), reason="inicial", actor=actor)
    req = register_vacation(
        company=company, employee_id=emp.id,
        start_date=date(2025, 6, 9), end_date=date(2025, 6, 13), actor=actor,
    )
    bal_after_take = vacation_balance(emp)
    cancel_vacation(company=company, request_id=req.id, reason="Error de captura", actor=actor)
    req.refresh_from_db()
    assert req.status == VacationRequest.Status.ANULADA
    assert vacation_balance(emp) == Decimal("30.00")
    assert bal_after_take < Decimal("30.00")


@pytest.mark.django_db
def test_cancel_twice_rejected():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    actor = _mk_user()
    adjust_balance(company=company, employee_id=emp.id, days=Decimal("30"), reason="inicial", actor=actor)
    req = register_vacation(
        company=company, employee_id=emp.id,
        start_date=date(2025, 6, 9), end_date=date(2025, 6, 13), actor=actor,
    )
    cancel_vacation(company=company, request_id=req.id, actor=actor)
    with pytest.raises(VacationError) as exc:
        cancel_vacation(company=company, request_id=req.id, actor=actor)
    assert exc.value.code == "VACATION_ALREADY_CANCELLED"


@pytest.mark.django_db
def test_summary_lists_active_employees_with_balance():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    actor = _mk_user()
    accrue_vacation_month(company=company, year=2025, month=1, actor=actor)
    rows = vacation_summary(company)
    row = next(r for r in rows if r["employee_id"] == emp.id)
    assert row["balance"] == "2.50"


@pytest.mark.django_db
def test_register_other_company_employee_rejected():
    _, c1, _ = _mk_org()
    _, c2, _ = _mk_org()
    emp2 = _mk_employee(c2)
    with pytest.raises(VacationError) as exc:
        register_vacation(
            company=c1, employee_id=emp2.id,
            start_date=date(2025, 6, 9), end_date=date(2025, 6, 10), actor=_mk_user(),
        )
    assert exc.value.code == "EMPLOYEE_NOT_FOUND"
