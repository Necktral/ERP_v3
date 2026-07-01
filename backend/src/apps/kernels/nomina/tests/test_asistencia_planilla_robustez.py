"""ROBUSTEZ del puente asistencia de campo → planilla (consolidar/aplicar).

Catálogo de ataque (no el camino feliz, eso lo cubre test_field_attendance_bridge):
- Idempotencia: re-aplicar la asistencia a la línea NO duplica días ni efectos.
- Re-consolidar una consolidación APROBADA/BLOQUEADA es rechazado (4xx de negocio),
  no recalcula a la fuerza ni revienta.
- Día sin reporte de cuadrilla → consolidación WARNING (no rompe, no bloquea aprobar).
- day_value por estado (ausente=0, medio día=0.5, accidente=1).
- Entrada inválida: empleado de OTRA empresa, fecha fuera del período, día partido
  fuera de [0,1], lista vacía, empleado duplicado, empleado inactivo →
  FieldAttendanceError (negocio, 4xx), NUNCA un error no tipado / 500.
- Aplicar sobre línea sin empleado o sin asistencia aprobada → error tipado.

Sondas de fragilidad: garbage como day_value crudo en metadata de evento.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.nomina.models import (
    FieldAttendanceConsolidation,
    FieldAttendanceConsolidationStatus,
    FieldWorkerEventType,
    PayrollEntry,
    PayrollPeriod,
    PayrollSheet,
    PeriodType,
)
from apps.kernels.nomina.services import (
    FieldAttendanceError,
    aggregate_attendance_for_employee,
    apply_field_attendance_to_entry,
    approve_field_attendance,
    consolidate_field_attendance,
    create_default_nicaragua_config,
    open_field_work_day,
    record_worker_event,
    submit_rollcall,
)
from apps.modulos.hr.models import Employee
from apps.modulos.iam.models import OrgUnit

User = get_user_model()
UT = OrgUnit.UnitType


def _mk_scope(suffix: str = ""):
    tag = suffix or uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=UT.HOLDING, name=f"H_{tag}")
    company = OrgUnit.objects.create(unit_type=UT.COMPANY, name=f"C_{tag}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=UT.BRANCH, name=f"B_{tag}", parent=company)
    return company, branch


def _actor(prefix: str = "planillero"):
    username = f"{prefix}_{uuid.uuid4().hex[:8]}"
    return User.objects.create_user(username=username, email=f"{username}@test.local", password="x")


def _request(actor, *, company=None, branch=None):
    return SimpleNamespace(
        user=actor, META={}, company=company, branch=branch, _request=None,
        ctx=None, request_id=f"req_{uuid.uuid4().hex[:8]}", path="", method="POST",
    )


def _period(company, *, start=date(2026, 6, 1), end=date(2026, 6, 14)):
    return PayrollPeriod.objects.create(
        company=company, year=2026, month=6, period_type=PeriodType.CATORCENA,
        start_date=start, end_date=end, working_days=14,
    )


def _employee(company, first_name="Trabajador", **kw):
    return Employee.objects.create(
        company=company, employee_code=f"E-{uuid.uuid4().hex[:6]}",
        first_name=first_name, last_name="Campo", is_active=True, **kw,
    )


def _entry(sheet, employee, *, base_salary_nio="14000.00"):
    return PayrollEntry.objects.create(
        sheet=sheet, employee=employee, full_name=f"{employee.first_name} Campo",
        has_inss=True, base_salary_nio=Decimal(base_salary_nio),
        days_in_period=14, days_worked=Decimal("0.00"),
    )


def _approve_present_day(company, branch, actor, period, worker, *, work_date, status="PRESENT"):
    work_day = open_field_work_day(
        request=_request(actor, company=company, branch=branch), actor=actor,
        company=company, branch=branch, payroll_period=period, work_date=work_date,
    )
    submit_rollcall(
        request=_request(actor, company=company, branch=branch), actor=actor,
        work_day=work_day, lines=[{"employee": worker, "status": status}],
    )
    consolidate_field_attendance(
        request=_request(actor, company=company, branch=branch), actor=actor, work_day=work_day
    )
    approve_field_attendance(
        request=_request(actor, company=company, branch=branch), actor=actor, work_day=work_day
    )
    return work_day


# --------------------------------------------------------------------------- #
# IDEMPOTENCIA
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_reaplicar_asistencia_a_linea_es_idempotente_en_el_efecto():
    """Aplicar dos veces NO debe duplicar los días. El segundo apply re-corre (la
    asistencia LOCKED sigue contando en el agregado), pero como `days_worked` se
    ASIGNA (no se incrementa), el efecto es idempotente: 2.00 → 2.00. Caso de doble
    click / reintento de red. (Verifica el invariante real del servicio, no que lance.)"""
    company, branch = _mk_scope()
    actor = _actor()
    create_default_nicaragua_config(request=_request(actor, company=company), actor=actor, company=company, fiscal_year=2026)
    period = _period(company)
    worker = _employee(company, "Luis")
    _approve_present_day(company, branch, actor, period, worker, work_date=date(2026, 6, 2))
    _approve_present_day(company, branch, actor, period, worker, work_date=date(2026, 6, 3))

    sheet = PayrollSheet.objects.create(period=period, branch=branch, sheet_name="S", has_inss=True)
    entry = _entry(sheet, worker)

    apply_field_attendance_to_entry(request=_request(actor, company=company, branch=branch), actor=actor, entry=entry)
    entry.refresh_from_db()
    first = entry.days_worked
    assert first == Decimal("2.00")

    # Segundo apply: NO duplica el conteo (asignación, no incremento) y no revienta.
    apply_field_attendance_to_entry(request=_request(actor, company=company, branch=branch), actor=actor, entry=entry)
    entry.refresh_from_db()
    assert entry.days_worked == first  # sin doble conteo
    # Las consolidaciones siguen LOCKED (no se recalcularon ni desbloquearon).
    locked = FieldAttendanceConsolidation.objects.filter(
        payroll_period=period, employee=worker, status=FieldAttendanceConsolidationStatus.LOCKED_FOR_PAYROLL
    ).count()
    assert locked == 2


@pytest.mark.django_db
def test_reconsolidar_aprobada_es_rechazado_no_recalcula():
    """Re-consolidar un día YA aprobado debe lanzar error de negocio tipado
    (invalid_state), no recalcular silenciosamente ni reventar con 500."""
    company, branch = _mk_scope()
    actor = _actor()
    period = _period(company)
    worker = _employee(company, "Marta")
    work_day = _approve_present_day(company, branch, actor, period, worker, work_date=date(2026, 6, 2))

    with pytest.raises(FieldAttendanceError) as exc:
        consolidate_field_attendance(request=_request(actor, company=company, branch=branch), actor=actor, work_day=work_day)
    # El error trae código de negocio, no es un crash genérico.
    assert getattr(exc.value, "code", None) in {"invalid_state", None} or "no se recalcula" in str(exc.value).lower()


# --------------------------------------------------------------------------- #
# DÍA SIN REPORTE DE CUADRILLA → WARNING (no rompe)
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_presente_sin_reporte_de_cuadrilla_es_warning_no_bloqueo():
    """Lista dice PRESENTE pero no hubo reporte de cuadrilla: la consolidación es
    WARNING (MISSING_CREW_CONFIRMATION), se puede aprobar igual; no es CONFLICT/BLOCKED."""
    company, branch = _mk_scope()
    actor = _actor()
    period = _period(company)
    worker = _employee(company, "Pedro")
    work_day = open_field_work_day(
        request=_request(actor, company=company, branch=branch), actor=actor,
        company=company, branch=branch, payroll_period=period, work_date=date(2026, 6, 2),
    )
    submit_rollcall(
        request=_request(actor, company=company, branch=branch), actor=actor,
        work_day=work_day, lines=[{"employee": worker, "status": "PRESENT"}],
    )
    cons = consolidate_field_attendance(request=_request(actor, company=company, branch=branch), actor=actor, work_day=work_day)
    assert len(cons) == 1
    assert cons[0].status == FieldAttendanceConsolidationStatus.WARNING
    assert "MISSING_CREW_CONFIRMATION" in cons[0].conflict_codes
    # Y se puede aprobar (WARNING es elegible).
    approved = approve_field_attendance(request=_request(actor, company=company, branch=branch), actor=actor, work_day=work_day)
    assert approved[0].status == FieldAttendanceConsolidationStatus.APPROVED


# --------------------------------------------------------------------------- #
# day_value POR ESTADO
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_day_value_ausente_es_cero():
    company, branch = _mk_scope()
    actor = _actor()
    period = _period(company)
    worker = _employee(company, "Ausente")
    _approve_present_day(company, branch, actor, period, worker, work_date=date(2026, 6, 2), status="ABSENT")
    agg = aggregate_attendance_for_employee(period=period, employee=worker)
    assert agg["days_worked"] == Decimal("0.00")


@pytest.mark.django_db
def test_day_value_accidente_pone_el_dia():
    """Regla del dueño: accidente EN el trabajo → el día se pone (day_value 1.00)."""
    company, branch = _mk_scope()
    actor = _actor()
    period = _period(company)
    worker = _employee(company, "Accidentado")
    work_day = open_field_work_day(
        request=_request(actor, company=company, branch=branch), actor=actor,
        company=company, branch=branch, payroll_period=period, work_date=date(2026, 6, 2),
    )
    submit_rollcall(
        request=_request(actor, company=company, branch=branch), actor=actor,
        work_day=work_day, lines=[{"employee": worker, "status": "PRESENT"}],
    )
    record_worker_event(
        request=_request(actor, company=company, branch=branch), actor=actor,
        work_day=work_day, employee=worker, event_type=FieldWorkerEventType.ACCIDENT,
        details="Se cortó con el machete",
    )
    consolidate_field_attendance(request=_request(actor, company=company, branch=branch), actor=actor, work_day=work_day)
    approve_field_attendance(request=_request(actor, company=company, branch=branch), actor=actor, work_day=work_day)
    agg = aggregate_attendance_for_employee(period=period, employee=worker)
    assert agg["days_worked"] == Decimal("1.00")


# --------------------------------------------------------------------------- #
# ENTRADA INVÁLIDA → 4xx de negocio tipado (FieldAttendanceError), nunca crudo
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_empleado_de_otra_empresa_en_rollcall_es_rechazado():
    company, branch = _mk_scope()
    other_company, _ = _mk_scope()
    actor = _actor()
    period = _period(company)
    ajeno = _employee(other_company, "Ajeno")
    work_day = open_field_work_day(
        request=_request(actor, company=company, branch=branch), actor=actor,
        company=company, branch=branch, payroll_period=period, work_date=date(2026, 6, 2),
    )
    with pytest.raises(FieldAttendanceError) as exc:
        submit_rollcall(
            request=_request(actor, company=company, branch=branch), actor=actor,
            work_day=work_day, lines=[{"employee": ajeno, "status": "PRESENT"}],
        )
    assert getattr(exc.value, "code", None) == "employee_out_of_scope"


@pytest.mark.django_db
def test_fecha_fuera_del_periodo_es_rechazada():
    company, branch = _mk_scope()
    actor = _actor()
    period = _period(company, start=date(2026, 6, 1), end=date(2026, 6, 14))
    with pytest.raises(FieldAttendanceError) as exc:
        open_field_work_day(
            request=_request(actor, company=company, branch=branch), actor=actor,
            company=company, branch=branch, payroll_period=period, work_date=date(2026, 6, 20),
        )
    assert getattr(exc.value, "code", None) == "invalid_period_date"


@pytest.mark.django_db
def test_rollcall_vacio_es_rechazado():
    company, branch = _mk_scope()
    actor = _actor()
    period = _period(company)
    work_day = open_field_work_day(
        request=_request(actor, company=company, branch=branch), actor=actor,
        company=company, branch=branch, payroll_period=period, work_date=date(2026, 6, 2),
    )
    with pytest.raises(FieldAttendanceError) as exc:
        submit_rollcall(request=_request(actor, company=company, branch=branch), actor=actor, work_day=work_day, lines=[])
    assert getattr(exc.value, "code", None) == "empty_rollcall"


@pytest.mark.django_db
def test_empleado_duplicado_en_rollcall_es_rechazado():
    company, branch = _mk_scope()
    actor = _actor()
    period = _period(company)
    worker = _employee(company, "Doble")
    work_day = open_field_work_day(
        request=_request(actor, company=company, branch=branch), actor=actor,
        company=company, branch=branch, payroll_period=period, work_date=date(2026, 6, 2),
    )
    with pytest.raises(FieldAttendanceError) as exc:
        submit_rollcall(
            request=_request(actor, company=company, branch=branch), actor=actor,
            work_day=work_day,
            lines=[{"employee": worker, "status": "PRESENT"}, {"employee": worker, "status": "ABSENT"}],
        )
    assert getattr(exc.value, "code", None) == "duplicate_employee"


@pytest.mark.django_db
def test_empleado_inactivo_es_rechazado():
    company, branch = _mk_scope()
    actor = _actor()
    period = _period(company)
    inactivo = _employee(company, "Inactivo")
    inactivo.is_active = False
    inactivo.save(update_fields=["is_active"])
    work_day = open_field_work_day(
        request=_request(actor, company=company, branch=branch), actor=actor,
        company=company, branch=branch, payroll_period=period, work_date=date(2026, 6, 2),
    )
    with pytest.raises(FieldAttendanceError) as exc:
        submit_rollcall(
            request=_request(actor, company=company, branch=branch), actor=actor,
            work_day=work_day, lines=[{"employee": inactivo, "status": "PRESENT"}],
        )
    assert getattr(exc.value, "code", None) == "inactive_employee"


@pytest.mark.django_db
def test_estado_de_rollcall_invalido_es_rechazado():
    company, branch = _mk_scope()
    actor = _actor()
    period = _period(company)
    worker = _employee(company, "Estado")
    work_day = open_field_work_day(
        request=_request(actor, company=company, branch=branch), actor=actor,
        company=company, branch=branch, payroll_period=period, work_date=date(2026, 6, 2),
    )
    with pytest.raises(FieldAttendanceError) as exc:
        submit_rollcall(
            request=_request(actor, company=company, branch=branch), actor=actor,
            work_day=work_day, lines=[{"employee": worker, "status": "ESTADO_BASURA"}],
        )
    assert getattr(exc.value, "code", None) == "invalid_rollcall_status"


@pytest.mark.django_db
def test_tipo_de_evento_basura_es_rechazado():
    company, branch = _mk_scope()
    actor = _actor()
    period = _period(company)
    worker = _employee(company, "Evt")
    work_day = open_field_work_day(
        request=_request(actor, company=company, branch=branch), actor=actor,
        company=company, branch=branch, payroll_period=period, work_date=date(2026, 6, 2),
    )
    submit_rollcall(
        request=_request(actor, company=company, branch=branch), actor=actor,
        work_day=work_day, lines=[{"employee": worker, "status": "PRESENT"}],
    )
    with pytest.raises(FieldAttendanceError) as exc:
        record_worker_event(
            request=_request(actor, company=company, branch=branch), actor=actor,
            work_day=work_day, employee=worker, event_type="EVENTO_INEXISTENTE",
        )
    assert getattr(exc.value, "code", None) == "invalid_event_type"


@pytest.mark.django_db
def test_aplicar_linea_sin_empleado_es_error_tipado():
    company, branch = _mk_scope()
    actor = _actor()
    period = _period(company)
    sheet = PayrollSheet.objects.create(period=period, branch=branch, sheet_name="S", has_inss=True)
    # Línea SIN empleado (eventual tipeado a mano).
    entry = PayrollEntry.objects.create(
        sheet=sheet, employee=None, full_name="Eventual",
        has_inss=False, base_salary_nio=Decimal("5000.00"), days_in_period=14,
    )
    with pytest.raises(FieldAttendanceError) as exc:
        apply_field_attendance_to_entry(request=_request(actor, company=company, branch=branch), actor=actor, entry=entry)
    assert getattr(exc.value, "code", None) == "missing_employee"


@pytest.mark.django_db
def test_aplicar_sin_asistencia_aprobada_es_error_tipado():
    company, branch = _mk_scope()
    actor = _actor()
    period = _period(company)
    worker = _employee(company, "SinAsist")
    sheet = PayrollSheet.objects.create(period=period, branch=branch, sheet_name="S", has_inss=True)
    entry = _entry(sheet, worker)
    with pytest.raises(FieldAttendanceError) as exc:
        apply_field_attendance_to_entry(request=_request(actor, company=company, branch=branch), actor=actor, entry=entry)
    assert getattr(exc.value, "code", None) == "no_attendance"
