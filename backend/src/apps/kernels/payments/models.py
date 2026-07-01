from __future__ import annotations

import uuid
from decimal import Decimal
from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.modulos.common.models import Syncable
from apps.modulos.common.tender import TENDER_PAYMENT_METHOD_CHOICES
from apps.modulos.iam.models import OrgUnit


class PaymentIntent(Syncable):
    # Operativo: la intención de pago se origina en el nodo (caja) y sube como evento.
    class Status(models.TextChoices):
        INTENDED = "INTENDED", "Intended"
        AUTHORIZED = "AUTHORIZED", "Authorized"
        CAPTURED = "CAPTURED", "Captured"
        PARTIALLY_CAPTURED = "PARTIALLY_CAPTURED", "Partially Captured"
        REFUNDED = "REFUNDED", "Refunded"
        PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED", "Partially Refunded"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"

    payment_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    company = models.ForeignKey(OrgUnit, on_delete=models.PROTECT, related_name="pay_intents_company")
    branch = models.ForeignKey(
        OrgUnit, null=True, blank=True,
        on_delete=models.PROTECT, related_name="pay_intents_branch",
    )

    external_ref = models.CharField(max_length=96, blank=True, default="")
    idempotency_key = models.CharField(max_length=96, blank=True, default="")

    amount = models.DecimalField(max_digits=18, decimal_places=2)
    amount_authorized = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True,
        help_text="Monto autorizado (puede ser parcial)"
    )
    amount_captured = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True,
        help_text="Monto capturado/cobrado efectivamente"
    )
    amount_refunded = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00"),
        help_text="Total reembolsado (acumulado)"
    )
    currency = models.CharField(max_length=8, default="NIO")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.INTENDED, db_index=True)

    provider = models.CharField(max_length=32, blank=True, default="")
    provider_txn_id = models.CharField(max_length=96, blank=True, default="")
    payment_method = models.CharField(max_length=24, choices=TENDER_PAYMENT_METHOD_CHOICES, blank=True, default="")

    authorized_at = models.DateTimeField(null=True, blank=True)
    captured_at = models.DateTimeField(null=True, blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(max_length=255, blank=True, default="")
    cancellation_reason = models.CharField(max_length=255, blank=True, default="")

    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "payments"
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="ck_pay_intent_amount_positive"),
            models.UniqueConstraint(
                fields=["company", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="uq_pay_intent_company_idempotency",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "branch", "status", "created_at"]),
            models.Index(fields=["provider", "provider_txn_id"]),
            models.Index(fields=["company", "payment_method", "status"]),
        ]

    @property
    def outstanding_amount(self) -> Decimal:
        """Monto pendiente de capturar."""
        captured = self.amount_captured or Decimal("0.00")
        return self.amount - captured

    @property
    def refundable_amount(self) -> Decimal:
        """Monto capturado que puede ser reembolsado."""
        captured = self.amount_captured or Decimal("0.00")
        return captured - (self.amount_refunded or Decimal("0.00"))

    # Máquina de estado explícita (§9). Patrón cec.CloseRun / iam.ApprovalRequest.
    _ALLOWED_TRANSITIONS: ClassVar[dict[str, set[str]]] = {
        Status.INTENDED: {Status.AUTHORIZED, Status.CAPTURED, Status.CANCELLED, Status.FAILED},
        Status.AUTHORIZED: {Status.CAPTURED, Status.PARTIALLY_CAPTURED, Status.CANCELLED, Status.FAILED},
        Status.CAPTURED: {Status.REFUNDED, Status.PARTIALLY_REFUNDED, Status.FAILED},
        Status.PARTIALLY_CAPTURED: {
            Status.CAPTURED, Status.REFUNDED, Status.PARTIALLY_REFUNDED, Status.FAILED,
        },
        Status.PARTIALLY_REFUNDED: {Status.REFUNDED, Status.PARTIALLY_REFUNDED},
        Status.REFUNDED: set(),
        Status.FAILED: set(),
        Status.CANCELLED: set(),
    }

    def can_transition_to(self, target_status: str) -> bool:
        if target_status == self.status:
            return True
        return target_status in self._ALLOWED_TRANSITIONS.get(self.status, set())


