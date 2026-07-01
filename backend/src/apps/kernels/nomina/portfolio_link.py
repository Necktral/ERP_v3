"""Puente nómina → portfolio: abono de descuentos de préstamo/adelanto de planilla.

Registra el `PayrollLoanDeduction` (link auditado entre la línea de planilla y el crédito
del empleado en `portfolio`) y aplica el abono al saldo del crédito (best-effort: nunca
bloquea la nómina). El abono usa `portfolio.apply_payroll_abono` (sin payment intent).
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.modulos.audit.writer import write_event

from .models import PayrollLoanDeduction

logger = logging.getLogger(__name__)


def _apply_to_portfolio(*, deduction: PayrollLoanDeduction, amount: Decimal, actor, abono_date):
    """Aplica el abono al crédito/CxC del empleado en portfolio (best-effort)."""
    try:
        from apps.kernels.portfolio.models import Credit, Receivable
        from apps.kernels.portfolio.services import PortfolioDomainError, apply_payroll_abono
    except ImportError:
        return None

    model = Receivable if deduction.credit_type == "RECEIVABLE" else Credit
    obligation = model.objects.filter(id=deduction.credit_id).first()
    if obligation is None:
        return None
    try:
        return apply_payroll_abono(
            obligation=obligation,
            amount=amount,
            abono_date=abono_date,
            created_by=actor,
            reference=f"PLANILLA:deduction:{deduction.id}",
        )
    except (PortfolioDomainError, ValueError, RuntimeError, TypeError):
        return None


def register_payroll_loan_deduction(
    *, request, actor, entry, credit_id, amount, credit_type: str = "CREDIT", abono_date=None,
    source: str = "",
):
    """Registra el descuento de préstamo de una línea y abona al crédito en portfolio (best-effort).

    `source` etiqueta el origen del abono en `deduction.notes` (p. ej. "COPA" para el cobro
    negociado del Cobrador-Pagador). La rectificación lo usa para reversar SOLO los abonos del
    cobro y no los del auto-armado de la planilla. Backward-compatible (default "").

    Devuelve (PayrollLoanDeduction, monto_abonado | None).
    """
    amount = Decimal(str(amount))
    period = entry.sheet.period
    with transaction.atomic():
        deduction = PayrollLoanDeduction.objects.create(
            entry=entry,
            company=period.company,
            credit_id=int(credit_id),
            credit_type=(credit_type or "CREDIT").upper(),
            amount_deducted=amount,
            notes=(source or "").strip()[:255],
        )
        write_event(
            request=request,
            module="NOMINA",
            event_type="NOMINA_LOAN_DEDUCTION_RECORDED",
            reason_code="NOMINA_OK",
            actor_user=actor,
            subject_type="PAYROLL_LOAN_DEDUCTION",
            subject_id=str(deduction.id),
            metadata={
                "entry_id": entry.id,
                "credit_id": int(credit_id),
                "credit_type": deduction.credit_type,
                "amount": str(amount),
            },
        )

    # Best-effort, fuera de la txn del registro: la nómina nunca se bloquea por portfolio.
    applied = _apply_to_portfolio(
        deduction=deduction, amount=amount, actor=actor, abono_date=abono_date or timezone.localdate()
    )

    # NM-06: registrar lo realmente abonado. Si falla (applied None) o queda corto, la
    # deducción queda con `abono_applied` < `amount_deducted` → abono pendiente, visible
    # para conciliación (antes el trabajador quedaba descontado sin abonar el crédito y
    # el desfase era silencioso).
    deduction.abono_applied = applied if applied is not None else Decimal("0.00")
    deduction.save(update_fields=["abono_applied"])
    if deduction.abono_applied < amount:
        logger.warning(
            "payroll_loan_abono_pending",
            extra={
                "deduction_id": deduction.id,
                "credit_id": int(credit_id),
                "credit_type": deduction.credit_type,
                "amount_deducted": str(amount),
                "abono_applied": str(deduction.abono_applied),
            },
        )
    return deduction, applied


def reverse_payroll_loan_deduction(*, request, actor, deduction: PayrollLoanDeduction, reason: str = ""):
    """Reversa un abono de planilla: devuelve el saldo al crédito/CxC en portfolio y marca la deducción.

    Lo usa la rectificación del Cobrador-Pagador cuando el pagador se equivoca de monto. Llama la
    reversa GLOBAL del kernel portfolio (`reverse_payroll_abono`, válida para cualquier obligación) por
    lo realmente abonado (`abono_applied`), pone `abono_applied = 0` y deja la deducción marcada como
    REVERSADA (no se vuelve a reversar). Devuelve el monto reversado.
    """
    reversed_amount = Decimal("0.00")
    applied = deduction.abono_applied or Decimal("0.00")
    if applied > 0:
        try:
            from apps.kernels.portfolio.models import Credit, Receivable
            from apps.kernels.portfolio.services import reverse_payroll_abono
        except ImportError:
            Credit = Receivable = None  # type: ignore[assignment,misc]
        if Credit is not None:
            model = Receivable if deduction.credit_type == "RECEIVABLE" else Credit
            obligation = model.objects.filter(id=deduction.credit_id).first()
            if obligation is not None:
                reversed_amount = reverse_payroll_abono(
                    obligation=obligation,
                    amount=applied,
                    created_by=actor,
                    reference=f"PLANILLA:reverse:deduction:{deduction.id}",
                )

    with transaction.atomic():
        deduction.abono_applied = Decimal("0.00")
        nota = (f"REVERSADO: {reason}" if reason else "REVERSADO").strip()[:255]
        deduction.notes = nota
        deduction.save(update_fields=["abono_applied", "notes"])
        write_event(
            request=request,
            module="NOMINA",
            event_type="NOMINA_LOAN_DEDUCTION_REVERSED",
            reason_code="NOMINA_OK",
            actor_user=actor,
            subject_type="PAYROLL_LOAN_DEDUCTION",
            subject_id=str(deduction.id),
            metadata={
                "entry_id": deduction.entry_id,
                "credit_id": deduction.credit_id,
                "credit_type": deduction.credit_type,
                "amount_reversed": str(reversed_amount),
                "reason": reason or "",
            },
        )
    return reversed_amount
