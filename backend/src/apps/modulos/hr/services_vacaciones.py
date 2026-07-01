"""Vacaciones: política de acumulación, ledger de saldo y registro directo.

Modelo de saldo estilo ledger (como el kernel contable): el saldo es la suma de
movimientos con signo. La acumulación mensual es idempotente por (empleado, año,
mes). Las vacaciones se registran directamente por RRHH (sin doble firma) y
descuentan días HÁBILES (excluyen domingos y feriados).

Default legal Nicaragua (Art. 76 CT): 2.5 días/mes (30/año), configurable.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.modulos.audit.writer import write_event

from .models import Employee, VacationLedgerEntry, VacationPolicy, VacationRequest

Q2 = Decimal("0.01")


class VacationError(Exception):
    """Error de negocio de vacaciones; el código viaja como detail."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _q2(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Q2)


# ---------------------------------------------------------------------------
# Política
# ---------------------------------------------------------------------------

def get_or_create_vacation_policy(company) -> VacationPolicy:
    policy, _ = VacationPolicy.objects.get_or_create(company=company)
    return policy


@transaction.atomic
def update_vacation_policy(
    *, company, days_per_month, max_accrual_days=None, is_active=True, request=None, actor=None
) -> VacationPolicy:
    policy = get_or_create_vacation_policy(company)
    policy.days_per_month = _q2(days_per_month)
    policy.max_accrual_days = _q2(max_accrual_days) if max_accrual_days is not None else None
    policy.is_active = bool(is_active)
    policy.updated_by = actor
    policy.save()
    write_event(
        request=request,
        module="HR",
        event_type="HR_VACATION_POLICY_UPDATED",
        reason_code="OK",
        actor_user=actor,
        subject_type="VACATION_POLICY",
        subject_id=str(company.id),
        metadata={
            "days_per_month": str(policy.days_per_month),
            "max_accrual_days": str(policy.max_accrual_days) if policy.max_accrual_days is not None else "",
        },
    )
    return policy


# ---------------------------------------------------------------------------
# Días hábiles (excluye domingos + feriados)
# ---------------------------------------------------------------------------

def _holiday_dates_in_range(company, start: date, end: date) -> set[date]:
    """Fechas feriadas (catálogo nacional + propias de la empresa) en el rango."""
    from apps.kernels.nomina.models import Holiday

    qs = Holiday.objects.filter(is_active=True, applies_to_payroll=True)
    if company is not None and getattr(company, "id", None) is not None:
        from django.db.models import Q

        qs = qs.filter(Q(company__isnull=True) | Q(company_id=company.id))
    else:
        qs = qs.filter(company__isnull=True)

    out: set[date] = set()
    for holiday in qs:
        for year in range(start.year, end.year + 1):
            d = holiday.date_for_year(year)
            if d is not None and start <= d <= end:
                out.add(d)
    return out


def _business_days(company, start: date, end: date) -> int:
    """Días hábiles en [start, end] inclusive (excluye domingos y feriados)."""
    if end < start:
        return 0
    holidays = _holiday_dates_in_range(company, start, end)
    days = 0
    cur = start
    while cur <= end:
        if cur.weekday() != 6 and cur not in holidays:  # 6 = domingo
            days += 1
        cur += timedelta(days=1)
    return days


# ---------------------------------------------------------------------------
# Saldo / lecturas
# ---------------------------------------------------------------------------

def vacation_balance(employee: Employee) -> Decimal:
    total = VacationLedgerEntry.objects.filter(employee=employee).aggregate(s=Sum("days"))["s"]
    return _q2(total or Decimal("0"))


def vacation_ledger(employee: Employee, *, limit: int = 200) -> list[VacationLedgerEntry]:
    return list(employee.vacation_entries.select_related("created_by")[:limit])


def vacation_summary(company) -> list[dict]:
    """Saldo por trabajador activo de la empresa."""
    balances = {
        row["employee_id"]: row["s"]
        for row in VacationLedgerEntry.objects.filter(employee__company=company)
        .values("employee_id")
        .annotate(s=Sum("days"))
    }
    employees = Employee.objects.filter(company=company, is_active=True).order_by("first_name", "last_name")
    out: list[dict] = []
    for emp in employees:
        out.append(
            {
                "employee_id": emp.id,
                "employee_name": f"{emp.first_name} {emp.last_name}".strip(),
                "employee_code": emp.employee_code or "",
                "balance": str(_q2(balances.get(emp.id, Decimal("0")))),
            }
        )
    return out


def vacation_days_in_period(employee: Employee, period) -> Decimal:
    """Helper de lectura para nómina/asistencia: días de vacaciones APROBADAS cuyo
    rango cae dentro del período de planilla (no muta AttendanceReport)."""
    total = Decimal("0")
    qs = employee.vacation_requests.filter(
        status=VacationRequest.Status.APROBADA,
        start_date__lte=period.end_date,
        end_date__gte=period.start_date,
    )
    for req in qs:
        lo = max(req.start_date, period.start_date)
        hi = min(req.end_date, period.end_date)
        total += Decimal(_business_days(employee.company, lo, hi))
    return _q2(total)


# ---------------------------------------------------------------------------
# Acumulación (idempotente)
# ---------------------------------------------------------------------------