class PaymentRefund(Syncable):
    """Registro individual de cada reembolso contra un PaymentIntent."""
    # Operativo: el reembolso se origina en el nodo (caja) y sube como evento.

    refund_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    intent = models.ForeignKey(PaymentIntent, on_delete=models.PROTECT, related_name="refunds")
    company = models.ForeignKey(OrgUnit, on_delete=models.PROTECT, related_name="pay_refunds_company")

    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=8, default="NIO")
    reason = models.CharField(max_length=255, blank=True, default="")
    idempotency_key = models.CharField(max_length=96, blank=True, default="")

    provider_refund_id = models.CharField(max_length=96, blank=True, default="")
    metadata = models.JSONField(default=dict)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="pay_refunds_created"
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        app_label = "payments"
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="ck_pay_refund_amount_positive"),
            models.UniqueConstraint(
                fields=["intent", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="uq_pay_refund_intent_idempotency",
            ),
        ]
        indexes = [
            models.Index(fields=["intent", "created_at"]),
            models.Index(fields=["company", "created_at"]),
        ]


class CashSession(Syncable):
    # Operativo: la sesión de caja (arqueo) se abre/cierra en el nodo y sube como evento.
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        COUNT_PENDING = "COUNT_PENDING", "Count pending"
        REVIEW_PENDING = "REVIEW_PENDING", "Review pending"
        CLOSED = "CLOSED", "Closed"
        REOPENED_FOR_INVESTIGATION = "REOPENED_FOR_INVESTIGATION", "Reopened for investigation"

    company = models.ForeignKey(OrgUnit, on_delete=models.PROTECT, related_name="cash_sessions_company")
    branch = models.ForeignKey(
        OrgUnit, null=True, blank=True,
        on_delete=models.PROTECT, related_name="cash_sessions_branch",
    )

    # Identificador del punto de venta / caja — permite múltiples sesiones por sucursal
    register_id = models.CharField(
        max_length=64, blank=True, default="",
        help_text="Identificador del punto de venta (ej: CAJA-1, POS-COMISARIATO-A)"
    )

    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT, related_name="cash_sessions_opened",
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="cash_sessions_closed",
    )

    status = models.CharField(max_length=32, choices=Status.choices, default=Status.OPEN, db_index=True)

    opened_at = models.DateTimeField(default=timezone.now, editable=False)
    closed_at = models.DateTimeField(null=True, blank=True)

    opening_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    expected_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    counted_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    difference_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    notes = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict)

    class Meta:
        app_label = "payments"
        indexes = [
            models.Index(fields=["company", "branch", "status", "opened_at"]),
            models.Index(fields=["company", "branch", "register_id", "status"]),
        ]
        constraints = [
            # Permite solo una sesión OPEN por (branch, register_id)
            models.UniqueConstraint(
                fields=["branch", "register_id"],
                condition=models.Q(status="OPEN"),
                name="uq_cash_session_open_per_register",
            ),
        ]

    def clean(self):
        if self.status == self.Status.CLOSED and self.closed_at is None:
            raise ValidationError("CashSession cerrada requiere closed_at.")
        expected_difference = self.counted_amount - self.expected_amount
        if self.difference_amount != expected_difference:
            raise ValidationError("difference_amount debe ser counted_amount - expected_amount.")

    def total_income(self) -> Decimal:
        return sum(
            m.amount for m in self.movements.filter(movement_type=CashMovement.MovementType.INCOME)
        ) or Decimal("0.00")

    def total_expenses(self) -> Decimal:
        return sum(
            m.amount for m in self.movements.filter(
                movement_type__in=[CashMovement.MovementType.EXPENSE, CashMovement.MovementType.REFUND]
            )
        ) or Decimal("0.00")

    # Máquina de estado explícita (§9). Patrón cec.CloseRun / iam.ApprovalRequest.
    _ALLOWED_TRANSITIONS: ClassVar[dict[str, set[str]]] = {
        Status.OPEN: {Status.COUNT_PENDING, Status.REVIEW_PENDING, Status.CLOSED},
        Status.COUNT_PENDING: {Status.REVIEW_PENDING, Status.CLOSED, Status.OPEN},
        Status.REVIEW_PENDING: {Status.CLOSED, Status.COUNT_PENDING},
        Status.CLOSED: {Status.REOPENED_FOR_INVESTIGATION},
        Status.REOPENED_FOR_INVESTIGATION: {Status.CLOSED, Status.COUNT_PENDING},
    }

    def can_transition_to(self, target_status: str) -> bool:
        if target_status == self.status:
            return True
        return target_status in self._ALLOWED_TRANSITIONS.get(self.status, set())


