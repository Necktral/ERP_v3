"""Pagos del neto de planilla + cierre del período (U5).

Registra el pago del líquido por empleado y mueve el período por su ciclo final:
`APPROVED → PAID` (auto, cuando todas las líneas con neto>0 quedan cubiertas) `→ CLOSED`.
El abono de préstamos a `portfolio` y los endpoints HTTP quedan como follow-up.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.modulos.audit.writer import write_event

from .models import PayrollEntry, PayrollPayment, PayrollPeriod, PeriodStatus


class PayrollPaymentError(ValueError):
    """Error de dominio para pagos/cierre de planilla."""


def _entry_is_paid(entry: PayrollEntry) -> bool:
    paid = entry.payments.aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
    return paid >= (entry.net_to_pay or Decimal("0.00"))


def _period_fully_paid(period: PayrollPeriod) -> bool:
    entries = list(PayrollEntry.objects.filter(sheet__period=period).prefetch_related("payments"))
    if not entries:
        return False
    return all(_entry_is_paid(e) for e in entries)


def register_payroll_payment(
    *, request, actor, entry: PayrollEntry, payment_method: str, amount, payment_date=None, reference: str = "", notes: str = ""
) -> PayrollPayment:
    """Registra el pago del neto de una línea. Auto-transiciona el período a PAID si queda cubierto.

    CONCURRENCIA (anti doble-pago/sobrepago): el chequeo de "neto restante" y la creación del
    pago se serializan tomando un lock pesimista sobre la fila `PayrollEntry`
    (`select_for_update`). Sin él, N requests simultáneos (reintentos de la cola offline /
    doble click) leían el mismo `already_paid` y todos creaban su pago → sobrepago real.
    """
    period = entry.sheet.period
    if period.status not in (PeriodStatus.APPROVED, PeriodStatus.PAID):
        raise PayrollPaymentError(f"El período debe estar APROBADO para pagar (estado: {period.status}).")
    amount = Decimal(str(amount))
    if amount <= 0:
        raise PayrollPaymentError("El monto del pago debe ser > 0.")

    with transaction.atomic():
        # Lock pesimista de la línea: serializa los cálculos de saldo concurrentes.
        locked_entry = PayrollEntry.objects.select_for_update().get(pk=entry.pk)

        # Idempotencia DENTRO del lock: si la clave ya creó un pago, devolverlo (no duplicar).
        ref_key = (reference or "").strip()
        if ref_key:
            existing = locked_entry.payments.filter(reference=ref_key).first()
            if existing is not None:
                return existing

        # NM-05: no permitir pagar más que el neto restante (evita sobrepago / pago duplicado).
        already_paid = locked_entry.payments.aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
        remaining = (locked_entry.net_to_pay or Decimal("0.00")) - already_paid
        if amount > remaining:
            raise PayrollPaymentError(
                f"El pago ({amount}) excede el neto restante ({remaining})."
            )

        payment = PayrollPayment.objects.create(
            entry=entry,
            company=period.company,
            payment_method=payment_method,
            amount=amount,
            payment_date=payment_date or timezone.now().date(),
            reference=reference or "",
            notes=notes or "",
            created_by=actor,
        )
        write_event(
            request=request,
            module="NOMINA",
            event_type="NOMINA_PAYMENT_REGISTERED",
            reason_code="NOMINA_OK",
            actor_user=actor,
            subject_type="PAYROLL_PAYMENT",
            subject_id=str(payment.id),
            metadata={"period_id": period.id, "entry_id": entry.id, "amount": str(amount), "method": payment_method},
        )
        if period.status == PeriodStatus.APPROVED and _period_fully_paid(period):
            period.status = PeriodStatus.PAID
            period.save(update_fields=["status", "updated_at"])
            write_event(
                request=request,
                module="NOMINA",
                event_type="NOMINA_PERIOD_PAID",
                reason_code="NOMINA_OK",
                actor_user=actor,
                subject_type="PAYROLL_PERIOD",
                subject_id=str(period.id),
                metadata={"period_id": period.id},
            )
        return payment


def register_payroll_payment_idempotent(
    *, request, actor, entry: PayrollEntry, payment_method: str, amount,
    payment_date=None, idempotency_key: str = "", notes: str = "",
) -> PayrollPayment:
    """Igual que `register_payroll_payment` pero idempotente por `idempotency_key`.

    La clave del cliente (cola offline de la app del pagador) viaja en `PayrollPayment.reference`.
    Si ya existe un pago de ESTA línea con esa referencia, lo devuelve tal cual (reintento seguro,
    sin doble pago) en vez de crear un duplicado. Sin migración: reusa el campo `reference`.

    La idempotencia y el guard de sobrepago se resuelven AHORA dentro del lock pesimista de
    `register_payroll_payment` (select_for_update sobre la línea), de modo que dos envíos
    simultáneos con la misma clave no abren ventana de doble pago.
    """
    key = (idempotency_key or "").strip()
    return register_payroll_payment(
        request=request, actor=actor, entry=entry, payment_method=payment_method,
        amount=amount, payment_date=payment_date, reference=key, notes=notes,
    )


def close_period(*, request, actor, period: PayrollPeriod) -> PayrollPeriod:
    """Cierra un período PAGADO (PAID → CLOSED)."""
    if period.status != PeriodStatus.PAID:
        raise PayrollPaymentError(f"Solo se puede cerrar un período PAGADO (estado: {period.status}).")
    with transaction.atomic():
        period.status = PeriodStatus.CLOSED
        period.save(update_fields=["status", "updated_at"])
        write_event(
            request=request,
            module="NOMINA",
            event_type="NOMINA_PERIOD_CLOSED",
            reason_code="NOMINA_OK",
            actor_user=actor,
            subject_type="PAYROLL_PERIOD",
            subject_id=str(period.id),
            metadata={"period_id": period.id},
        )
    return period
