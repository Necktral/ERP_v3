from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.modulos.common.tender import TenderPaymentMethod


class PosSaleLineSerializer(serializers.Serializer):
    inventory_item_id = serializers.IntegerField(min_value=1)
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    # Solo con permiso sales.pos.price_override; si no viene, manda el catálogo.
    unit_price = serializers.DecimalField(
        max_digits=18, decimal_places=4, required=False, allow_null=True, min_value=Decimal("0")
    )
    discount_pct = serializers.DecimalField(
        max_digits=6, decimal_places=4, required=False, default=Decimal("0.0000"),
        min_value=Decimal("0"), max_value=Decimal("1"),
    )
    warehouse_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class PosSalePaymentSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=TenderPaymentMethod.choices)
    # CREDIT no manda monto (es el total); contado sí.
    amount = serializers.DecimalField(
        max_digits=18, decimal_places=2, required=False, allow_null=True, min_value=Decimal("0.01")
    )


class CollectReceivableSerializer(serializers.Serializer):
    receivable_id = serializers.IntegerField(min_value=1)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0.01"))
    method = serializers.ChoiceField(choices=TenderPaymentMethod.choices)
    idempotency_key = serializers.CharField(max_length=96)


class PosSaleSerializer(serializers.Serializer):
    warehouse_id = serializers.IntegerField(min_value=1)
    customer_party_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    customer_name = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    currency = serializers.CharField(max_length=8, required=False, default="NIO")
    is_fiscal = serializers.BooleanField(default=True)
    idempotency_key = serializers.CharField(max_length=96)
    # Código del pre-ticket de auto-facturación que esta venta cobra (opcional).
    self_service_code = serializers.CharField(
        max_length=12, required=False, allow_blank=True, default=""
    )
    # Grant firmado de autorización de supervisor (cuando el cajero no tiene el permiso).
    override_grant = serializers.CharField(required=False, allow_blank=True, default="")
    lines = PosSaleLineSerializer(many=True, allow_empty=False)
    payments = PosSalePaymentSerializer(many=True, allow_empty=False)

    def validate(self, attrs):
        for p in attrs["payments"]:
            if p["method"] != TenderPaymentMethod.CREDIT and p.get("amount") is None:
                raise serializers.ValidationError({"payments": "amount es requerido para pagos de contado."})
        return attrs


class PosOverrideSerializer(serializers.Serializer):
    """Un supervisor se reautentica en la caja para autorizar precio/descuento."""

    supervisor_username = serializers.CharField(max_length=150)
    supervisor_password = serializers.CharField(max_length=256, trim_whitespace=False)
    reason = serializers.CharField(max_length=255)


class SelfServiceLineSerializer(serializers.Serializer):
    inventory_item_id = serializers.IntegerField(min_value=1)
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))


class SelfServiceCreateSerializer(serializers.Serializer):
    currency = serializers.CharField(max_length=8, required=False, default="NIO")
    lines = SelfServiceLineSerializer(many=True, allow_empty=False)
