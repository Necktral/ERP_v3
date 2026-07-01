"""Conteo físico de inventario (cycle count) — Ola C.

Hoja con snapshot → captura de lo contado → varianzas → aprobación SoD (quien
cuenta NO aprueba) → ajustes reales al kardex vía ``post_adjust`` con movimiento
PHYSICAL_COUNT (idempotencia determinista por línea, GL automático del kernel).

Multi-empresa: todo scoped por request.company/request.branch como el resto del
kernel; el módulo "inventory" se enciende por empresa (CompanyModule).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.modulos.audit.writer import write_event

from .models import (
    MovementType,
    PhysicalCount,
    PhysicalCountLine,
    PhysicalCountStatus,
    StockBalance,
    Warehouse,
)
from .services import post_adjust


class InventoryCountError(Exception):
    """Errores de negocio del conteo físico; el código viaja como detail."""


class InventoryCountSoDError(InventoryCountError):
    """Quien cuenta no puede aprobar las varianzas → HTTP 409."""


def _count_for_update(*, request, count_id: int) -> PhysicalCount:
    count = (
        PhysicalCount.objects.select_for_update()
        .filter(id=int(count_id), company=request.company, branch=request.branch)
        .first()
    )
    if count is None:
        raise InventoryCountError("INVENTORY_COUNT_NOT_FOUND")
    return count


def count_payload(count: PhysicalCount) -> dict[str, Any]:
    lines = []
    for ln in count.lines.select_related("item").order_by("item__sku"):
        variance = ln.variance
        lines.append(
            {
                "id": ln.id,
                "item_id": ln.item_id,
                "item_sku": ln.item.sku,
                "item_name": ln.item.name,
                "item_uom": ln.item.uom,
                "qty_expected": str(ln.qty_expected),
                "qty_counted": str(ln.qty_counted) if ln.qty_counted is not None else None,
                "variance": str(variance) if variance is not None else None,
                "movement_id": ln.movement_id,
            }
        )
    return {
        "id": count.id,
        "status": count.status,
        "warehouse_id": count.warehouse_id,
        "warehouse_name": count.warehouse.name,
        "category": count.category,
        "notes": count.notes,
        "created_by": getattr(count.created_by, "username", None),
        "counted_by": getattr(count.counted_by, "username", None),
        "approved_by": getattr(count.approved_by, "username", None),
        "created_at": count.created_at.isoformat(),
        "counted_at": count.counted_at.isoformat() if count.counted_at else None,
        "approved_at": count.approved_at.isoformat() if count.approved_at else None,
        "lines": lines,
    }


def create_physical_count(
    *,
    request,
    actor,
    warehouse_id: int,
    category: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """Genera la hoja de conteo con el snapshot de existencias de la bodega.

    Entran los artículos con saldo registrado (incluso 0, para detectar sobrantes
    de artículos que 'no deberían' estar) filtrados por categoría opcional.
    """
    company = request.company
    branch = request.branch

    with transaction.atomic():
        warehouse = Warehouse.objects.filter(
            id=int(warehouse_id), company=company, branch=branch
        ).first()
        if warehouse is None:
            raise InventoryCountError("INVENTORY_COUNT_WAREHOUSE_NOT_FOUND")

        balances = (
            StockBalance.objects.filter(company=company, branch=branch, warehouse=warehouse)
            .select_related("item")
            .order_by("item__sku")
        )
        if category:
            balances = balances.filter(item__category=category)

        rows = [(bal.item, bal.qty_on_hand) for bal in balances if bal.item.is_active]
        if not rows:
            raise InventoryCountError("INVENTORY_COUNT_NO_ITEMS")

        count = PhysicalCount.objects.create(
            company=company,
            branch=branch,
            warehouse=warehouse,
            category=category or "",
            notes=notes or "",
            created_by=actor,
        )
        PhysicalCountLine.objects.bulk_create(
            PhysicalCountLine(count=count, item=item, qty_expected=qty)
            for item, qty in rows
        )

        write_event(
            request=request,
            module="INVENTORY",
            event_type="INVENTORY_COUNT_CREATED",
            reason_code="INVENTORY_OK",
            actor_user=actor,
            subject_type="INVENTORY_COUNT",
            subject_id=str(count.id),
            metadata={"warehouse_id": warehouse.id, "category": category, "lines": len(rows)},
        )
        return count_payload(count)


def capture_physical_count(
    *, request, actor, count_id: int, lines: list[dict]
) -> dict[str, Any]:
    """Registra lo contado (re-capturable mientras no se postee).

    Quien captura queda como `counted_by` — y por SoD no podrá aprobar.
    """
    if not lines:
        raise InventoryCountError("INVENTORY_COUNT_LINES_REQUIRED")

    with transaction.atomic():
        count = _count_for_update(request=request, count_id=count_id)
        if count.status not in (PhysicalCountStatus.OPEN, PhysicalCountStatus.COUNTED):
            raise InventoryCountError("INVENTORY_COUNT_NOT_OPEN")

        by_id = {ln.id: ln for ln in count.lines.select_for_update()}
        for ln in lines:
            line = by_id.get(int(ln["line_id"]))
            if line is None:
                raise InventoryCountError("INVENTORY_COUNT_LINE_NOT_FOUND")
            qty = Decimal(str(ln["qty_counted"]))
            if qty < 0:
                raise InventoryCountError("INVENTORY_COUNT_QTY_INVALID")
            line.qty_counted = qty
            line.save(update_fields=["qty_counted"])

        if count.lines.filter(qty_counted__isnull=True).exists():
            # Captura parcial: la hoja sigue abierta hasta contar todo.
            pending = count.lines.filter(qty_counted__isnull=True).count()
            count.counted_by = actor
            count.save(update_fields=["counted_by"])
            payload = count_payload(count)
            payload["pending_lines"] = pending
            return payload

        count.status = PhysicalCountStatus.COUNTED
        count.counted_by = actor
        count.counted_at = timezone.now()
        count.save(update_fields=["status", "counted_by", "counted_at"])

        write_event(
            request=request,
            module="INVENTORY",
            event_type="INVENTORY_COUNT_CAPTURED",
            reason_code="INVENTORY_OK",
            actor_user=actor,
            subject_type="INVENTORY_COUNT",
            subject_id=str(count.id),
            metadata={"lines": len(lines)},
        )
        return count_payload(count)


def approve_physical_count(*, request, actor, count_id: int) -> dict[str, Any]:
    """COUNTED→POSTED: postea un ajuste PHYSICAL_COUNT por cada varianza ≠ 0.

    SoD: quien capturó el conteo no puede aprobarlo. El posteo fija la existencia
    en lo CONTADO (la verdad observada hoy), idempotente por línea — un reintento
    no duplica movimientos.
    """
    with transaction.atomic():
        count = _count_for_update(request=request, count_id=count_id)
        if count.status != PhysicalCountStatus.COUNTED:
            raise InventoryCountError("INVENTORY_COUNT_NOT_COUNTED")
        if (
            count.counted_by_id is not None
            and actor is not None
            and actor.id == count.counted_by_id
        ):
            raise InventoryCountSoDError("INVENTORY_COUNT_SOD_SELF_APPROVAL")

        adjusted = 0
        for line in count.lines.select_for_update().select_related("item"):
            # Varianza contra la existencia ACTUAL (no el snapshot): si alguien ya
            # movió stock y lo contado coincide, no hay nada que ajustar.
            bal = StockBalance.objects.filter(
                company=count.company, branch=count.branch,
                warehouse=count.warehouse, item=line.item,
            ).first()
            current = bal.qty_on_hand if bal else Decimal("0.0000")
            if line.qty_counted == current:
                continue
            qty_counted = line.qty_counted
            if qty_counted is None:
                continue
            result = post_adjust(
                request=request,
                actor=actor,
                warehouse_id=count.warehouse_id,
                item_id=line.item_id,
                new_qty_on_hand=qty_counted,
                idempotency_key=f"count:{count.id}:line:{line.id}",
                note=f"Conteo físico #{count.id}",
                movement_type=MovementType.PHYSICAL_COUNT,
            )
            line.movement_id = result.movement_id
            line.save(update_fields=["movement_id"])
            adjusted += 1

        count.status = PhysicalCountStatus.POSTED
        count.approved_by = actor
        count.approved_at = timezone.now()
        count.save(update_fields=["status", "approved_by", "approved_at"])

        write_event(
            request=request,
            module="INVENTORY",
            event_type="INVENTORY_COUNT_POSTED",
            reason_code="INVENTORY_OK",
            actor_user=actor,
            subject_type="INVENTORY_COUNT",
            subject_id=str(count.id),
            metadata={"adjusted_lines": adjusted},
        )
        payload = count_payload(count)
        payload["adjusted_lines"] = adjusted
        return payload


def cancel_physical_count(*, request, actor, count_id: int) -> dict[str, Any]:
    with transaction.atomic():
        count = _count_for_update(request=request, count_id=count_id)
        if count.status not in (PhysicalCountStatus.OPEN, PhysicalCountStatus.COUNTED):
            raise InventoryCountError("INVENTORY_COUNT_NOT_OPEN")
        count.status = PhysicalCountStatus.CANCELLED
        count.cancelled_at = timezone.now()
        count.save(update_fields=["status", "cancelled_at"])
        write_event(
            request=request,
            module="INVENTORY",
            event_type="INVENTORY_COUNT_CANCELLED",
            reason_code="INVENTORY_OK",
            actor_user=actor,
            subject_type="INVENTORY_COUNT",
            subject_id=str(count.id),
            metadata={},
        )
        return {"id": count.id, "status": count.status}


# --------------------------------------------------------------------------- valorización

def inventory_valuation(*, company, branch, warehouse_id: int | None = None) -> dict[str, Any]:
    """Valorización del inventario: Σ existencia × costo promedio (política de costo
    versionada del kernel). Agregado por bodega y categoría; solo lectura.
    """
    qs = (
        StockBalance.objects.filter(company=company, branch=branch)
        .select_related("item", "warehouse")
        .exclude(qty_on_hand=0)
    )
    if warehouse_id:
        qs = qs.filter(warehouse_id=int(warehouse_id))

    total = Decimal("0.00")
    by_warehouse: dict[int, dict] = {}
    by_category: dict[str, dict] = {}
    detail = []
    for bal in qs:
        value = (Decimal(bal.qty_on_hand) * Decimal(bal.avg_cost)).quantize(Decimal("0.01"))
        total += value
        wh = by_warehouse.setdefault(
            bal.warehouse_id,
            {"warehouse_id": bal.warehouse_id, "warehouse_name": bal.warehouse.name,
             "items": 0, "value": Decimal("0.00")},
        )
        wh["items"] += 1
        wh["value"] += value
        cat_key = bal.item.category or "(sin categoría)"
        cat = by_category.setdefault(cat_key, {"category": cat_key, "items": 0, "value": Decimal("0.00")})
        cat["items"] += 1
        cat["value"] += value
        detail.append(
            {
                "item_id": bal.item_id,
                "sku": bal.item.sku,
                "name": bal.item.name,
                "category": bal.item.category,
                "warehouse_id": bal.warehouse_id,
                "warehouse_name": bal.warehouse.name,
                "qty_on_hand": str(bal.qty_on_hand),
                "avg_cost": str(bal.avg_cost),
                "value": str(value),
            }
        )

    def _ser(group: dict) -> dict:
        return {**group, "value": str(group["value"].quantize(Decimal("0.01")))}

    detail.sort(key=lambda r: Decimal(str(r["value"])), reverse=True)
    return {
        "total_value": str(total.quantize(Decimal("0.01"))),
        "by_warehouse": [_ser(g) for g in by_warehouse.values()],
        "by_category": sorted((_ser(g) for g in by_category.values()), key=lambda g: g["category"]),
        "detail": detail,
    }
