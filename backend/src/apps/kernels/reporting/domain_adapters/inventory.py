from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum, Value
from django.db.models.functions import Coalesce

from apps.kernels.inventarios.models import StockBalance, StockMovement
from apps.kernels.reporting.exceptions import DatasetExecutionError

from .utils import q2, q4, q6, resolve_bounds, resolve_date_range

# Tope de filas de detalle (oleada 6): los totales salen agregados de la BD
# (exactos sobre todo el rango); el detalle se corta para no materializar
# históricos completos en memoria/JSON.
MAX_DETAIL_ROWS = 5000

_MONEY = DecimalField(max_digits=18, decimal_places=2)


def _stock_balance_payload(*, company, branch, filters: dict[str, Any]) -> dict[str, Any]:
    qs = StockBalance.objects.filter(company=company, branch=branch)

    valor = ExpressionWrapper(F("qty_on_hand") * F("avg_cost"), output_field=_MONEY)
    totales = qs.aggregate(
        qty=Coalesce(Sum("qty_on_hand"), Value(Decimal("0.0000"))),
        value=Coalesce(Sum(valor), Value(Decimal("0.00"), output_field=_MONEY)),
    )

    detalle = list(
        qs.values(
            "warehouse__code", "warehouse__name", "item__sku", "item__name", "item__uom",
            "qty_on_hand", "avg_cost",
        )
        .order_by("warehouse__code", "item__sku")[: MAX_DETAIL_ROWS + 1]
    )

    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    for bal in detalle[:MAX_DETAIL_ROWS]:
        qty = Decimal(bal["qty_on_hand"])
        avg_cost = Decimal(bal["avg_cost"])
        rows.append(
            {
                "warehouse_code": str(bal["warehouse__code"]),
                "warehouse_name": str(bal["warehouse__name"]),
                "sku": str(bal["item__sku"]),
                "item_name": str(bal["item__name"]),
                "uom": str(bal["item__uom"]),
                "qty_on_hand": q4(qty),
                "avg_cost": q6(avg_cost),
                "stock_value": q2(qty * avg_cost),
            }
        )
    if len(detalle) > MAX_DETAIL_ROWS:
        warnings.append(
            f"Detalle truncado a {MAX_DETAIL_ROWS} filas; los totales cubren todo el inventario."
        )

    return {
        "grain": "warehouse_item",
        "dimensions": ["warehouse_code", "warehouse_name", "sku", "item_name", "uom"],
        "measures": ["qty_on_hand", "avg_cost", "stock_value"],
        "rows": rows,
        "totals": {
            "qty_on_hand": q4(Decimal(totales["qty"])),
            "stock_value": q2(Decimal(totales["value"])),
        },
        "warnings": warnings,
        "source_summary": {"source_modules": ["INVENTORY"]},
        "effective_filters": {},
    }


def _movements_payload(*, company, branch, filters: dict[str, Any]) -> dict[str, Any]:
    date_from, date_to = resolve_date_range(filters)
    start, end = resolve_bounds(date_from=date_from, date_to=date_to)

    qs = StockMovement.objects.filter(
        company=company, branch=branch, created_at__gte=start, created_at__lte=end
    )

    totales = qs.aggregate(
        movement_count=Count("id"),
        qty_delta=Coalesce(Sum("qty_delta"), Value(Decimal("0.0000"))),
        total_cost=Coalesce(Sum("total_cost"), Value(Decimal("0.00"), output_field=_MONEY)),
    )

    detalle = list(
        qs.values(
            "movement_type", "warehouse__code", "item__sku", "item__name",
            "qty_delta", "unit_cost", "total_cost", "source_module",
        )
        .order_by("created_at", "id")[: MAX_DETAIL_ROWS + 1]
    )

    warnings: list[str] = []
    rows: list[dict[str, Any]] = [
        {
            "movement_type": str(mov["movement_type"]),
            "warehouse_code": str(mov["warehouse__code"]),
            "sku": str(mov["item__sku"]),
            "item_name": str(mov["item__name"]),
            "qty_delta": q4(Decimal(mov["qty_delta"])),
            "unit_cost": q6(Decimal(mov["unit_cost"])),
            "total_cost": q2(Decimal(mov["total_cost"])),
            "source_module": str(mov["source_module"] or ""),
        }
        for mov in detalle[:MAX_DETAIL_ROWS]
    ]
    if len(detalle) > MAX_DETAIL_ROWS:
        warnings.append(
            f"Detalle truncado a {MAX_DETAIL_ROWS} movimientos; los totales cubren TODO el rango. "
            "Acotá el rango de fechas para ver el detalle completo."
        )

    return {
        "grain": "movement",
        "dimensions": ["movement_type", "warehouse_code", "sku", "item_name", "source_module"],
        "measures": ["qty_delta", "unit_cost", "total_cost"],
        "rows": rows,
        "totals": {
            "movement_count": int(totales["movement_count"]),
            "qty_delta": q4(Decimal(totales["qty_delta"])),
            "total_cost": q2(Decimal(totales["total_cost"])),
        },
        "warnings": warnings,
        "source_summary": {"source_modules": ["INVENTORY"]},
        "effective_filters": {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        },
    }


def run_dataset(*, dataset_key: str, company, branch, filters: dict) -> dict[str, Any]:
    if dataset_key == "inventory.stock_balance.current":
        return _stock_balance_payload(company=company, branch=branch, filters=filters)
    if dataset_key == "inventory.movements.period":
        return _movements_payload(company=company, branch=branch, filters=filters)
    raise DatasetExecutionError(f"Dataset Inventory no soportado: {dataset_key}")