class CashDenomination(models.Model):
    """
    Arqueo de caja: desglose por denominación de billetes y monedas.
    Se registra al momento del cierre de la sesión.

    Nicaragua usa: billetes 10, 20, 50, 100, 200, 500, 1000 C$
                   monedas 0.50, 1, 5, 10, 25 C$
    """

    class DenominationType(models.TextChoices):
        BILL = "BILL", "Billete"
        COIN = "COIN", "Moneda"

    class Stage(models.TextChoices):
        OPENING = "OPENING", "Apertura (fondo)"
        CLOSING = "CLOSING", "Cierre (arqueo)"

    session = models.ForeignKey(CashSession, on_delete=models.CASCADE, related_name="denominations")

    # Etapa del arqueo: el cierre siempre persistió el desglose; la apertura ahora también
    # (BUG-10). `default=CLOSING` preserva la semántica de las filas existentes.
    stage = models.CharField(
        max_length=8, choices=Stage.choices, default=Stage.CLOSING, db_index=True
    )

    denomination_type = models.CharField(max_length=8, choices=DenominationType.choices)
    denomination_value = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Valor de la denominación (ej: 100.00 para billete de C$100)"
    )
    quantity = models.PositiveIntegerField(default=0)
    subtotal = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00"),
        help_text="denomination_value * quantity — calculado automáticamente"
    )

    class Meta:
        app_label = "payments"
        constraints = [
            models.UniqueConstraint(
                fields=["session", "stage", "denomination_value"],
                name="uq_cash_denom_session_stage_value"
            ),
        ]
        ordering = ["-denomination_type", "-denomination_value"]

    def save(self, *args, **kwargs):
        self.subtotal = self.denomination_value * Decimal(str(self.quantity))
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"C${self.denomination_value} × {self.quantity} = C${self.subtotal}"


class CashMovement(Syncable):
    # Operativo: cada movimiento de caja se origina en el nodo y sube como evento append-only.
    class MovementType(models.TextChoices):
        INCOME = "INCOME", "Ingreso"
        EXPENSE = "EXPENSE", "Egreso"
        ADJUSTMENT = "ADJUSTMENT", "Ajuste"
        REFUND = "REFUND", "Devolución"

    session = models.ForeignKey(CashSession, on_delete=models.CASCADE, related_name="movements")

    # Vínculo opcional al PaymentIntent que originó este movimiento
    payment_intent = models.ForeignKey(
        PaymentIntent, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="cash_movements"
    )

    movement_type = models.CharField(max_length=16, choices=MovementType.choices, db_index=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    payment_method = models.CharField(
        max_length=24, choices=TENDER_PAYMENT_METHOD_CHOICES, blank=True, default="",
        help_text="Método de pago de este movimiento específico"
    )
    reference = models.CharField(max_length=96, blank=True, default="")
    reason = models.CharField(max_length=255, blank=True, default="")
    idempotency_key = models.CharField(max_length=96, blank=True, default="")
    metadata = models.JSONField(default=dict)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="cash_movements_created",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        app_label = "payments"
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="ck_cash_movement_amount_positive"),
            models.UniqueConstraint(
                fields=["session", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="uq_cash_movement_session_idempotency",
            ),
        ]
        indexes = [
            models.Index(fields=["session", "created_at"]),
            models.Index(fields=["session", "idempotency_key"], name="ix_cashmov_session_idem"),
            models.Index(fields=["session", "movement_type"]),
            models.Index(fields=["payment_intent"], name="ix_cashmov_intent"),
        ]