@transaction.atomic
def accrue_vacation_month(*, company, year: int, month: int, request=None, actor=None) -> int:
    """Acredita la acumulación del mes a cada empleado ACTIVO. Idempotente por
    (empleado, año, mes). Devuelve cuántos movimientos nuevos se crearon."""
    policy = get_or_create_vacation_policy(company)
    if not policy.is_active:
        raise VacationError("VACATION_POLICY_INACTIVE")
    last_day = calendar.monthrange(year, month)[1]
    occurred = date(year, month, last_day)

    created = 0
    employees = Employee.objects.filter(
        company=company, is_active=True, employment_status=Employee.EmploymentStatus.ACTIVO
    )
    for emp in employees:
        days = policy.days_per_month
        if policy.max_accrual_days is not None:
            room = policy.max_accrual_days - vacation_balance(emp)
            days = max(Decimal("0"), min(policy.days_per_month, room))
        _, was_created = VacationLedgerEntry.objects.get_or_create(
            employee=emp,
            entry_type=VacationLedgerEntry.EntryType.ACCRUAL,
            accrual_year=year,
            accrual_month=month,
            defaults={
                "days": _q2(days),
                "occurred_on": occurred,
                "source": f"Acumulación {month:02d}/{year}",
                "created_by": actor,
            },
        )
        if was_created:
            created += 1

    write_event(
        request=request,
        module="HR",
        event_type="HR_VACATION_ACCRUED",
        reason_code="OK",
        actor_user=actor,
        subject_type="VACATION_LEDGER",
        subject_id=str(company.id),
        metadata={"year": year, "month": month, "created": created},
    )
    return created


# ---------------------------------------------------------------------------
# Registro directo / anulación / ajuste
# ---------------------------------------------------------------------------

def _get_company_employee(company, employee_id: int) -> Employee:
    emp = Employee.objects.filter(id=employee_id, company=company).first()
    if emp is None:
        raise VacationError("EMPLOYEE_NOT_FOUND")
    return emp


@transaction.atomic
def register_vacation(
    *, company, employee_id: int, start_date: date, end_date: date, reason: str = "", request=None, actor=None
) -> VacationRequest:
    emp = _get_company_employee(company, employee_id)
    if end_date < start_date:
        raise VacationError("INVALID_DATE_RANGE")
    business = _business_days(company, start_date, end_date)
    if business <= 0:
        raise VacationError("ZERO_BUSINESS_DAYS")
    business_dec = _q2(Decimal(business))
    if business_dec > vacation_balance(emp):
        raise VacationError("HR_VACATION_INSUFFICIENT_BALANCE")
    calendar_days = (end_date - start_date).days + 1

    req = VacationRequest.objects.create(
        employee=emp,
        start_date=start_date,
        end_date=end_date,
        calendar_days=calendar_days,
        business_days=business_dec,
        status=VacationRequest.Status.APROBADA,
        reason=reason or "",
        created_by=actor,
    )
    VacationLedgerEntry.objects.create(
        employee=emp,
        entry_type=VacationLedgerEntry.EntryType.TAKEN,
        days=-business_dec,
        occurred_on=start_date,
        source=f"Vacaciones {start_date}–{end_date}",
        request=req,
        created_by=actor,
    )
    write_event(
        request=request,
        module="HR",
        event_type="HR_VACATION_REGISTERED",
        reason_code="OK",
        actor_user=actor,
        subject_type="VACATION_REQUEST",
        subject_id=str(req.id),
        metadata={
            "employee_id": emp.id,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "business_days": str(business_dec),
        },
    )
    return req


@transaction.atomic
def cancel_vacation(*, company, request_id: int, reason: str = "", request=None, actor=None) -> VacationRequest:
    req = (
        VacationRequest.objects.select_for_update()
        .filter(id=request_id, employee__company=company)
        .select_related("employee")
        .first()
    )
    if req is None:
        raise VacationError("VACATION_REQUEST_NOT_FOUND")
    if req.status == VacationRequest.Status.ANULADA:
        raise VacationError("VACATION_ALREADY_CANCELLED")

    VacationLedgerEntry.objects.create(
        employee=req.employee,
        entry_type=VacationLedgerEntry.EntryType.ADJUSTMENT,
        days=req.business_days,  # reversa positiva del TAKEN
        occurred_on=timezone.localdate(),
        source=f"Anulación de vacaciones #{req.id}",
        request=req,
        created_by=actor,
    )
    req.status = VacationRequest.Status.ANULADA
    req.cancelled_by = actor
    req.cancelled_at = timezone.now()
    req.cancel_reason = reason or ""
    req.save(update_fields=["status", "cancelled_by", "cancelled_at", "cancel_reason"])

    write_event(
        request=request,
        module="HR",
        event_type="HR_VACATION_CANCELLED",
        reason_code="OK",
        actor_user=actor,
        subject_type="VACATION_REQUEST",
        subject_id=str(req.id),
        metadata={"employee_id": req.employee_id, "restored_days": str(req.business_days)},
    )
    return req


@transaction.atomic
def adjust_balance(
    *, company, employee_id: int, days, reason: str, request=None, actor=None
) -> VacationLedgerEntry:
    emp = _get_company_employee(company, employee_id)
    days_dec = _q2(days)
    if days_dec == 0:
        raise VacationError("ADJUSTMENT_ZERO")
    if not (reason or "").strip():
        raise VacationError("ADJUSTMENT_REASON_REQUIRED")
    entry = VacationLedgerEntry.objects.create(
        employee=emp,
        entry_type=VacationLedgerEntry.EntryType.ADJUSTMENT,
        days=days_dec,
        occurred_on=timezone.localdate(),
        source=reason.strip(),
        created_by=actor,
    )
    write_event(
        request=request,
        module="HR",
        event_type="HR_VACATION_ADJUSTED",
        reason_code="OK",
        actor_user=actor,
        subject_type="VACATION_LEDGER",
        subject_id=str(emp.id),
        metadata={"employee_id": emp.id, "days": str(days_dec), "reason": reason.strip()},
    )
    return entry
