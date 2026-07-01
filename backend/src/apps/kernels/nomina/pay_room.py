"""Sala de pago — resumen consolidado por empleado (lectura, para la app del pagador).

Junta, por empleado y para un período, lo que el pagador necesita ver de un vistazo:
- En qué planilla(s) legal(es) está (CON/SIN INSS) y su neto LEGAL completo.
- El complemento de salario (si tiene).
- El desglose de retenciones de LEY (INSS / IR).
- Cuánto se le ha pagado (Σ `PayrollPayment`) y cuánto falta entregar.

PROHIBIDO: la nómina NO cobra comisariato ni préstamos personales. El Pagador SOLO entrega el
neto legal; no hay recaudación de deudas internas en este flujo. Es SOLO lectura: devuelve
estructuras planas (dict) listas para serializar/cachear.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from django.db.models import Q, Sum

from apps.modulos.iam.models import OrgUnit

from .models import (
    PayrollEntry,
    PayrollPeriod,
    PayrollSheet,
    SalaryComplementLine,
    SalaryComplementSheet,
)
from .planilla_export import print_page

Q2 = Decimal("0.01")


def _q2(value: Any) -> Decimal:
    return Decimal(str(value or "0")).quantize(Q2)


def _entry_location(sheet: PayrollSheet, company: OrgUnit, emp_branch: str) -> str:
    """Finca/sucursal donde se ubica el trabajador, en orden de autoridad:

    1) sucursal de la HOJA (planilla de una finca → todos sus trabajadores ahí),
    2) sucursal de la ASIGNACIÓN del empleado en RH (planilla company-wide: cada
       trabajador puede estar en una finca distinta — Santa Isabel, Las Morenas…),
    3) la empresa (último recurso; nunca el nombre genérico de la planilla).
    """
    if sheet.branch_id:
        sheet_branch = sheet.branch
        if sheet_branch is not None:
            return sheet_branch.name or company.name
    if emp_branch:
        return emp_branch
    return company.name or str(company)


def _employee_key(*, employee_id: Optional[int], cedula: str, worker_code: str = "") -> str:
    """Clave de agrupación: el empleado del expediente, o el carnet/cédula si es línea manual.

    El carnet (ID único de persona del holding) agrupa a quien NO tiene cédula entre sus hojas.
    """
    if employee_id:
        return f"emp:{employee_id}"
    wc = (worker_code or "").strip().upper()
    if wc:
        return f"wc:{wc}"
    ced = (cedula or "").strip().upper()
    return f"ced:{ced}" if ced else ""


def _empty_totales() -> dict[str, Any]:
    return {
        "neto_total_a_entregar": Decimal("0.00"),
        "pagado": Decimal("0.00"),
        "pendiente": Decimal("0.00"),
    }


def _new_row(
    *, key: str, employee_id: Optional[int], employee, inss_number: str, cedula: str, full_name: str, cargo: str,
    worker_code: str = "",
) -> dict[str, Any]:
    return {
        "employee_key": key,
        "employee_id": employee_id,
        "employee_code": getattr(employee, "employee_code", "") or "",
        "inss_number": inss_number or (getattr(employee, "inss_number", "") or ""),
        "cedula": cedula or (getattr(employee, "cedula", "") or ""),
        # Carnet (ID único de persona del holding) — clave del cobro entre empresas sin cédula.
        "worker_code": worker_code or "",
        "full_name": full_name,
        "cargo": cargo or "",
        "ubicacion": "",  # planilla/finca donde está (de la 1ª hoja), para la tarjeta
        "sheets": [],
        "complement": None,
        "totales": _empty_totales(),
    }


def build_pay_summary(
    *, period: PayrollPeriod, company: OrgUnit, branch: Optional[OrgUnit] = None
) -> list[dict[str, Any]]:
    """Resumen consolidado por empleado del período (planillas legales + complemento)."""
    sheets = PayrollSheet.objects.filter(period=period)
    if branch is not None:
        # Una planilla sin sucursal (branch=None) es de TODA la empresa → debe verse en
        # cualquier sucursal; solo se excluyen las planillas de OTRA sucursal.
        sheets = sheets.filter(Q(branch=branch) | Q(branch__isnull=True))
    sheet_ids = list(sheets.values_list("id", flat=True))

    entries = (
        PayrollEntry.objects.filter(sheet_id__in=sheet_ids)
        .select_related("employee", "sheet", "sheet__branch")
        .order_by("full_name")
    )

    # Posición impresa (No.) de cada entrada: la planilla legal numera por `id` dentro de la
    # hoja (ver planilla_export.build_planilla_matrix). Reproducimos ese orden 1-indexado por
    # hoja para decirle al pagador "Hoja X, No. Y" del papel.
    print_no_by_entry: dict[int, int] = {}
    _counter: dict[int, int] = {}
    for eid, sid in (
        PayrollEntry.objects.filter(sheet_id__in=sheet_ids)
        .order_by("sheet_id", "id")
        .values_list("id", "sheet_id")
    ):
        _counter[sid] = _counter.get(sid, 0) + 1
        print_no_by_entry[eid] = _counter[sid]

    # Finca/sucursal de cada empleado por su asignación ACTIVA de RH (para planillas
    # company-wide donde cada trabajador está en una finca distinta). Edge nomina→hr ya
    # existe (asistencia_dia), no agrega dependencia nueva.
    emp_branch_name: dict[int, str] = {}
    emp_ids = [e.employee_id for e in entries if e.employee_id]
    if emp_ids:
        from apps.modulos.hr.models import EmploymentAssignment

        for emp_id, bname in (
            EmploymentAssignment.objects.filter(
                employee_id__in=set(emp_ids), is_active=True, branch__isnull=False
            )
            .order_by("employee_id", "-started_at")
            .values_list("employee_id", "branch__name")
        ):
            emp_branch_name.setdefault(emp_id, bname)  # la más reciente por empleado

    # Pagos ya registrados por entry (Σ PayrollPayment).
    paid_by_entry: dict[int, Decimal] = {}
    for payment_row in (
        PayrollEntry.objects.filter(sheet_id__in=sheet_ids)
        .values("id")
        .annotate(s=Sum("payments__amount"))
    ):
        paid_by_entry[payment_row["id"]] = _q2(payment_row["s"])

    rows: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for entry in entries:
        key = _employee_key(employee_id=entry.employee_id, cedula=entry.cedula, worker_code=entry.worker_code)
        if not key:
            key = f"entry:{entry.id}"  # línea sin empleado ni cédula ni carnet: fila propia
        row: dict[str, Any] | None = rows.get(key)
        if row is None:
            row = _new_row(
                key=key,
                employee_id=entry.employee_id,
                employee=entry.employee,
                inss_number=entry.inss_number,
                cedula=entry.cedula,
                worker_code=entry.worker_code,
                full_name=entry.full_name,
                cargo=entry.cargo,
            )
            rows[key] = row
            order.append(key)

        already_paid = paid_by_entry.get(entry.id, Decimal("0.00"))
        net = _q2(entry.net_to_pay)
        remaining = _q2(net - already_paid)
        deductions = {
            "inss_laboral": _q2(entry.inss_laboral),
            "ir_amount": _q2(entry.ir_amount),
            "loan_payment": _q2(entry.loan_payment),
            "store_credit_deduction": _q2(entry.store_credit_deduction),
            "advance_deduction": _q2(entry.advance_deduction),
            "food_deduction": _q2(entry.food_deduction),
            "other_deductions": _q2(entry.other_deductions),
            "total_deductions": _q2(entry.total_deductions),
        }
        emp_branch = emp_branch_name.get(entry.employee_id, "") if entry.employee_id is not None else ""
        location = _entry_location(entry.sheet, company, emp_branch)
        print_no = print_no_by_entry.get(entry.id, 0)
        if not row["ubicacion"]:
            row["ubicacion"] = location
        row["sheets"].append(
            {
                "sheet_id": entry.sheet_id,
                "sheet_name": entry.sheet.sheet_name,
                "has_inss": entry.has_inss,
                "status": entry.sheet.status,
                "entry_id": entry.id,
                "location": location,
                "print_no": print_no,  # No. del trabajador en la planilla impresa
                "print_page": print_page(print_no),  # hoja del papel donde cae
                "total_devengado": _q2(entry.total_devengado),
                "net_to_pay": net,
                "already_paid": already_paid,
                "remaining": remaining,
                "paid": remaining <= 0 and net > 0,
                "deductions": deductions,
            }
        )

    # Complemento de salario del período (por empleado/cédula).
    comp_sheets = SalaryComplementSheet.objects.filter(period=period)
    if branch is not None:
        comp_sheets = comp_sheets.filter(Q(branch=branch) | Q(branch__isnull=True))
    comp_sheet_ids = list(comp_sheets.values_list("id", flat=True))
    for line in (
        SalaryComplementLine.objects.filter(sheet_id__in=comp_sheet_ids).select_related("employee")
    ):
        key = _employee_key(employee_id=line.employee_id, cedula=line.cedula)
        comp_row = rows.get(key) if key else None
        if comp_row is None:
            # Empleado solo en el complemento (sin planilla legal): fila propia.
            key = key or f"compline:{line.id}"
            comp_row = _new_row(
                key=key,
                employee_id=line.employee_id,
                employee=line.employee,
                inss_number="",
                cedula=line.cedula,
                full_name=line.full_name,
                cargo=line.cargo,
            )
            rows[key] = comp_row
            order.append(key)
        comp_row["complement"] = {
            "complement_sheet_id": line.sheet_id,
            "line_id": line.id,
            "amount_nio": _q2(line.amount_nio),
            "received": line.received_at is not None,
        }

    # Totales por empleado.
    result: list[dict[str, Any]] = []
    for key in order:
        row = rows[key]
        legal_neto = _q2(sum((s["net_to_pay"] for s in row["sheets"]), Decimal("0.00")))
        pagado_legal = _q2(sum((s["already_paid"] for s in row["sheets"]), Decimal("0.00")))
        comp = row["complement"]
        comp_monto = comp["amount_nio"] if comp else Decimal("0.00")
        comp_pagado = comp_monto if (comp and comp["received"]) else Decimal("0.00")

        neto_total = _q2(legal_neto + comp_monto)
        pagado_total = _q2(pagado_legal + comp_pagado)
        row["totales"] = {
            "neto_total_a_entregar": neto_total,
            "pagado": pagado_total,
            "pendiente": _q2(neto_total - pagado_total),
        }
        row["planillas"] = sorted({("CON INSS" if s["has_inss"] else "SIN INSS") for s in row["sheets"]})
        result.append(row)

    return result
