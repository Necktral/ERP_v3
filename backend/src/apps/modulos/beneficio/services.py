"""Servicios del beneficio: orquestación sobre el kardex del kernel inventarios.

Ciclo: crear orden (DRAFT) → iniciar (consume el insumo vía ``post_issue``; el costo
kardex consumido queda capturado en `input_cost_total`) → cerrar (produce la salida vía
``post_receive`` con costo ABSORBIDO = costo insumo / libras reales; calcula merma y
rendimiento; si el rendimiento sale del rango esperado, dispara alerta YIELD_ANOMALY).
Anular solo en DRAFT (una orden iniciada ya consumió café: lo honesto es cerrarla con
lo que salió, no borrar el consumo).
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.utils import timezone

from apps.kernels.inventarios.models import StockMovement
from apps.kernels.inventarios.services import post_issue, post_receive
from apps.modulos.iam.models import OrgUnit
from apps.modulos.integration.services import publish_outbox_event

from .models import OrderStatus, ProcessingOrder, TransformationRecipe

_TWO = Decimal("0.01")


class BeneficioError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _q2(x: Decimal) -> Decimal:
    return x.quantize(_TWO, rounding=ROUND_HALF_UP)


def create_recipe(
    *, company: OrgUnit, code: str, name: str, input_item, output_item,
    expected_yield_pct: Decimal, yield_tolerance_pct: Decimal = Decimal("5.00"),
) -> TransformationRecipe:
    if input_item.company_id != company.id or output_item.company_id != company.id:
        raise BeneficioError("BEN_ITEM_SCOPE", "Los ítems pertenecen a otra empresa.")
    if input_item.pk == output_item.pk:
        raise BeneficioError("BEN_ITEMS_EQUAL", "El insumo y el producto deben ser ítems distintos.")
    if not (Decimal("0") < expected_yield_pct <= Decimal("100")):
        raise BeneficioError("BEN_YIELD_INVALID", "El rendimiento esperado debe estar entre 0 y 100%.")
    obj, _created = TransformationRecipe.objects.get_or_create(
        company=company, code=code,
        defaults={
            "name": name, "input_item": input_item, "output_item": output_item,
            "expected_yield_pct": expected_yield_pct, "yield_tolerance_pct": yield_tolerance_pct,
        },
    )
    return obj


def _next_order_reference(company: OrgUnit) -> str:
    seq = ProcessingOrder.objects.filter(company=company).count() + 1
    return f"BEN-{company.pk}-{seq:05d}"


def create_order(
    *, company: OrgUnit, recipe: TransformationRecipe, input_warehouse, output_warehouse,
    input_qty: Decimal, reference: str = "", note: str = "", actor=None,
) -> ProcessingOrder:
    if recipe.company_id != company.id:
        raise BeneficioError("BEN_RECIPE_SCOPE", "La receta pertenece a otra empresa.")
    if not recipe.is_active:
        raise BeneficioError("BEN_RECIPE_INACTIVE", "La receta está inactiva.")
    input_qty = _q2(Decimal(input_qty))
    if input_qty <= 0:
        raise BeneficioError("BEN_QTY_INVALID", "La cantidad de insumo debe ser positiva.")
    return ProcessingOrder.objects.create(
        company=company, recipe=recipe, reference=reference or _next_order_reference(company),
        input_warehouse=input_warehouse, output_warehouse=output_warehouse,
        input_qty=input_qty, note=note,
        created_by=actor if getattr(actor, "pk", None) else None,
    )


@transaction.atomic
def start_order(*, request, actor, order: ProcessingOrder) -> ProcessingOrder:
    """Consume el insumo (sale de bodega con su costo kardex) y abre el proceso."""
    if order.company_id != request.company.id:
        raise BeneficioError("BEN_ORDER_SCOPE", "La orden pertenece a otra empresa.")
    if order.status != OrderStatus.DRAFT:
        raise BeneficioError("BEN_ORDER_STATE", f"Solo un borrador se inicia (está {order.status}).")
    result = post_issue(
        request=request, actor=actor,
        warehouse_id=order.input_warehouse_id, item_id=order.recipe.input_item_id,
        qty=order.input_qty,
        idempotency_key=f"ben-issue-{order.pk}",
        note=f"Beneficio {order.reference}: consumo de insumo",
        source_module="BENEFICIO", source_type="ProcessingOrder", source_id=str(order.pk),
    )
    movement = StockMovement.objects.get(pk=result.movement_id)
    order.input_cost_total = abs(movement.total_cost)
    order.issue_movement_id = result.movement_id
    order.status = OrderStatus.IN_PROCESS
    order.started_at = timezone.now()
    order.save(update_fields=[
        "input_cost_total", "issue_movement_id", "status", "started_at", "updated_at",
    ])
    return order


@transaction.atomic
def close_order(*, request, actor, order: ProcessingOrder, output_qty: Decimal) -> ProcessingOrder:
    """Produce la salida con costo absorbido; calcula merma/rendimiento; alerta si anómalo."""
    if order.company_id != request.company.id:
        raise BeneficioError("BEN_ORDER_SCOPE", "La orden pertenece a otra empresa.")
    if order.status != OrderStatus.IN_PROCESS:
        raise BeneficioError("BEN_ORDER_STATE", f"Solo una orden en proceso se cierra (está {order.status}).")
    output_qty = _q2(Decimal(output_qty))
    if output_qty <= 0:
        raise BeneficioError("BEN_QTY_INVALID", "La cantidad producida debe ser positiva.")
    if output_qty > order.input_qty:
        raise BeneficioError(
            "BEN_OUTPUT_EXCEEDS_INPUT",
            f"La salida ({output_qty}) no puede superar el insumo ({order.input_qty}).",
        )

    unit_cost = Decimal("0")
    if order.input_cost_total > 0:
        unit_cost = (order.input_cost_total / output_qty).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
    result = post_receive(
        request=request, actor=actor,
        warehouse_id=order.output_warehouse_id, item_id=order.recipe.output_item_id,
        qty=output_qty, unit_cost=unit_cost,
        idempotency_key=f"ben-receive-{order.pk}",
        note=f"Beneficio {order.reference}: producción (costo absorbido)",
        source_module="BENEFICIO", source_type="ProcessingOrder", source_id=str(order.pk),
    )

    yield_pct = (output_qty / order.input_qty * Decimal("100")).quantize(
        _TWO, rounding=ROUND_HALF_UP
    )
    order.output_qty = output_qty
    order.output_unit_cost = unit_cost
    order.yield_pct = yield_pct
    order.shrinkage_qty = _q2(order.input_qty - output_qty)
    order.receive_movement_id = result.movement_id
    order.status = OrderStatus.DONE
    order.finished_at = timezone.now()
    order.save(update_fields=[
        "output_qty", "output_unit_cost", "yield_pct", "shrinkage_qty",
        "receive_movement_id", "status", "finished_at", "updated_at",
    ])

    # Antifraude de báscula: rendimiento fuera del rango esperado → alerta.
    deviation = abs(yield_pct - order.recipe.expected_yield_pct)
    if deviation > order.recipe.yield_tolerance_pct:
        from apps.modulos.alertas.services import AlertDraft, upsert_alert

        upsert_alert(
            company=order.company, alert_type="YIELD_ANOMALY",
            draft=AlertDraft(
                subject_type="BENEFICIO_ORDER", subject_id=str(order.pk),
                severity="CRITICAL",
                title=f"Rendimiento anómalo en {order.reference}: {yield_pct}% "
                      f"(esperado {order.recipe.expected_yield_pct}%)",
                detail=f"Entrada {order.input_qty}, salida {output_qty}, merma {order.shrinkage_qty}. "
                       f"Desviación {deviation} pp (tolerancia {order.recipe.yield_tolerance_pct} pp).",
                payload={"reference": order.reference, "yield_pct": str(yield_pct)},
            ),
        )

    publish_outbox_event(
        request=request, source_module="BENEFICIO", event_type="ProcessingOrderClosed",
        payload={
            "order_id": order.pk, "reference": order.reference,
            "input_qty": str(order.input_qty), "output_qty": str(output_qty),
            "yield_pct": str(yield_pct), "input_cost_total": str(order.input_cost_total),
            "output_unit_cost": str(unit_cost),
        },
        actor_user=actor, company=order.company, branch=getattr(request, "branch", None),
    )
    return order


def cancel_order(*, order: ProcessingOrder) -> ProcessingOrder:
    if order.status != OrderStatus.DRAFT:
        raise BeneficioError(
            "BEN_ORDER_STATE",
            "Solo un borrador se anula; una orden iniciada ya consumió insumo (cerrala con la salida real).",
        )
    order.status = OrderStatus.CANCELLED
    order.save(update_fields=["status", "updated_at"])
    return order
