from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from .models import ProcessingOrder, TransformationRecipe


class RecipeCreateSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=32)
    name = serializers.CharField(max_length=120)
    input_item_id = serializers.IntegerField()
    output_item_id = serializers.IntegerField()
    expected_yield_pct = serializers.DecimalField(max_digits=6, decimal_places=2)
    yield_tolerance_pct = serializers.DecimalField(
        max_digits=6, decimal_places=2, required=False, default=Decimal("5.00")
    )


class RecipeSerializer(serializers.ModelSerializer):
    input_item_name = serializers.CharField(source="input_item.name", read_only=True)
    output_item_name = serializers.CharField(source="output_item.name", read_only=True)

    class Meta:
        model = TransformationRecipe
        fields = [
            "id", "code", "name", "input_item_id", "input_item_name",
            "output_item_id", "output_item_name", "expected_yield_pct",
            "yield_tolerance_pct", "is_active",
        ]


class OrderCreateSerializer(serializers.Serializer):
    recipe_id = serializers.IntegerField()
    input_warehouse_id = serializers.IntegerField()
    output_warehouse_id = serializers.IntegerField()
    input_qty = serializers.DecimalField(max_digits=14, decimal_places=2)
    reference = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class OrderCloseSerializer(serializers.Serializer):
    output_qty = serializers.DecimalField(max_digits=14, decimal_places=2)


class OrderSerializer(serializers.ModelSerializer):
    recipe_code = serializers.CharField(source="recipe.code", read_only=True)

    class Meta:
        model = ProcessingOrder
        fields = [
            "id", "reference", "recipe_id", "recipe_code", "input_warehouse_id",
            "output_warehouse_id", "input_qty", "output_qty", "status",
            "input_cost_total", "output_unit_cost", "yield_pct", "shrinkage_qty",
            "issue_movement_id", "receive_movement_id", "started_at", "finished_at",
            "note", "created_at",
        ]
