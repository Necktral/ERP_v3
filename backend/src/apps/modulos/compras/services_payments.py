"""Pago de CxP a proveedores desde caja (Ola D): espejo de ventas.collect_receivable.

Compone los kernels existentes SIN duplicar lógica:
- payments.create_payment_intent / capture_payment_intent — el pago queda trazado
  (provider CASHIER, metadata direction=OUTBOUND) y conciliable contra banco.
- payments.post_cash_movement — si es efectivo, el egreso sale de la sesión ABIERTA.
- portfolio.allocate_payment_to_obligation — aplica el pago a la CxP (PARTIAL/PAID).

Guard de reentrada: como es dinero que SALE, una re-llamada con la misma
idempotency_key devuelve el resultado existente sin volver a aplicar.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from apps.kernels.payments.models import CashMovement, CashSession, PaymentIntent
from apps.kernels.payments.services import (
    capture_payment_intent,
    create_payment_intent,
    post_cash_movement,
)
from apps.kernels.portfolio.models import (
    AllocationStatus,
    ObligationStatus,
    Payable,
    PaymentAllocation,
)
from apps.kernels.portfolio.services import allocate_payment_to_obligation
from apps.modulos.audit.service_audit import emit_service_event
from apps.modulos.common.tender import TenderPaymentMethod

from .services import ProcurementError, ProcurementNotFoundError

_CENT = Decimal("0.01")

# Métodos aceptados para pagar a un proveedor en mostrador/caja.
PAYABLE_PAY_METHODS = frozenset(
    {
        TenderPaymentMethod.CASH,
        TenderPaymentMethod.TRANSFER,
        TenderPaymentMethod.CARD,
        TenderPaymentMethod.CHECK,
    }
)

_CLOSED_STATUSES = (
    ObligationStatus.PAID,
    ObligationStatus.WRITTEN_OFF,
    ObligationStatus.CANCELLED,
)


def _q2(x) -> Decimal:
    return Decimal(x).quantize(_CENT)


def _open_cash_session(*, company, branch, actor) -> CashSession:
    """Sesión de caja abierta del cajero (o la única abierta de la sucursal)."""
    own = (
        CashSession.objects.filter(
            company=company, branch=branch, status=CashSession.Status.OPEN, opened_by=actor
        )
        .order_by("-id")
        .first()
    )
    if own is not None:
        return own
    opened = list(
        CashSession.objects.filter(company=company, branch=branch, status=CashSession.Status.OPEN)[:2]
    )
    if len(opened) == 1:
        return opened[0]
    raise ProcurementError("PROCUREMENT_CASH_SESSION_REQUIRED")


def _payment_result(*, payable: Payable, allocation_id: str, paid: Decimal, cash_movement_id) -> dict[str, Any]:
    return {
        "payable_id": str(payable.obligation_id),
        "allocation_id": str(allocation_id),
        "paid": str(_q2(paid)),
        "outstanding_after": str(payable.outstanding_amount),
        "status_after": payable.status,
        "cash_movement_id": cash_movement_id,
    }


def _replay_result(*, company, payable: Payable, intent: PaymentIntent, cash_key: str) -> dict[str, Any] | None:
    """Reentrada idempotente: el intent de esta key ya fue capturado y aplicado a esta CxP."""
    if intent.status != PaymentIntent.Status.CAPTURED:
        return None
    allocation = (
        PaymentAllocation.objects.filter(
            payment_intent=intent,
            obligation_content_type=ContentType.objects.get_for_model(Payable),
            obligation_object_id=payable.id,
            status=AllocationStatus.APPLIED,
        )
        .order_by("-id")
        .first()
    )
    if allocation is None:
        return None
    movement = (
        CashMovement.objects.filter(session__company=company, idempotency_key=cash_key)
        .order_by("-id")
        .first()
    )
    return _payment_result(
        payable=payable,
        allocation_id=str(allocation.allocation_id),
        paid=Decimal(allocation.allocated_amount),
        cash_movement_id=movement.id if movement else None,
    )


def pay_payable(
    *,
    request,
    actor,
    payable_id: int,
    amount: Decimal,
    method: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Pago de una CxP en caja: intent capturado → aplicación en cartera → egreso de la sesión.

    A diferencia del cobro de CxC, no hay documento que reflejar: PurchaseDocument
    no lleva payment_status; el saldo vivo de la deuda es la CxP misma.
    """
    if not idempotency_key:
        raise ProcurementError("PROCUREMENT_IDEMPOTENCY_REQUIRED")
    if method not in PAYABLE_PAY_METHODS:
        raise ProcurementError("PROCUREMENT_INVALID_PAYMENT_METHOD")

    company = request.company
    branch = request.branch
    amount = _q2(Decimal(str(amount)))
    if amount <= 0:
        raise ProcurementError("PROCUREMENT_AMOUNT_INVALID")

    intent_key = f"pago-cxp:{company.id}:{idempotency_key}"
    cash_key = f"pago-cash:{company.id}:{idempotency_key}"

    with transaction.atomic():
        payable = (
            Payable.objects.select_for_update()
            .filter(id=payable_id, company=company)
            .first()
        )
        if payable is None:
            raise ProcurementNotFoundError("PROCUREMENT_PAYABLE_NOT_FOUND")

        prior = (
            PaymentIntent.objects.filter(company=company, idempotency_key=intent_key)
            .order_by("-id")
            .first()
        )
        if prior is not None:
            replay = _replay_result(company=company, payable=payable, intent=prior, cash_key=cash_key)
            if replay is not None:
                return replay

        if payable.status in _CLOSED_STATUSES:
            raise ProcurementError("PROCUREMENT_PAYABLE_NOT_OPEN")
        if amount > _q2(Decimal(payable.outstanding_amount)):
            raise ProcurementError("PROCUREMENT_AMOUNT_EXCEEDS_OUTSTANDING")

        session = (
            _open_cash_session(company=company, branch=branch, actor=actor)
            if method == TenderPaymentMethod.CASH
            else None
        )

        intent, _created = create_payment_intent(
            request=request, actor=actor, amount=amount, currency=payable.currency,
            idempotency_key=intent_key,
            external_ref=f"payable:{payable.obligation_id}", provider="CASHIER",
            payment_method=method,
        )
        intent = capture_payment_intent(
            request=request, actor=actor, payment_id=intent.payment_id,
            provider_txn_id=f"pago-cxp:{idempotency_key}",
            metadata={
                "payable_id": str(payable.obligation_id),
                "direction": "OUTBOUND",
                "channel": "caja",
            },
        )

        allocation = allocate_payment_to_obligation(
            payment_intent=intent,
            obligation=payable,
            allocated_amount=amount,
            allocation_date=timezone.localdate(),
            created_by=actor,
        )

        cash_movement_id = None
        if session is not None:
            movement = post_cash_movement(
                request=request, actor=actor, session_id=session.id,
                movement_type=CashMovement.MovementType.EXPENSE, amount=amount,
                reference=f"pago-cxp:{payable.id}", reason="PAGO_CXP",
                idempotency_key=cash_key,
            )
            cash_movement_id = movement.id

        payable.refresh_from_db()
        emit_service_event(
            company=company,
            branch=branch,
            request=request,
            module="PROCUREMENT",
            event_type="PROCUREMENT_PAYABLE_PAID",
            reason_code="PROCUREMENT_OK",
            actor_user=actor,
            subject_type="PAYABLE",
            subject_id=str(payable.obligation_id),
            after_snapshot={"status": payable.status, "outstanding": str(payable.outstanding_amount)},
            metadata={"paid": str(amount), "method": method, "cash_movement_id": cash_movement_id},
        )
        return _payment_result(
            payable=payable,
            allocation_id=str(allocation.allocation_id),
            paid=amount,
            cash_movement_id=cash_movement_id,
        )
