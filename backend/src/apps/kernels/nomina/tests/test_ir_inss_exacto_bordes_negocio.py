"""Cómputo EXACTO de INSS laboral/patronal e IR (finder de bugs de negocio).

Ataca el invariante legal NM-01 (la base del IR resta el INSS laboral, art. 21 LCT)
con NÚMEROS CONCRETOS, no triviales, y la anualización por frecuencia real:
  - Mensual quincenal (×24) de salario alto → tramo 5 del IR.
  - El INSS patronal toma el tramo correcto según el conteo REAL de trabajadores
    (política configurada actual): <50 = 21.5%, >=50 = 22.5%.
  - Trabajador SIN INSS: INSS laboral/patronal/INATEC = 0 e IR sobre el bruto.
  - Jornalero de salario mínimo agro → IR = 0 (no tributa).

Estos tests fijan los valores legales esperados. Si el cómputo cambia, fallan y
señalan el descuadre (esperado vs obtenido), no se ablandan.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.nomina.models import (
    PayrollEntry,
    PayrollPeriod,
    PayrollSheet,
    PeriodType,
    SalaryType,
)
from apps.kernels.nomina.services import compute_entry, create_default_nicaragua_config
from apps.modulos.hr.models import Employee
from apps.modulos.iam.models import OrgUnit

User = get_user_model()


def _scope():
    t = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H_{t}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name=f"C_{t}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, name=f"B_{t}", parent=company)
    return company, branch


def _actor():
    u = f"u_{uuid.uuid4().hex[:8]}"
    return User.objects.create_user(username=u, email=f"{u}@t.local", password="x")


def _request(actor, company, branch):
    return SimpleNamespace(
        user=actor, META={}, company=company, branch=branch, _request=None,
        ctx=None, request_id=f"req_{uuid.uuid4().hex[:8]}", path="", method="POST",
    )


def _period(company, *, ptype=PeriodType.FIRST_HALF, start=date(2026, 6, 1), end=date(2026, 6, 15), days=15):
    return PayrollPeriod.objects.create(
        company=company, year=2026, month=6, period_type=ptype,
        start_date=start, end_date=end, working_days=days,
    )


def _sheet(period, branch, *, has_inss=True):
    return PayrollSheet.objects.create(
        period=period, branch=branch, has_inss=has_inss,
        sheet_name=("Planilla CON INSS" if has_inss else "Planilla SIN INSS"),
    )


def _employee(company):
    return Employee.objects.create(
        company=company, employee_code=f"E-{uuid.uuid4().hex[:6]}",
        first_name="Trab", last_name="Test", is_active=True,
    )


@pytest.fixture
def ctx(db):
    company, branch = _scope()
    actor = _actor()
    create_default_nicaragua_config(
        request=_request(actor, company, branch), actor=actor, company=company,
        fiscal_year=2026, effective_from=date(2026, 1, 1),
    )
    return SimpleNamespace(company=company, branch=branch, actor=actor)


def test_ir_base_resta_inss_laboral_y_anualiza_x24(ctx):
    """Mensual quincenal, base C$50,000:
      quincenal = 25,000.00 ; INSS lab = 25,000 × 7% = 1,750.00
      base IR  = 25,000 − 1,750 = 23,250.00
      anual    = 23,250 × 24 = 558,000  → tramo 5: 82,500 + (558,000−500,000)×30% = 99,900
      IR período = 99,900 / 24 = 4,162.50
    """
    period = _period(ctx.company)
    sheet = _sheet(period, ctx.branch, has_inss=True)
    emp = _employee(ctx.company)
    entry = PayrollEntry.objects.create(
        sheet=sheet, employee=emp, full_name="Trab Test", has_inss=True,
        salary_type=SalaryType.MONTHLY, payment_frequency=PeriodType.FIRST_HALF,
        base_salary_nio=Decimal("50000.00"), days_in_period=15, days_worked=Decimal("15"),
    )
    # 5 trabajadores → tramo patronal pequeño (21.5%).
    compute_entry(entry=entry, worker_count=5)
    entry.refresh_from_db()

    assert entry.quincenal_salary == Decimal("25000.00"), entry.quincenal_salary
    assert entry.inss_laboral == Decimal("1750.00"), entry.inss_laboral
    assert entry.ir_amount == Decimal("4162.50"), (
        f"BUG NM-01/IR: IR esperado 4162.50 (base neta de INSS, anualizada ×24), obtenido {entry.ir_amount}"
    )
    # Patronal pequeño 21.5% sobre el devengado básico (25,000).
    assert entry.inss_patronal == Decimal("5375.00"), entry.inss_patronal
    assert entry.inatec == Decimal("500.00"), entry.inatec


def test_inss_patronal_tramo_grande_con_mas_de_50_trabajadores(ctx):
    """Mismo salario, pero >50 trabajadores → patronal 22.5% (BUG-7)."""
    period = _period(ctx.company)
    sheet = _sheet(period, ctx.branch, has_inss=True)
    emp = _employee(ctx.company)
    entry = PayrollEntry.objects.create(
        sheet=sheet, employee=emp, full_name="Trab Test", has_inss=True,
        salary_type=SalaryType.MONTHLY, payment_frequency=PeriodType.FIRST_HALF,
        base_salary_nio=Decimal("50000.00"), days_in_period=15, days_worked=Decimal("15"),
    )
    compute_entry(entry=entry, worker_count=60)
    entry.refresh_from_db()
    # 25,000 × 22.5% = 5,625.00
    assert entry.inss_patronal == Decimal("5625.00"), (
        f"BUG-7: patronal con >50 trab esperado 5625.00 (22.5%), obtenido {entry.inss_patronal}"
    )


@pytest.mark.parametrize(
    ("worker_count", "expected_patronal"),
    [
        (49, Decimal("5375.00")),
        (50, Decimal("5625.00")),
        (51, Decimal("5625.00")),
    ],
)
def test_inss_ir_golden_frontera_politica_configurada(ctx, worker_count, expected_patronal):
    """Congela la política técnica vigente; su validez legal sigue en LEGAL-PEND-002."""
    period = _period(ctx.company)
    sheet = _sheet(period, ctx.branch, has_inss=True)
    entry = PayrollEntry.objects.create(
        sheet=sheet,
        employee=_employee(ctx.company),
        full_name="Trab Test",
        has_inss=True,
        salary_type=SalaryType.MONTHLY,
        payment_frequency=PeriodType.FIRST_HALF,
        base_salary_nio=Decimal("50000.00"),
        days_in_period=15,
        days_worked=Decimal("15"),
    )

    compute_entry(entry=entry, worker_count=worker_count)
    entry.refresh_from_db()

    assert entry.quincenal_salary == Decimal("25000.00")
    assert entry.inss_laboral == Decimal("1750.00")
    assert entry.inss_patronal == expected_patronal
    assert entry.ir_amount == Decimal("4162.50")
    assert entry.total_deductions == Decimal("5912.50")
    assert entry.net_to_pay == Decimal("19087.50")


def test_sin_inss_no_retiene_inss_e_ir_sobre_bruto(ctx):
    """Trabajador SIN INSS: INSS lab/patronal/INATEC = 0, base IR = bruto (sin restar INSS).
      base IR = 25,000 ; anual = 600,000 → tramo 5: 82,500 + (600k−500k)×30% = 112,500
      IR período = 112,500 / 24 = 4,687.50
    """
    period = _period(ctx.company)
    sheet = _sheet(period, ctx.branch, has_inss=False)
    emp = _employee(ctx.company)
    entry = PayrollEntry.objects.create(
        sheet=sheet, employee=emp, full_name="Trab Test", has_inss=False,
        salary_type=SalaryType.MONTHLY, payment_frequency=PeriodType.FIRST_HALF,
        base_salary_nio=Decimal("50000.00"), days_in_period=15, days_worked=Decimal("15"),
    )
    compute_entry(entry=entry, worker_count=5)
    entry.refresh_from_db()
    assert entry.inss_laboral == Decimal("0.00"), entry.inss_laboral
    assert entry.inss_patronal == Decimal("0.00"), entry.inss_patronal
    assert entry.inatec == Decimal("0.00"), entry.inatec
    assert entry.ir_amount == Decimal("4687.50"), (
        f"IR sin INSS esperado 4687.50 (base = bruto, ×24), obtenido {entry.ir_amount}"
    )


def test_jornalero_salario_minimo_no_tributa_ir(ctx):
    """Jornalero (DAILY) de salario bajo: IR = 0 (cae en el primer tramo, 0%)."""
    period = _period(ctx.company, ptype=PeriodType.CATORCENA, start=date(2026, 6, 1), end=date(2026, 6, 14), days=14)
    sheet = _sheet(period, ctx.branch, has_inss=True)
    emp = _employee(ctx.company)
    # Salario mínimo agro mensual ~ C$5,000-ish; base diaria modesta.
    entry = PayrollEntry.objects.create(
        sheet=sheet, employee=emp, full_name="Jornal", has_inss=True,
        salary_type=SalaryType.DAILY, payment_frequency=PeriodType.CATORCENA,
        base_salary_nio=Decimal("6000.00"), days_in_period=14, days_worked=Decimal("12"),
    )
    compute_entry(entry=entry, worker_count=5)
    entry.refresh_from_db()
    assert entry.ir_amount == Decimal("0.00"), (
        f"BUG: un jornalero de salario mínimo NO debe tributar IR; obtenido {entry.ir_amount}"
    )


def test_total_deductions_y_neto_consistentes(ctx):
    """El neto debe ser devengado − deducciones (INSS lab + IR) y todo cuadrar."""
    period = _period(ctx.company)
    sheet = _sheet(period, ctx.branch, has_inss=True)
    emp = _employee(ctx.company)
    entry = PayrollEntry.objects.create(
        sheet=sheet, employee=emp, full_name="Trab Test", has_inss=True,
        salary_type=SalaryType.MONTHLY, payment_frequency=PeriodType.FIRST_HALF,
        base_salary_nio=Decimal("50000.00"), days_in_period=15, days_worked=Decimal("15"),
    )
    compute_entry(entry=entry, worker_count=5)
    entry.refresh_from_db()
    # total_deductions = INSS lab + IR (+ otras = 0)
    assert entry.total_deductions == (entry.inss_laboral + entry.ir_amount), (
        f"total_deductions {entry.total_deductions} != INSS+IR {entry.inss_laboral + entry.ir_amount}"
    )
    # net = devengado − deducciones (sin alimentación)
    assert entry.net_to_pay == (entry.total_devengado - entry.total_deductions), (
        f"net_to_pay {entry.net_to_pay} != devengado−deducciones "
        f"{entry.total_devengado - entry.total_deductions}"
    )