class BankAccount(models.Model):
    """Cuenta bancaria de la empresa (Ola D: conciliación).

    El efectivo se concilia por arqueo de caja (CashSession); lo bancario
    (transferencias, cheques, tarjetas liquidadas) se concilia contra extracto.
    """

    company = models.ForeignKey(OrgUnit, on_delete=models.PROTECT, related_name="bank_accounts")
    name = models.CharField(max_length=120)
    bank_name = models.CharField(max_length=120)
    account_number = models.CharField(max_length=64)
    currency = models.CharField(max_length=8, default="NIO")
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="bank_accounts_created",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        app_label = "payments"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "bank_name", "account_number"],
                name="uq_bank_account_company_number",
            ),
        ]

    def __str__(self):
        return f"{self.bank_name} {self.account_number}"


class BankStatement(models.Model):
    """Extracto bancario de un período; se concilia línea por línea y queda inmutable."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        RECONCILED = "RECONCILED", "Reconciled"

    company = models.ForeignKey(OrgUnit, on_delete=models.PROTECT, related_name="bank_statements")
    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="statements")
    period_start = models.DateField()
    period_end = models.DateField()
    opening_balance = models.DecimalField(max_digits=18, decimal_places=2)
    closing_balance = models.DecimalField(max_digits=18, decimal_places=2)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN, db_index=True)
    reconciled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="bank_statements_reconciled",
    )
    reconciled_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="bank_statements_created",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        app_label = "payments"
        indexes = [
            models.Index(fields=["company", "bank_account", "-period_end"], name="ix_bankstmt_scope"),
        ]

    def __str__(self):
        return f"Extracto {self.bank_account_id} {self.period_start}..{self.period_end}"


class BankStatementLine(models.Model):
    """Línea del extracto: monto con signo (+depósito / −retiro)."""

    class Status(models.TextChoices):
        UNMATCHED = "UNMATCHED", "Unmatched"
        MATCHED = "MATCHED", "Matched"
        EXCLUDED = "EXCLUDED", "Excluded"

    statement = models.ForeignKey(BankStatement, on_delete=models.CASCADE, related_name="lines")
    position = models.PositiveIntegerField(default=0)
    line_date = models.DateField()
    description = models.CharField(max_length=200, blank=True, default="")
    reference = models.CharField(max_length=96, blank=True, default="")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.UNMATCHED, db_index=True
    )
    matched_intent = models.ForeignKey(
        PaymentIntent, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="bank_statement_lines",
    )
    excluded_reason = models.CharField(max_length=255, blank=True, default="")
    matched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="bank_lines_matched",
    )
    matched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "payments"
        ordering = ["position", "id"]
        constraints = [
            models.CheckConstraint(condition=~models.Q(amount=0), name="ck_bank_line_amount_nonzero"),
            # Un pago del sistema solo puede respaldar UNA línea de extracto.
            models.UniqueConstraint(
                fields=["matched_intent"],
                condition=models.Q(matched_intent__isnull=False),
                name="uq_bank_line_matched_intent",
            ),
        ]
        indexes = [
            models.Index(fields=["statement", "status"], name="ix_bankline_stmt_status"),
        ]

    def __str__(self):
        return f"{self.line_date} {self.amount} ({self.status})"
