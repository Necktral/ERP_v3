from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from .models import CustomerSegment


class AccountUpsertSerializer(serializers.Serializer):
    party_id = serializers.IntegerField(min_value=1)
    segment = serializers.ChoiceField(choices=CustomerSegment.choices)
    credit_limit = serializers.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    credit_days = serializers.IntegerField(min_value=0, max_value=365, required=False, default=30)
    collecting_company_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    is_active = serializers.BooleanField(default=True)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class SaleLineSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=255)
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    unit_price = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"))
    tax_rate = serializers.DecimalField(
        max_digits=6, decimal_places=4, required=False, default=Decimal("0.0000")
    )
    inventory_item_id = serializers.IntegerField(min_value=1)
    warehouse_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class SaleSerializer(serializers.Serializer):
    account_id = serializers.IntegerField(min_value=1)
    warehouse_id = serializers.IntegerField(min_value=1)
    reference_code = serializers.CharField(max_length=96)
    currency = serializers.CharField(max_length=8, required=False, default="NIO")
    is_fiscal = serializers.BooleanField(default=True)
    lines = SaleLineSerializer(many=True, allow_empty=False)


class CobrarYPagarSerializer(serializers.Serializer):
    """Cobro negociado + pago (CO-PA): abono parcial por deuda (0..saldo) y método de pago."""

    abono_comisariato = serializers.DecimalField(
        max_digits=18, decimal_places=2, required=False, default=Decimal("0.00"), min_value=Decimal("0.00")
    )
    abono_prestamo = serializers.DecimalField(
        max_digits=18, decimal_places=2, required=False, default=Decimal("0.00"), min_value=Decimal("0.00")
    )
    payment_method = serializers.ChoiceField(choices=["CASH", "BANK_TRANSFER", "CHECK"], default="CASH")
    idempotency_key = serializers.CharField(required=False, allow_blank=True, default="", max_length=96)


class RectificarCobroSerializer(serializers.Serializer):
    """Rectifica un cobro ya aplicado: montos corregidos + motivo (obligatorio) para anular el recibo."""

    abono_comisariato = serializers.DecimalField(
        max_digits=18, decimal_places=2, required=False, default=Decimal("0.00"), min_value=Decimal("0.00")
    )
    abono_prestamo = serializers.DecimalField(
        max_digits=18, decimal_places=2, required=False, default=Decimal("0.00"), min_value=Decimal("0.00")
    )
    payment_method = serializers.ChoiceField(choices=["CASH", "BANK_TRANSFER", "CHECK"], default="CASH")
    motivo = serializers.CharField(max_length=255, allow_blank=False)
    idempotency_key = serializers.CharField(required=False, allow_blank=True, default="", max_length=96)
