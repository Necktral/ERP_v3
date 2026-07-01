"""Beneficio de café — el MRP de Odoo aterrizado a UNA transformación: pergamino→oro.

BOM ligero: una `TransformationRecipe` declara insumo, producto y rendimiento esperado
(% de libras que sobreviven al trillado/secado). La `ProcessingOrder` consume el insumo
al INICIAR (sale de bodega con su costo kardex) y produce el café oro al CERRAR con
**costo absorbido**: todo el costo del insumo se reparte en las libras de salida — la
merma encarece el oro, como en la realidad. El rendimiento real fuera del rango esperado
dispara una alerta (módulo alertas): antifraude de báscula del beneficio.

El stock y los costos viven en el kernel `inventarios` (kardex); aquí solo la orden.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.modulos.common.models import Syncable
from apps.modulos.iam.models import OrgUnit


class TransformationRecipe(models.Model):
    company = models.ForeignKey(
        OrgUnit, on_delete=models.PROTECT, related_name="beneficio_recipes",
    )
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=120)
    input_item = models.ForeignKey(
        "inventarios.InventoryItem", on_delete=models.PROTECT,
        related_name="beneficio_recipes_as_input",
        help_text="Insumo (p.ej. café pergamino húmedo).",
    )
    output_item = models.ForeignKey(
        "inventarios.InventoryItem", on_delete=models.PROTECT,
        related_name="beneficio_recipes_as_output",
        help_text="Producto (p.ej. café oro).",
    )
    expected_yield_pct = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text="Rendimiento esperado (%): libras de salida por cada 100 de entrada.",
    )
    yield_tolerance_pct = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("5.00"),
        help_text="Desviación tolerada (puntos %) antes de alertar rendimiento anómalo.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        app_label = "beneficio"
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="uq_beneficio_recipe_code"),
            models.CheckConstraint(
                condition=models.Q(expected_yield_pct__gt=0) & models.Q(expected_yield_pct__lte=100),
                name="ck_beneficio_yield_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code}: {self.input_item} → {self.output_item} ({self.expected_yield_pct}%)"


class OrderStatus(models.TextChoices):
    DRAFT = "DRAFT", "Borrador"
    IN_PROCESS = "IN_PROCESS", "En proceso (insumo consumido)"
    DONE = "DONE", "Cerrada"
    CANCELLED = "CANCELLED", "Anulada"


class ProcessingOrder(Syncable):
    # Operativo: la orden de beneficio (pergamino→oro) se origina en el nodo y sube como evento.
    company = models.ForeignKey(
        OrgUnit, on_delete=models.PROTECT, related_name="beneficio_orders",
    )
    recipe = models.ForeignKey(
        TransformationRecipe, on_delete=models.PROTECT, related_name="orders",
    )
    reference = models.CharField(max_length=40)
    input_warehouse = models.ForeignKey(
        "inventarios.Warehouse", on_delete=models.PROTECT, related_name="beneficio_inputs",
    )
    output_warehouse = models.ForeignKey(
        "inventarios.Warehouse", on_delete=models.PROTECT, related_name="beneficio_outputs",
    )
    input_qty = models.DecimalField(
        max_digits=14, decimal_places=2, help_text="Cantidad de insumo (en la UoM del ítem).",
    )
    output_qty = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        help_text="Cantidad real producida (se fija al cerrar).",
    )
    status = models.CharField(
        max_length=16, choices=OrderStatus.choices, default=OrderStatus.DRAFT, db_index=True,
    )
    input_cost_total = models.DecimalField(
        max_digits=18, decimal_places=6, default=Decimal("0"),
        help_text="Costo kardex del insumo consumido (se captura al iniciar).",
    )
    output_unit_cost = models.DecimalField(
        max_digits=18, decimal_places=6, null=True, blank=True,
        help_text="Costo unitario absorbido del producto (costo insumo / salida real).",
    )
    yield_pct = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        help_text="Rendimiento real (%).",
    )
    shrinkage_qty = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True, help_text="Merma (entrada − salida).",
    )
    issue_movement_id = models.PositiveIntegerField(null=True, blank=True)
    receive_movement_id = models.PositiveIntegerField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="beneficio_orders_created",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "beneficio"
        constraints = [
            models.UniqueConstraint(fields=["company", "reference"], name="uq_beneficio_order_ref"),
        ]
        indexes = [models.Index(fields=["company", "status"])]

    def __str__(self) -> str:
        return f"Orden {self.reference} ({self.status})"
