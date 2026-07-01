"""Lazo de cobro del empleado: comisariato → planilla (sala de pago).

El comisariato manda sus cuentas por cobrar a la sala de pago: para cada empleado de
la planilla con CxC abierta en el comisariato, se fija la columna existente
`PayrollEntry.store_credit_deduction` y se **abona** la CxC por el riel probado
`register_payroll_loan_deduction` (nómina → portfolio). El cruce entre empresas usa la
**cédula** como clave natural (la planilla está en la finca; la CxC está en el
comisariato, que es OTRA empresa → el empleado es un Party distinto por empresa).

Dirección de dependencia: modulo (comisariato) → kernel (nomina/portfolio), la preferida.

FASE 2 (pendiente, NO en v1): el reclass intercompany finca→comisariato (cobro-en-nombre-de).
Como toda empresa tiene RUC propio, cuando la finca retiene de la planilla efectivo que es
del comisariato, debe nacer una CxP-IC de la finca al comisariato y reclasificarse la CxC del
empleado a CxC-finca en el comisariato. Eso es un primitivo NUEVO de tesorería entre empresas
(cobro-en-nombre-de), distinto de `record_intercompany_charge` (que postea ingreso/gasto, no
aplica a un cobro por cuenta). v1 abona la CxC directo y difiere ese asiento.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from django.db import transaction

from apps.kernels.nomina.models import PayrollEntry, PayrollSheet, SheetStatus
from apps.kernels.nomina.portfolio_link import register_payroll_loan_deduction
from apps.kernels.portfolio.models import Receivable
from apps.modulos.audit.writer import write_event
from apps.modulos.iam.models import OrgUnit

from .models import CustomerCreditAccount, CustomerSegment
from .services import TERMINAL_STATUSES, ComisariatoError, _q2

EDITABLE_SHEET_STATUSES = {SheetStatus.DRAFT, SheetStatus.SUBMITTED}


def _open_receivables(*, company: OrgUnit, party) -> list[Receivable]:
    return list(
        Receivable.objects.filter(company=company, party=party)
        .exclude(status__in=TERMINAL_STATUSES)
        .order_by("issue_date", "id")
    )


def _has_active_cxc_relationship(*, finca: OrgUnit, comisariato: OrgUnit) -> bool:
    """¿Existe la relación de empresas CXC declarada finca↔comisariato? (multi-empresa).

    El cobro cross-company (la finca cobra por cuenta del comisariato, otra empresa con RUC
    propio) SOLO procede si el vínculo está declarado en `org.IntercompanyRelationship` (tipo
    CXC, activo). Es el "habilitador" del cruce — sin él, no se descuenta la deuda del comisariato.
    """
    from django.db.models import Q

    from apps.modulos.org.models import IntercompanyRelationship

    if finca.id == comisariato.id:
        return False
    return (
        IntercompanyRelationship.objects
        .filter(is_active=True, relationship_type=IntercompanyRelationship.RelationshipType.CXC)
        .filter(Q(company_a=finca, company_b=comisariato) | Q(company_a=comisariato, company_b=finca))
        .exists()
    )


def find_employee_account(
    *, collecting_company: OrgUnit, worker_code: str = "", cedula: str = ""
) -> Optional[CustomerCreditAccount]:
    """Cuenta EMPLOYEE del comisariato del trabajador, cuya finca cobradora es `collecting_company`.

    El cruce es por **carnet** (`worker_code`, ID único de persona del holding) y, como respaldo,
    por **cédula** (no todos la tienen). La planilla vive en la finca; la CxC en el comisariato (otra
    empresa) → el match SOLO procede si existe la relación de empresas CXC declarada finca↔comisariato.
    """
    wc = (worker_code or "").strip().upper()
    ced = (cedula or "").strip().upper()
    if not wc and not ced:
        return None
    accounts = list(
        CustomerCreditAccount.objects
        .filter(segment=CustomerSegment.EMPLOYEE, is_active=True, collecting_company=collecting_company)
        .select_related("party", "company")
    )

    def _pick(predicate):
        for a in accounts:
            if predicate(a.party):
                # Multi-empresa: el cruce cross-company exige el vínculo declarado.
                if not _has_active_cxc_relationship(finca=collecting_company, comisariato=a.company):
                    return None
                return a
        return None

    # Carnet primero (clave del holding); cédula como respaldo.
    if wc:
        hit = _pick(lambda p: bool(p.worker_code) and p.worker_code.strip().upper() == wc)
        if hit is not None:
            return hit
    if ced:
        return _pick(lambda p: bool(p.national_id) and p.national_id.strip().upper() == ced)
    return None


def employee_comisariato_balance(
    *, collecting_company: OrgUnit, worker_code: str = "", cedula: str = ""
) -> tuple[Decimal, Optional[CustomerCreditAccount]]:
    """Saldo total (Σ CxC abierta) que el trabajador debe al comisariato, y su cuenta (por carnet/cédula)."""
    account = find_employee_account(collecting_company=collecting_company, worker_code=worker_code, cedula=cedula)
    if account is None:
        return _q2(Decimal("0.00")), None
    recs = _open_receivables(company=account.company, party=account.party)
    return _q2(sum((r.outstanding_amount for r in recs), Decimal("0.00"))), account


def apply_amount_to_comisariato(
    *, request, actor, entry: PayrollEntry, account: CustomerCreditAccount, amount: Decimal,
    source: str = "",
) -> Decimal:
    """Abona un MONTO (parcial, negociado) a las CxC del trabajador en el comisariato, FIFO.

    A diferencia de `apply_store_credit_deductions` (que toma la deuda completa al armar la
    planilla), acá el pagador decide cuánto abonar al PAGAR. Devuelve el total efectivamente abonado.
    `source` etiqueta el abono (p. ej. "COPA") para que la rectificación lo reverse selectivamente.
    """
    remaining = _q2(amount)
    applied_total = Decimal("0.00")
    for rec in _open_receivables(company=account.company, party=account.party):
        if remaining <= 0:
            break
        amt = _q2(min(rec.outstanding_amount, remaining))
        if amt <= 0:
            continue
        register_payroll_loan_deduction(
            request=request, actor=actor, entry=entry,
            credit_id=rec.id, amount=amt, credit_type="RECEIVABLE", source=source,
        )
        applied_total += amt
        remaining -= amt
    return _q2(applied_total)


def apply_store_credit_deductions(
    *,
    request,
    actor,
    sheet: PayrollSheet,
    comisariato_company: OrgUnit,
    per_period_cap: Optional[Decimal] = None,
) -> dict[str, Any]:
    """Aplica el crédito del comisariato a la planilla (descuento + abono de CxC).

    Para cada `PayrollEntry` cuyo empleado (por cédula) tenga cuenta EMPLOYEE con CxC
    abierta en el comisariato: fija `store_credit_deduction = min(saldo, neto disponible,
    tope)`, recomputa totales y abona las CxC (FIFO). Best-effort por entrada: una falla no
    aborta el resto. Idempotente: omite entradas que ya tienen `store_credit_deduction > 0`.
    """
    if sheet.status not in EDITABLE_SHEET_STATUSES:
        raise ComisariatoError("COMISARIATO_SHEET_NOT_EDITABLE")
    cap = _q2(per_period_cap) if per_period_cap is not None else None

    accounts = list(
        CustomerCreditAccount.objects
        .filter(company=comisariato_company, segment=CustomerSegment.EMPLOYEE, is_active=True)
        .select_related("party")
    )
    by_worker: dict[str, CustomerCreditAccount] = {
        a.party.worker_code.strip().upper(): a for a in accounts if a.party.worker_code
    }
    by_cedula: dict[str, CustomerCreditAccount] = {
        a.party.national_id.strip().upper(): a for a in accounts if a.party.national_id
    }

    results: list[dict[str, Any]] = []
    for entry in PayrollEntry.objects.filter(sheet=sheet):
        wc = (entry.worker_code or "").strip().upper()
        ced = (entry.cedula or "").strip().upper()
        if not wc and not ced:
            continue
        # Carnet primero (clave del holding); cédula como respaldo.
        account = (by_worker.get(wc) if wc else None) or (by_cedula.get(ced) if ced else None)
        if account is None:
            continue
        if entry.store_credit_deduction and entry.store_credit_deduction > 0:
            results.append({"entry_id": entry.id, "status": "SKIPPED_ALREADY"})
            continue

        open_recs = _open_receivables(company=comisariato_company, party=account.party)
        outstanding = _q2(sum((r.outstanding_amount for r in open_recs), Decimal("0.00")))
        if outstanding <= 0:
            continue

        other_ded = (
            entry.inss_laboral + entry.ir_amount + entry.loan_payment
            + entry.food_deduction + entry.advance_deduction + entry.other_deductions
        )
        net_before = _q2(entry.total_devengado - other_ded)
        due = min(outstanding, net_before if net_before > 0 else Decimal("0.00"))
        if cap is not None:
            due = min(due, cap)
        due = _q2(due)
        if due <= 0:
            results.append({"entry_id": entry.id, "status": "SKIPPED_NO_NET"})
            continue

        try:
            with transaction.atomic():
                entry.store_credit_deduction = due
                entry.total_deductions = _q2(other_ded + due)
                entry.net_to_pay = _q2(entry.total_devengado - entry.total_deductions)
                entry.save(update_fields=["store_credit_deduction", "total_deductions", "net_to_pay"])

                remaining = due
                abonos: list[dict[str, str]] = []
                for rec in open_recs:
                    if remaining <= 0:
                        break
                    amt = _q2(min(rec.outstanding_amount, remaining))
                    if amt <= 0:
                        continue
                    register_payroll_loan_deduction(
                        request=request, actor=actor, entry=entry,
                        credit_id=rec.id, amount=amt, credit_type="RECEIVABLE",
                    )
                    abonos.append({"receivable_id": str(rec.obligation_id), "amount": str(amt)})
                    remaining -= amt

                write_event(
                    request=request, module="COMISARIATO",
                    event_type="COMISARIATO_STORE_CREDIT_DEDUCTED", reason_code="COMISARIATO_OK",
                    actor_user=actor, subject_type="COMISARIATO_ACCOUNT", subject_id=str(account.id),
                    metadata={
                        "sheet_id": sheet.id, "entry_id": entry.id, "cedula": ced,
                        "amount": str(due), "abonos": abonos,
                    },
                )
            results.append(
                {"entry_id": entry.id, "account_id": account.id, "amount": str(due), "status": "APPLIED"}
            )
        except Exception as exc:  # noqa: BLE001 — best-effort por entrada
            results.append({"entry_id": entry.id, "status": "ERROR", "error": str(exc)})

    applied = [r for r in results if r["status"] == "APPLIED"]
    total_applied = _q2(sum((Decimal(r["amount"]) for r in applied), Decimal("0.00")))
    return {
        "sheet_id": sheet.id,
        "applied_count": len(applied),
        "total_applied": str(total_applied),
        "results": results,
    }
