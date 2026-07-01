"""Sala de pago — resumen consolidado por empleado (build_pay_summary)."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.nomina.models import (
    PayrollEntry,
    PayrollPaymentMethod,
    PayrollPeriod,
    PayrollSheet,
    PeriodStatus,
    PeriodType,
    SalaryComplementLine,
    SalaryComplementSheet,
    SalaryType,
)
from apps.kernels.nomina.pay_room import build_pay_summary
from apps.kernels.nomina.planilla_export import ROWS_PER_PAGE, print_page
from apps.kernels.nomina.payroll_payments import register_payroll_payment
from apps.kernels.nomina.services import compute_entry, create_default_nicaragua_config
from apps.modulos.hr.models import Employee
from apps.modulos.iam.models import OrgUnit

User = get_user_model()


def _scope():
    t = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H{t}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name=f"C{t}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, name=f"B{t}", parent=company)
    return company, branch


def _actor():
    u = f"u_{uuid.uuid4().hex[:8]}"
    return User.objects.create_user(username=u, email=f"{u}@t.local", password="x")


def _req(actor, company):
    return SimpleNamespace(user=actor, META={}, company=company, branch=None, _request=None,
                           ctx=None, request_id="r", path="", method="POST")


def _period(company, actor):
    create_default_nicaragua_config(request=_req(actor, company), actor=actor, company=company, fiscal_year=2026)
    return PayrollPeriod.objects.create(
        company=company, year=2026, month=6, period_type=PeriodType.SECOND_HALF,
        start_date=date(2026, 6, 16), end_date=date(2026, 6, 30), working_days=15,
        status=PeriodStatus.APPROVED,
    )


def _entry(sheet, emp, *, has_inss):
    entry = PayrollEntry.objects.create(
        sheet=sheet, employee=emp, full_name=f"{emp.first_name} {emp.last_name}".strip(),
        cedula=emp.cedula, inss_number=emp.inss_number, has_inss=has_inss,
        salary_type=SalaryType.MONTHLY, base_salary_nio=Decimal("12000.00"),
        days_in_period=15, days_worked=Decimal("15.00"),
    )
    return compute_entry(entry=entry)


@pytest.mark.django_db
def test_summary_agrupa_dos_planillas_y_complemento_por_empleado():
    company, branch = _scope()
    actor = _actor()
    period = _period(company, actor)

    sheet_con = PayrollSheet.objects.create(period=period, branch=branch, sheet_name="FINCA CON INSS", has_inss=True)
    sheet_sin = PayrollSheet.objects.create(period=period, branch=branch, sheet_name="FINCA SIN INSS", has_inss=False)

    emp_a = Employee.objects.create(company=company, employee_code="E-A", first_name="Ana", last_name="Lopez",
                                    cedula="001-AAA", inss_number="111", is_active=True)
    emp_b = Employee.objects.create(company=company, employee_code="E-B", first_name="Beto", last_name="Ruiz",
                                    cedula="002-BBB", inss_number="222", is_active=True)

    # Ana: planilla CON INSS. La nómina NO cobra comisariato ni préstamos → neto legal completo.
    entry_a = _entry(sheet_con, emp_a, has_inss=True)
    # Beto: planilla SIN INSS.
    _entry(sheet_sin, emp_b, has_inss=False)

    # Complemento de salario para Ana (C$1,000 bruto).
    comp = SalaryComplementSheet.objects.create(period=period, branch=branch, name="Complemento")
    SalaryComplementLine.objects.create(sheet=comp, employee=emp_a, full_name="Ana Lopez",
                                        cedula="001-AAA", amount_nio=Decimal("1000.00"))

    rows = build_pay_summary(period=period, company=company)
    by_name = {r["full_name"]: r for r in rows}
    assert set(by_name) == {"Ana Lopez", "Beto Ruiz"}

    # build_pay_summary devuelve Decimals (la VISTA es la que los pasa a string en JSON).
    ana = by_name["Ana Lopez"]
    assert ana["employee_code"] == "E-A"
    assert ana["planillas"] == ["CON INSS"]
    assert len(ana["sheets"]) == 1
    assert ana["complement"]["amount_nio"] == Decimal("1000.00")
    assert ana["complement"]["received"] is False

    # Neto total a entregar = neto legal COMPLETO + complemento; nada pagado aún.
    legal_neto = entry_a.net_to_pay
    assert ana["totales"]["neto_total_a_entregar"] == (legal_neto + Decimal("1000.00")).quantize(Decimal("0.01"))
    assert ana["totales"]["pagado"] == Decimal("0.00")
    assert ana["totales"]["pendiente"] == ana["totales"]["neto_total_a_entregar"]
    # Ya no hay recaudación: la nómina no cobra deudas internas.
    assert "recaudacion" not in ana

    beto = by_name["Beto Ruiz"]
    assert beto["planillas"] == ["SIN INSS"]


@pytest.mark.django_db
def test_summary_refleja_pago_parcial_en_remaining_y_pagado():
    company, branch = _scope()
    actor = _actor()
    period = _period(company, actor)
    sheet = PayrollSheet.objects.create(period=period, branch=branch, sheet_name="FINCA", has_inss=True)
    emp = Employee.objects.create(company=company, employee_code="E-1", first_name="Carlos", last_name="Diaz",
                                  cedula="003-CCC", inss_number="333", is_active=True)
    entry = _entry(sheet, emp, has_inss=True)

    register_payroll_payment(request=_req(actor, company), actor=actor, entry=entry,
                             payment_method=PayrollPaymentMethod.CASH, amount=Decimal("100.00"),
                             payment_date=date(2026, 7, 1))

    rows = build_pay_summary(period=period, company=company)
    row = rows[0]
    s = row["sheets"][0]
    assert s["already_paid"] == Decimal("100.00")
    assert s["remaining"] == (entry.net_to_pay - Decimal("100.00")).quantize(Decimal("0.01"))
    assert s["paid"] is False
    assert row["totales"]["pagado"] == Decimal("100.00")


def test_print_page_formula():
    # La hoja es 1-indexada y cambia cada ROWS_PER_PAGE trabajadores.
    assert print_page(1) == 1
    assert print_page(ROWS_PER_PAGE) == 1
    assert print_page(ROWS_PER_PAGE + 1) == 2
    assert print_page(2 * ROWS_PER_PAGE + 1) == 3


@pytest.mark.django_db
def test_summary_expone_ubicacion_y_posicion_impresa():
    """Cada hoja del resumen trae ubicación (sucursal) + No. y Hoja del papel impreso."""
    company, branch = _scope()
    actor = _actor()
    period = _period(company, actor)
    sheet = PayrollSheet.objects.create(period=period, branch=branch, sheet_name="FINCA", has_inss=True)
    for i in range(3):
        emp = Employee.objects.create(company=company, employee_code=f"E-{i}", first_name=f"N{i}", last_name="X",
                                      cedula=f"00{i}-PRT", inss_number=str(i), is_active=True)
        _entry(sheet, emp, has_inss=True)

    rows = build_pay_summary(period=period, company=company)
    by_entry = {s["entry_id"]: s for r in rows for s in r["sheets"]}
    # El No. impreso sigue el orden de `id` dentro de la hoja (igual que build_planilla_matrix).
    ordered_ids = list(PayrollEntry.objects.filter(sheet=sheet).order_by("id").values_list("id", flat=True))
    for pos, eid in enumerate(ordered_ids, start=1):
        assert by_entry[eid]["print_no"] == pos
        assert by_entry[eid]["print_page"] == print_page(pos)
        assert by_entry[eid]["location"] == branch.name  # ubicación = sucursal
    # ubicación a nivel fila (para la tarjeta) = la de su 1ª hoja.
    for r in rows:
        assert r["ubicacion"] == branch.name


@pytest.mark.django_db
def test_summary_ubicacion_usa_finca_de_la_asignacion_si_planilla_company_wide():
    """Planilla de toda la empresa (sin sucursal): la finca sale de la asignación de RH."""
    from apps.modulos.hr.models import EmploymentAssignment, JobPosition

    company, branch = _scope()  # branch = la finca (ej. 'Santa Isabel')
    actor = _actor()
    period = _period(company, actor)
    sheet = PayrollSheet.objects.create(period=period, branch=None, sheet_name="Planilla general", has_inss=False)
    emp = Employee.objects.create(company=company, employee_code="E-9", first_name="Z", last_name="Q",
                                  cedula="009-PRT", inss_number="9", is_active=True)
    pos = JobPosition.objects.create(company=company, name="Cortador")
    EmploymentAssignment.objects.create(employee=emp, position=pos, branch=branch, is_active=True)
    _entry(sheet, emp, has_inss=False)

    rows = build_pay_summary(period=period, company=company)
    s = rows[0]["sheets"][0]
    assert s["location"] == branch.name  # finca del trabajador, no "Planilla general"
    assert rows[0]["ubicacion"] == branch.name


@pytest.mark.django_db
def test_summary_ubicacion_fallback_a_empresa_sin_sucursal_ni_asignacion():
    company, _branch = _scope()
    actor = _actor()
    period = _period(company, actor)
    # Planilla company-wide y trabajador sin finca asignada → último recurso: la empresa.
    sheet = PayrollSheet.objects.create(period=period, branch=None, sheet_name="Planilla general", has_inss=False)
    emp = Employee.objects.create(company=company, employee_code="E-8", first_name="Y", last_name="W",
                                  cedula="008-PRT", inss_number="8", is_active=True)
    _entry(sheet, emp, has_inss=False)

    rows = build_pay_summary(period=period, company=company)
    s = rows[0]["sheets"][0]
    assert s["location"] == company.name  # nunca el genérico "Planilla general"
    assert s["print_no"] == 1
    assert s["print_page"] == 1
    assert rows[0]["ubicacion"] == company.name
