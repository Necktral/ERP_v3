"""Servicios de la planilla de complemento de salario (convenio personal, bruto en recibo).

Invariante: el complemento es un pago bruto pactado, **net = gross** (no hay INSS/IR ni
deducciones), totalmente separado de la planilla legal — NUNCA crea `PayrollEntry` ni toca
la base de INSS/IR. El monto base vive en el perfil del trabajador
(`hr.Employee.salary_complement_base_nio`) y es ajustable por línea (por periodo) mientras la
hoja esté en DRAFT.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.modulos.audit.writer import write_event
from apps.modulos.hr.models import Employee

from .models import SalaryComplementLine, SalaryComplementSheet, SheetStatus


def _full_name(emp: Employee) -> str:
    return f"{emp.first_name} {emp.last_name}".strip()


@transaction.atomic
def create_complement_sheet(*, request, actor, period, branch=None, name: str = "") -> SalaryComplementSheet:
    """Crea la hoja de complemento del período y la siembra con la totalidad de trabajadores
    activos de la empresa que tienen complemento habilitado, con el monto base del perfil
    (ajustable por línea después). El monto base = `salary_complement_base_nio`."""
    sheet = SalaryComplementSheet.objects.create(
        period=period,
        branch=branch,
        name=name or f"Complemento {period.year}/{period.month:02d} {period.period_type}",
        status=SheetStatus.DRAFT,
        created_by=actor,
    )
    enabled = (
        Employee.objects.filter(
            company=period.company, salary_complement_enabled=True, is_active=True,
        )
        .order_by("first_name", "last_name")
    )
    lines = [
        SalaryComplementLine(
            sheet=sheet,
            employee=emp,
            full_name=_full_name(emp),
            cedula=emp.cedula or "",
            amount_nio=emp.salary_complement_base_nio or Decimal("0.00"),
        )
        for emp in enabled
    ]
    SalaryComplementLine.objects.bulk_create(lines)

    write_event(
        request=request,
        module="NOMINA",
        event_type="NOMINA_COMPLEMENT_SHEET_CREATED",
        reason_code="NOMINA_OK",
        actor_user=actor,
        subject_type="NOMINA_COMPLEMENT",
        subject_id=str(sheet.id),
        metadata={"period_id": period.id, "lines": len(lines)},
    )
    return sheet


def set_complement_line_amount(*, request, actor, line: SalaryComplementLine, amount: Decimal) -> SalaryComplementLine:
    """Override del monto por periodo (solo mientras la hoja esté en DRAFT)."""
    if line.sheet.status != SheetStatus.DRAFT:
        raise ValueError("Solo se puede editar el monto en una hoja en borrador.")
    amount = Decimal(amount)
    if amount < 0:
        raise ValueError("El monto del complemento no puede ser negativo.")
    line.amount_nio = amount.quantize(Decimal("0.01"))
    line.save(update_fields=["amount_nio", "updated_at"])
    return line


def submit_complement_sheet(*, request, actor, sheet: SalaryComplementSheet) -> SalaryComplementSheet:
    """Maker: envía la hoja a aprobación."""
    if sheet.status != SheetStatus.DRAFT:
        raise ValueError(f"No se puede enviar desde estado: {sheet.status}")
    sheet.status = SheetStatus.SUBMITTED
    sheet.submitted_by = actor
    sheet.submitted_at = timezone.now()
    sheet.save(update_fields=["status", "submitted_by", "submitted_at", "updated_at"])
    write_event(
        request=request, module="NOMINA", event_type="NOMINA_COMPLEMENT_SHEET_SUBMITTED",
        reason_code="NOMINA_OK", actor_user=actor, subject_type="NOMINA_COMPLEMENT",
        subject_id=str(sheet.id), metadata={"period_id": sheet.period_id},
    )
    return sheet


def approve_complement_sheet(*, request, actor, sheet: SalaryComplementSheet) -> SalaryComplementSheet:
    """Checker (SoD): aprueba la hoja. Quien la armó/envió NO puede aprobarla."""
    if sheet.status not in (SheetStatus.SUBMITTED, SheetStatus.REVIEWED):
        raise ValueError(f"No se puede aprobar desde estado: {sheet.status}")
    if sheet.submitted_by_id and actor is not None and sheet.submitted_by_id == getattr(actor, "id", None):
        raise ValueError("Quien envía el complemento no puede aprobarlo (segregación de funciones).")
    sheet.status = SheetStatus.APPROVED
    sheet.approved_by = actor
    sheet.approved_at = timezone.now()
    sheet.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    write_event(
        request=request, module="NOMINA", event_type="NOMINA_COMPLEMENT_SHEET_APPROVED",
        reason_code="NOMINA_OK", actor_user=actor, subject_type="NOMINA_COMPLEMENT",
        subject_id=str(sheet.id), metadata={"period_id": sheet.period_id},
    )
    return sheet


def mark_complement_received(*, request, actor, line: SalaryComplementLine, note: str = "") -> SalaryComplementLine:
    """Registra el recibo firmado (pago en mano) de una línea de complemento aprobado."""
    if line.sheet.status != SheetStatus.APPROVED:
        raise ValueError("Solo se registra el recibo de un complemento aprobado.")
    line.received_at = timezone.now()
    line.received_by = actor
    if note:
        line.note = note[:255]
    line.save(update_fields=["received_at", "received_by", "note", "updated_at"])
    write_event(
        request=request, module="NOMINA", event_type="NOMINA_COMPLEMENT_RECEIVED",
        reason_code="NOMINA_OK", actor_user=actor, subject_type="NOMINA_COMPLEMENT",
        subject_id=str(line.sheet_id), metadata={"line_id": line.id, "amount": str(line.amount_nio)},
    )
    return line


def complement_sheet_payload(sheet: SalaryComplementSheet) -> dict:
    """Payload con líneas y subtotal (devengado = neto)."""
    lines = list(sheet.lines.order_by("full_name", "id"))
    subtotal = sum((ln.amount_nio for ln in lines), Decimal("0.00"))
    return {
        "id": sheet.id,
        "period_id": sheet.period_id,
        "branch_id": sheet.branch_id,
        "name": sheet.name,
        "status": sheet.status,
        "subtotal_nio": str(subtotal),
        "lines": [
            {
                "id": ln.id,
                "employee_id": ln.employee_id,
                "full_name": ln.full_name,
                "cedula": ln.cedula,
                "cargo": ln.cargo,
                "devengado_nio": str(ln.amount_nio),
                "neto_nio": str(ln.amount_nio),  # net = gross
                "received_at": ln.received_at,
            }
            for ln in lines
        ],
        "created_at": sheet.created_at,
    }
