from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.modulos.common.tender import TenderPaymentMethod

from .models import PurchaseDocType

# doc_type creables vía API: PURCHASE_ORDER/PO_RECEIPT son solo de numeración interna
# (la OC y la recepción tienen modelo y endpoints propios).
_DOC_CHOICES = [
    (v, label)
    for v, label in PurchaseDocType.choices
    if v not in (PurchaseDocType.PURCHASE_ORDER, PurchaseDocType.PO_RECEIPT)
]


class PurchaseDocCreateSerializer(serializers.Serializer):
    doc_type = serializers.ChoiceField(choices=_DOC_CHOICES)
    series = serializers.CharField(max_length=16, required=False, allow_blank=False, default="P")
    currency = serializers.CharField(max_length=8, required=False, allow_blank=False, default="NIO")
    supplier_name = serializers.CharField(max_length=160, required=False, allow_blank=True, default="")
    supplier_ref = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    external_ref = serializers.CharField(max_length=96, required=False, allow_blank=True, default="")
    supplier_party_id = serializers.IntegerField(required=False, allow_null=True)
    subtotal = serializers.DecimalField(max_digits=18, decimal_places=2)
    tax_total = serializers.DecimalField(max_digits=18, decimal_places=2, required=False, default=Decimal("0.00"))
    total = serializers.DecimalField(max_digits=18, decimal_places=2)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    metadata_json = serializers.JSONField(required=False, default=dict)
    idempotency_key = serializers.CharField(max_length=96, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if attrs["subtotal"] < 0 or attrs["tax_total"] < 0:
            raise serializers.ValidationError("subtotal/tax_total deben ser >= 0")
        if attrs["total"] < 0:
            raise serializers.ValidationError("total debe ser >= 0")
        if (attrs["subtotal"] + attrs["tax_total"]) != attrs["total"]:
            raise serializers.ValidationError("total debe ser subtotal + tax_total")
        supplier_party_id = attrs.get("supplier_party_id")
        if supplier_party_id is not None and int(supplier_party_id) <= 0:
            raise serializers.ValidationError("supplier_party_id debe ser > 0")
        return attrs


class PurchaseDocVoidSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="VOID")


# --------------------------------------------------------------------------- Ola B

class PurchaseOrderLineInSerializer(serializers.Serializer):
    item_id = serializers.IntegerField(min_value=1)
    qty = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    # Sin costo: se resuelve del precio por proveedor (acordado → último costo).
    unit_cost = serializers.DecimalField(
        max_digits=18, decimal_places=4, required=False, allow_null=True, min_value=Decimal("0")
    )
    tax_rate = serializers.DecimalField(
        max_digits=6, decimal_places=4, required=False, allow_null=True,
        min_value=Decimal("0"), max_value=Decimal("1"),
    )
    description = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class PurchaseOrderCreateSerializer(serializers.Serializer):
    supplier_party_id = serializers.IntegerField(min_value=1)
    currency = serializers.CharField(max_length=8, required=False, default="NIO")
    series = serializers.CharField(max_length=16, required=False, default="OC")
    expected_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    idempotency_key = serializers.CharField(max_length=96, required=False, allow_blank=True, default="")
    lines = PurchaseOrderLineInSerializer(many=True, allow_empty=False)


class PurchaseOrderUpdateSerializer(serializers.Serializer):
    expected_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True)
    lines = PurchaseOrderLineInSerializer(many=True, required=False, allow_empty=False)


class ReceiveLineSerializer(serializers.Serializer):
    order_line_id = serializers.IntegerField(min_value=1)
    qty = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    # Costo real de la recepción; sin él, el de la línea de la OC.
    unit_cost = serializers.DecimalField(
        max_digits=18, decimal_places=4, required=False, allow_null=True, min_value=Decimal("0")
    )


class ReceiveSerializer(serializers.Serializer):
    warehouse_id = serializers.IntegerField(min_value=1)
    idempotency_key = serializers.CharField(max_length=96)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    lines = ReceiveLineSerializer(many=True, allow_empty=False)


class OrderInvoiceSerializer(serializers.Serializer):
    subtotal = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0"))
    tax_total = serializers.DecimalField(
        max_digits=18, decimal_places=2, required=False, default=Decimal("0.00"), min_value=Decimal("0")
    )
    total = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0.01"))
    supplier_ref = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    external_ref = serializers.CharField(max_length=96, required=False, allow_blank=True, default="")
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    # Forzar fuera de tolerancia exige TAMBIÉN el permiso procurement.invoice.match_override.
    match_override = serializers.BooleanField(default=False)
    idempotency_key = serializers.CharField(max_length=96, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if (attrs["subtotal"] + attrs["tax_total"]) != attrs["total"]:
            raise serializers.ValidationError("total debe ser subtotal + tax_total")
        return attrs


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class RequisitionLineInSerializer(serializers.Serializer):
    item_id = serializers.IntegerField(min_value=1)
    qty = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class RequisitionCreateSerializer(serializers.Serializer):
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    lines = RequisitionLineInSerializer(many=True, allow_empty=False)


class RejectSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


class ConvertSerializer(serializers.Serializer):
    supplier_party_id = serializers.IntegerField(min_value=1)


class SupplierPriceUpsertSerializer(serializers.Serializer):
    supplier_party_id = serializers.IntegerField(min_value=1)
    item_id = serializers.IntegerField(min_value=1)
    agreed_price = serializers.DecimalField(
        max_digits=18, decimal_places=4, allow_null=True, min_value=Decimal("0")
    )
    currency = serializers.CharField(max_length=8, required=False, default="NIO")


class SuggestionItemSerializer(serializers.Serializer):
    item_id = serializers.IntegerField(min_value=1)
    qty = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    supplier_party_id = serializers.IntegerField(min_value=1)


class SuggestionOrderSerializer(serializers.Serializer):
    items = SuggestionItemSerializer(many=True, allow_empty=False)


class PayPayableSerializer(serializers.Serializer):
    payable_id = serializers.IntegerField(min_value=1)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0.01"))
    method = serializers.ChoiceField(choices=TenderPaymentMethod.choices)
    idempotency_key = serializers.CharField(max_length=96)
