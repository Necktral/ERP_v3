"""Tests de INVARIANTES DE NEGOCIO de nómina (caza de bugs de cómputo/regla).

Ataca:
- H8: INSS fechado — un período RETROACTIVO toma el régimen vigente EN SU FECHA, no el de hoy.
- INSS laboral/patronal: tasas y CON/SIN INSS (apaga INSS+INATEC).
- Patronal por tamaño (umbral 50): 21.5% (<50) vs 22.5% (>=50).
- Base de IR: art. 21 LCT (debe restar INSS laboral) — documenta el comportamiento real.
- Complemento de salario: NUNCA crea PayrollEntry/INSS (net = gross).
- Snapshot del carnet worker_code en PayrollEntry.

Reusa el estilo/fixtures de test_nomina_inss.py.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.nomina.models import (
    EmployeeInssEnrollment,
    InssRegime,
    IRBracket,
    PayrollEntry,
    PayrollPeriod,
    PayrollSheet,
    PeriodType,
    SalaryType,
)
from apps.kernels.nomina.services import (
    compute_entry,
    create_default_nicaragua_config,
)
from apps.kernels.nomina.services_complement import create_complement_sheet
from apps.kernels.nomina.services_inss import (
    classify_entries_by_inss,
    resolve_period_inss_elections,
    set_employee_inss_enrollment,
)
from apps.modulos.hr.models import Employee
from apps.modulos.iam.models import OrgUnit

User = get_user_model()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _mk_scope(suffix: str = ""):
    tag = suffix or uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H_{tag}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name=f"C_{tag}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, name=f"B_{tag}", parent=company)
    return company, branch


def _actor(prefix: str = "planillero"):
    username = f"{prefix}_{uuid.uuid4().hex[:8]}"
    return User.objects.create_user(username=username, email=f"{username}@test.local", password="x")


def _request(actor, *, company=None, branch=None):
    return SimpleNamespace(
        user=actor, META={}, company=company, branch=branch, _request=None,
        ctx=None, request_id=f"req_{uuid.uuid4().hex[:8]}", path="", method="POST",
    )


def _period(company, *, year=2026, month=6, ptype=PeriodType.CATORCENA,
            start=date(2026, 6, 1), end=date(2026, 6, 14), days=14):
    return PayrollPeriod.objects.create(
        company=company, year=year, month=month, period_type=ptype,
        start_date=start, end_date=end, working_days=days,
    )


def _employee(company, first_name="Trabajador"):
    return Employee.objects.create(
        company=company, employee_code=f"E-{uuid.uuid4().hex[:6]}",
        first_name=first_name, last_name="Campo", is_active=True,
    )


def _entry(sheet, employee, *, has_inss=True, base="14000.00", days="14", days_in=14,
           ptype=PeriodType.CATORCENA, salary_type=SalaryType.MONTHLY):
    return PayrollEntry.objects.create(
        sheet=sheet, employee=employee, full_name=f"{employee.first_name} Campo",
        has_inss=has_inss, base_salary_nio=Decimal(base), days_in_period=days_in,
        days_worked=Decimal(days), payment_frequency=ptype, salary_type=salary_type,
    )


# =========================================================================== #
# H8 — INSS FECHADO: un período retroactivo NO toma el régimen de HOY
# =========================================================================== #

@pytest.mark.django_db
def test_h8_retro_period_uses_regime_effective_at_its_date():
    """El bug histórico H8: un trabajador que HOY no cotiza, pero SÍ cotizaba en
    el mes pasado, debe salir CON INSS en la planilla retroactiva de ese mes."""
    company, branch = _mk_scope()
    actor = _actor()
    req = _request(actor, company=company, branch=branch)
    create_default_nicaragua_config(request=req, actor=actor, company=company, fiscal_year=2026)
    emp = _employee(company, "Maria")

    # Cotizaba desde enero; dejó de cotizar desde el 1 de junio.
    set_employee_inss_enrollment(request=req, actor=actor, employee=emp,
                                 regime=InssRegime.AFFILIATED, effective_from=date(2026, 1, 1))
    set_employee_inss_enrollment(request=req, actor=actor, employee=emp,
                                 regime=InssRegime.NOT_AFFILIATED, effective_from=date(2026, 6, 1))

    # Resolución por fecha: marzo -> AFFILIATED; junio -> NOT_AFFILIATED.
    assert EmployeeInssEnrollment.resolve_for(emp, date(2026, 3, 15)) == InssRegime.AFFILIATED
    assert EmployeeInssEnrollment.resolve_for(emp, date(2026, 6, 15)) == InssRegime.NOT_AFFILIATED

    # Planilla RETROACTIVA de marzo (período cuyo start_date es 2026-03-01).
    period_mar = _period(company, month=3, start=date(2026, 3, 1), end=date(2026, 3, 14))
    sheet = PayrollSheet.objects.create(period=period_mar, branch=branch,
                                        sheet_name="Finca CON INSS", has_inss=True)
    entry = _entry(sheet, emp, has_inss=True)
    compute_entry(entry=entry)

    # La elección por afiliación para ese período debe ser "SÍ cotiza" (régimen de marzo).
    elections = resolve_period_inss_elections(request=req, actor=actor, period=period_mar)
    assert elections[emp.id] is True, (
        "H8: el período retroactivo de marzo debe tomar el régimen AFFILIATED vigente "
        "en marzo, no el NOT_AFFILIATED de hoy."
    )

    # Y tras clasificar, la entrada de marzo queda CON INSS con INSS laboral > 0.
    classify_entries_by_inss(request=req, actor=actor, period=period_mar)
    entry.refresh_from_db()
    assert entry.has_inss is True
    assert entry.inss_laboral > Decimal("0.00")


@pytest.mark.django_db
def test_h8_current_period_drops_inss_when_regime_changed():
    """Espejo del anterior: la planilla del período ACTUAL (junio) sale SIN INSS."""
    company, branch = _mk_scope()
    actor = _actor()
    req = _request(actor, company=company, branch=branch)
    create_default_nicaragua_config(request=req, actor=actor, company=company, fiscal_year=2026)
    emp = _employee(company, "Maria")
    set_employee_inss_enrollment(request=req, actor=actor, employee=emp,
                                 regime=InssRegime.AFFILIATED, effective_from=date(2026, 1, 1))
    set_employee_inss_enrollment(request=req, actor=actor, employee=emp,
                                 regime=InssRegime.NOT_AFFILIATED, effective_from=date(2026, 6, 1))

    period_jun = _period(company, month=6, start=date(2026, 6, 1), end=date(2026, 6, 14))
    sheet = PayrollSheet.objects.create(period=period_jun, branch=branch,
                                        sheet_name="Finca CON INSS", has_inss=True)
    entry = _entry(sheet, emp, has_inss=True)
    compute_entry(entry=entry)
    classify_entries_by_inss(request=req, actor=actor, period=period_jun)
    entry.refresh_from_db()
    assert entry.has_inss is False
    assert entry.inss_laboral == Decimal("0.00")


# =========================================================================== #
# INSS laboral / patronal — tasas correctas
# =========================================================================== #

@pytest.mark.django_db
def test_inss_laboral_is_7pct_of_basic_earned_monthly():
    """Mensual C$14.000, 14/14 días -> salario quincenal completo = 7.000.
    INSS laboral = 7% de 7.000 = 490.00."""
    company, branch = _mk_scope()
    actor = _actor()
    req = _request(actor, company=company, branch=branch)
    create_default_nicaragua_config(request=req, actor=actor, company=company, fiscal_year=2026)
    emp = _employee(company)
    period = _period(company)
    sheet = PayrollSheet.objects.create(period=period, branch=branch, sheet_name="S", has_inss=True)
    # 14000/30 = 466.666667 diario; worked 14 -> 6533.33; pero days_in=14 => worked==period_days
    # => quincenal_base = 14000/2 = 7000.00 (rama mensual con worked >= period_days)
    entry = _entry(sheet, emp, has_inss=True, base="14000.00", days="14", days_in=14)
    compute_entry(entry=entry)
    entry.refresh_from_db()
    assert entry.quincenal_salary == Decimal("7000.00")
    assert entry.inss_laboral == Decimal("490.00")  # 7000 * 0.07


@pytest.mark.django_db
def test_inss_patronal_rate_by_worker_count_threshold():
    """Patronal: 21.5% si <50 trabajadores, 22.5% si >=50 (umbral 50)."""
    company, branch = _mk_scope()
    actor = _actor()
    req = _request(actor, company=company, branch=branch)
    create_default_nicaragua_config(request=req, actor=actor, company=company, fiscal_year=2026)
    emp = _employee(company)
    period = _period(company)
    sheet = PayrollSheet.objects.create(period=period, branch=branch, sheet_name="S", has_inss=True)

    # < 50 trabajadores -> 21.5%
    e_small = _entry(sheet, emp, has_inss=True, base="14000.00", days="14", days_in=14)
    compute_entry(entry=e_small, worker_count=10)
    e_small.refresh_from_db()
    assert e_small.inss_patronal == Decimal("1505.00")  # 7000 * 0.215

    # >= 50 trabajadores -> 22.5%
    emp2 = _employee(company, "Otro")
    e_large = _entry(sheet, emp2, has_inss=True, base="14000.00", days="14", days_in=14)
    compute_entry(entry=e_large, worker_count=50)
    e_large.refresh_from_db()
    assert e_large.inss_patronal == Decimal("1575.00")  # 7000 * 0.225


@pytest.mark.django_db
def test_inatec_is_2pct_of_basic_earned():
    """INATEC patronal = 2% del básico devengado (C$7.000 -> 140.00)."""
    company, branch = _mk_scope()
    actor = _actor()
    req = _request(actor, company=company, branch=branch)
    create_default_nicaragua_config(request=req, actor=actor, company=company, fiscal_year=2026)
    emp = _employee(company)
    period = _period(company)
    sheet = PayrollSheet.objects.create(period=period, branch=branch, sheet_name="S", has_inss=True)
    entry = _entry(sheet, emp, has_inss=True, base="14000.00", days="14", days_in=14)
    compute_entry(entry=entry, worker_count=10)
    entry.refresh_from_db()
    assert entry.inatec == Decimal("140.00")  # 7000 * 0.02


@pytest.mark.django_db
def test_employer_cost_default_worker_count_overcharges_patronal():
    """BUG histórico de patronal: el flujo de la vista (views.py:241) llama
    `compute_all_entries_in_sheet(sheet=sheet)` SIN pasar worker_count, así que
    queda el default 999 (compute_all/compute_entry: worker_count=999). Una empresa
    PEQUEÑA (<50) debería cotizar patronal al 21.5%, pero por el default sale al
    22.5% (tasa de empresa grande), sobrecargando el costo patronal.

    Demostración con número cerrado: básico C$7.000.
      - patronal correcto (10 trabajadores)  = 7000 * 0.215 = 1505.00
      - patronal por default (worker_count=999, >= umbral 50) = 7000 * 0.225 = 1575.00
    El flujo real produce 1575.00 (de más) en lugar de 1505.00.
    """
    company, branch = _mk_scope()
    actor = _actor()
    req = _request(actor, company=company, branch=branch)
    create_default_nicaragua_config(request=req, actor=actor, company=company, fiscal_year=2026)
    emp = _employee(company)
    period = _period(company)
    sheet = PayrollSheet.objects.create(period=period, branch=branch, sheet_name="S", has_inss=True)
    _entry(sheet, emp, has_inss=True, base="14000.00", days="14", days_in=14)

    # Flujo REAL de la planilla: sin worker_count -> default 999.
    from apps.kernels.nomina.services import compute_all_entries_in_sheet
    compute_all_entries_in_sheet(sheet=sheet)
    e = sheet.entries.get()
    e.refresh_from_db()

    # La empresa tiene 1 sola persona en la planilla (small). Patronal legal = 21.5%.
    assert e.inss_patronal == Decimal("1505.00"), (
        f"NM-patronal: el flujo de planilla usa worker_count default=999 -> patronal "
        f"al 22.5% (empresa grande) = {e.inss_patronal}, cuando una empresa pequeña "
        f"debe cotizar 21.5% = 1505.00. Sobrecarga de C${e.inss_patronal - Decimal('1505.00')} "
        f"por trabajador/período. Origen: compute_entry/compute_all default worker_count=999 "
        f"(services.py:364,376; models.py:650) + views.py:241 no pasa el conteo real."
    )


@pytest.mark.django_db
def test_sin_inss_zeroes_laboral_patronal_and_inatec():
    company, branch = _mk_scope()
    actor = _actor()
    req = _request(actor, company=company, branch=branch)
    create_default_nicaragua_config(request=req, actor=actor, company=company, fiscal_year=2026)
    emp = _employee(company)
    period = _period(company)
    sheet = PayrollSheet.objects.create(period=period, branch=branch, sheet_name="SIN", has_inss=False)
    entry = _entry(sheet, emp, has_inss=False, base="14000.00", days="14", days_in=14)
    compute_entry(entry=entry)
    entry.refresh_from_db()
    assert entry.inss_laboral == Decimal("0.00")
    assert entry.inss_patronal == Decimal("0.00")
    assert entry.inatec == Decimal("0.00")


# =========================================================================== #
# IR — base gravable (art. 21 LCT: debe restar INSS laboral)
# =========================================================================== #

@pytest.mark.django_db
def test_ir_base_should_subtract_inss_laboral_art21_lct():
    """NM-01 (auditoría legal): la base del IR debe ser devengado - INSS laboral (art. 21 LCT).

    Trabajador asalariado mensual C$20.000 que SÍ tributa IR. Comprobamos cuál es el IR que
    cobra el sistema vs el IR legalmente correcto (base neta de INSS). Si el sistema NO resta
    el INSS, sobreestima la retención de IR -> hallazgo de ley.
    """
    company, branch = _mk_scope()
    actor = _actor()
    req = _request(actor, company=company, branch=branch)
    cfg = create_default_nicaragua_config(request=req, actor=actor, company=company, fiscal_year=2026)
    emp = _employee(company, "Asalariado")
    # Salario alto para caer en tramo de IR > 0. Usamos catorcena (la planilla real del holding).
    period = _period(company, month=6, ptype=PeriodType.CATORCENA,
                     start=date(2026, 6, 1), end=date(2026, 6, 14), days=14)
    sheet = PayrollSheet.objects.create(period=period, branch=branch, sheet_name="Admin CON INSS", has_inss=True)
    entry = _entry(sheet, emp, has_inss=True, base="40000.00", days="14", days_in=14,
                   ptype=PeriodType.CATORCENA)
    compute_entry(entry=entry)
    entry.refresh_from_db()

    # La BASE real del período que el sistema usó para INSS/IR es el básico devengado.
    basic_earned = (entry.quincenal_salary + entry.seventh_day_amount + entry.holiday_amount)
    inss_laboral = entry.inss_laboral
    assert inss_laboral > 0  # el trabajador cotiza
    ppy = 26  # catorcena
    # IR que el sistema cobró (base bruta = basic_earned, sin restar INSS):
    ir_actual = entry.ir_amount
    # IR legalmente correcto (base = básico devengado - INSS laboral, art. 21 LCT):
    ir_legal = IRBracket.calculate_period_ir(
        config=cfg, period_income=(basic_earned - inss_laboral), periods_per_year=ppy
    )
    # Si el sistema NO resta el INSS, su IR es MAYOR que el legal -> sobreestima la retención.
    assert ir_actual == ir_legal, (
        f"NM-01: el IR debe calcularse sobre la base neta de INSS (art. 21 LCT). "
        f"básico devengado={basic_earned} INSS laboral={inss_laboral}; "
        f"IR sistema={ir_actual} (base bruta {basic_earned}); "
        f"IR legal={ir_legal} (base neta {basic_earned - inss_laboral})."
    )


@pytest.mark.django_db
def test_ir_overcharge_exact_amount_catorcena_40000():
    """NM-01 con NÚMERO CERRADO de regresión: catorcena, básico devengado C$20.000,
    INSS laboral 7% = C$1.400.

      - IR sistema (base bruta 20.000)        = 3403.85
      - IR legal   (base neta 20.000-1.400)   = 3015.38   (art. 21 LCT)
      - Sobreestimación por catorcena          = 388.47

    Mientras el código compute IR sobre `basic_earned` bruto (models.py:774, antes
    de restar INSS en la línea 780), este test FALLA y deja la cifra exacta del daño.
    """
    company, branch = _mk_scope()
    actor = _actor()
    req = _request(actor, company=company, branch=branch)
    cfg = create_default_nicaragua_config(request=req, actor=actor, company=company, fiscal_year=2026)
    emp = _employee(company, "Asalariado")
    period = _period(company, month=6, ptype=PeriodType.CATORCENA,
                     start=date(2026, 6, 1), end=date(2026, 6, 14), days=14)
    sheet = PayrollSheet.objects.create(period=period, branch=branch, sheet_name="Admin", has_inss=True)
    entry = _entry(sheet, emp, has_inss=True, base="40000.00", days="14", days_in=14,
                   ptype=PeriodType.CATORCENA)
    compute_entry(entry=entry)
    entry.refresh_from_db()

    assert entry.inss_laboral == Decimal("1400.00")
    ir_legal = IRBracket.calculate_period_ir(
        config=cfg, period_income=(Decimal("20000.00") - Decimal("1400.00")), periods_per_year=26
    )
    assert ir_legal == Decimal("3015.38")  # control del cálculo legal esperado
    assert entry.ir_amount == ir_legal, (
        f"NM-01 regresión: IR sistema={entry.ir_amount} vs IR legal={ir_legal}; "
        f"sobreestima C${entry.ir_amount - ir_legal} por catorcena."
    )


# =========================================================================== #
# Complemento de salario — NUNCA crea PayrollEntry/INSS
# =========================================================================== #

@pytest.mark.django_db
def test_complement_sheet_never_creates_payroll_entry_or_inss():
    company, branch = _mk_scope()
    actor = _actor()
    req = _request(actor, company=company, branch=branch)
    period = _period(company)
    emp = _employee(company, "Convenio")
    emp.salary_complement_enabled = True
    emp.salary_complement_base_nio = Decimal("5000.00")
    emp.save(update_fields=["salary_complement_enabled", "salary_complement_base_nio"])

    before_entries = PayrollEntry.objects.count()
    sheet = create_complement_sheet(request=req, actor=actor, period=period, branch=branch)
    after_entries = PayrollEntry.objects.count()

    assert after_entries == before_entries, "El complemento NO debe crear PayrollEntry."
    line = sheet.lines.get(employee=emp)
    # net = gross: no INSS/IR. El monto base del perfil se sembró tal cual.
    assert line.amount_nio == Decimal("5000.00")


# =========================================================================== #
# Snapshot del carnet worker_code
# =========================================================================== #

@pytest.mark.django_db
def test_worker_code_snapshot_persists_on_entry():
    """El carnet (worker_code) es snapshot en el renglón: una vez fijado, se conserva
    aunque el modelo del empleado cambie después."""
    company, branch = _mk_scope()
    actor = _actor()
    req = _request(actor, company=company, branch=branch)
    create_default_nicaragua_config(request=req, actor=actor, company=company, fiscal_year=2026)
    emp = _employee(company)
    period = _period(company)
    sheet = PayrollSheet.objects.create(period=period, branch=branch, sheet_name="S", has_inss=True)
    entry = PayrollEntry.objects.create(
        sheet=sheet, employee=emp, full_name="X Campo", has_inss=True,
        base_salary_nio=Decimal("14000.00"), days_in_period=14, days_worked=Decimal("14"),
        worker_code="CARNET-001",
    )
    compute_entry(entry=entry)
    entry.refresh_from_db()
    # compute_all NO debe borrar el snapshot del carnet.
    assert entry.worker_code == "CARNET-001"
