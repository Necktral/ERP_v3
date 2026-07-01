from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.modulos.common.tender import TENDER_PAYMENT_METHOD_CHOICES

from .models import CashMovement, CashDenomination


class DenominationLineIn(serializers.Serializer):
    """Una línea de arqueo: denominación × cantidad."""
    denomination_value = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0")
    )
    # Tope de negocio: un arqueo real no tiene un millón de unidades de una denominación.
    # Acota además el desbordamiento del PositiveIntegerField (32-bit) y del subtotal
    # Decimal(18) → cantidad gigante responde 400, no 500 (BUG-4).
    quantity = serializers.IntegerField(min_value=0, max_value=1_000_000)
    denomination_type = serializers.ChoiceField(
        choices=CashDenomination.DenominationType.choices,
        required=False,
        default=CashDenomination.DenominationType.BILL,
    )


class DenominationCountIn(serializers.Serializer):
    """Arqueo de caja por denominación (apertura o cierre).

    Cierra el 500 por entrada cruda (BUG-4): DRF valida tipos/forma y responde 400
    ante basura (no-lista, falta de campos, valor/cantidad no numéricos, negativos).
    """
    denominations = DenominationLineIn(many=True, allow_empty=False)


class PaymentIntentCreateIn(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(max_length=8, required=False, allow_blank=True)
    external_ref = serializers.CharField(max_length=96, required=False, allow_blank=True)
    idempotency_key = serializers.CharField(max_length=96, required=False, allow_blank=True)
    provider = serializers.CharField(max_length=32, required=False, allow_blank=True)
    payment_method = serializers.ChoiceField(
        choices=TENDER_PAYMENT_METHOD_CHOICES,
        required=False,
        allow_blank=True,
    )


class PaymentIntentReverseCaptureIn(serializers.Serializer):
    idempotency_key = serializers.CharField(max_length=96, allow_blank=False, trim_whitespace=True)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, trim_whitespace=True)


class CashSessionOpenIn(serializers.Serializer):
    opening_amount = serializers.DecimalField(max_digits=18, decimal_places=2, required=False)
    notes = serializers.CharField(required=False, allow_blank=True)
    # BUG-10: desglose del fondo de apertura por denominación (opcional). Si viene, su
    # suma es el `opening_amount` autoritativo y se persiste con stage=OPENING.
    denominations = DenominationLineIn(many=True, required=False)


class CashSessionCloseIn(serializers.Serializer):
    counted_amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    notes = serializers.CharField(required=False, allow_blank=True)


class CashMovementCreateIn(serializers.Serializer):
    movement_type = serializers.ChoiceField(choices=CashMovement.MovementType.choices)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    reference = serializers.CharField(max_length=96, required=False, allow_blank=True)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True)
    idempotency_key = serializers.CharField(max_length=96, required=False, allow_blank=True)


class PaymentIntentAuthorizeIn(serializers.Serializer):
    amount_authorized = serializers.DecimalField(max_digits=18, decimal_places=2, required=False, allow_null=True)
    provider_txn_id = serializers.CharField(max_length=96, required=False, allow_blank=True)


class PaymentIntentCaptureIn(serializers.Serializer):
    provider_txn_id = serializers.CharField(max_length=96, required=False, allow_blank=True)


class PaymentIntentRefundIn(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True)
    idempotency_key = serializers.CharField(max_length=96, required=False, allow_blank=True)


class CashSessionOpenWithRegisterIn(serializers.Serializer):
    opening_amount = serializers.DecimalField(max_digits=18, decimal_places=2, required=False)
    register_id = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True)
