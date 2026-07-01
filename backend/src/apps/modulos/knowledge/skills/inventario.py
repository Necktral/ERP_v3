"""Skills de Inventario: stock bajo, valor del inventario, existencias de un producto."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import F, Sum

from apps.kernels.inventarios.models import InventoryItem, StockBalance

from . import skill


def _on_hand_by_item(company) -> dict[int, Decimal]:
    rows = StockBalance.objects.filter(company=company).values("item_id").annotate(q=Sum("qty_on_hand"))
    return {r["item_id"]: (r["q"] or Decimal("0")) for r in rows}


@skill(
    key="inventario.stock_bajo",
    description="Qué productos están por agotarse (existencia por debajo del punto de reorden).",
    required_permission="inventory.balance.read",
    keywords=(
        "stock bajo", "productos por agotarse", "que esta por agotarse", "productos bajos",
        "que falta comprar", "que productos faltan", "punto de reorden",
    ),
    examples=("¿Qué productos están por agotarse?", "Productos con stock bajo"),
)
def stock_bajo(*, request, args):
    company = request.company
    on_hand = _on_hand_by_item(company)
    items = InventoryItem.objects.filter(company=company, reorder_point__gt=0).values(
        "id", "name", "sku", "reorder_point"
    )
    bajos = []
    for it in items:
        q = on_hand.get(it["id"], Decimal("0"))
        if q <= it["reorder_point"]:
            bajos.append({"sku": it["sku"], "nombre": it["name"], "existencia": str(q), "reorden": str(it["reorder_point"])})
    bajos.sort(key=lambda x: x["nombre"])
    n = len(bajos)
    if n:
        muestra = ", ".join(f"{b['nombre']} ({b['existencia']})" for b in bajos[:10])
        answer = f"Hay {n} producto{'s' if n != 1 else ''} por agotarse en {company.name}: {muestra}" + (" …" if n > 10 else ".")
    else:
        answer = f"No hay productos por debajo del punto de reorden en {company.name}."
    return {"answer": answer, "data": {"total": n, "productos": bajos[:50]}}


@skill(
    key="inventario.valor",
    description="Cuál es el valor total del inventario (existencias × costo promedio).",
    required_permission="inventory.balance.read",
    keywords=("valor del inventario", "cuanto vale el inventario", "valor de inventario", "valorizacion del inventario"),
    examples=("¿Cuánto vale el inventario?",),
)
def valor(*, request, args):
    company = request.company
    val = StockBalance.objects.filter(company=company).aggregate(v=Sum(F("qty_on_hand") * F("avg_cost")))["v"] or Decimal("0")
    answer = f"El inventario de {company.name} vale C${val:,.2f} (existencias × costo promedio)."
    return {"answer": answer, "data": {"valor": str(val), "empresa": company.name}}


@skill(
    key="inventario.existencias_producto",
    description="Cuántas existencias hay de un producto (por nombre o código). Arg: nombre.",
    required_permission="inventory.balance.read",
    keywords=("existencias de", "cuanto stock hay de", "cuantas unidades de", "stock de"),
    examples=("¿Cuántas existencias hay de arroz?", "Stock de cemento"),
    args_schema=("nombre",),
)
def existencias_producto(*, request, args):
    company = request.company
    nombre = (args or {}).get("nombre", "").strip()
    if not nombre:
        return {"answer": "Decime el nombre o código del producto para consultar sus existencias.", "data": {}}
    items = InventoryItem.objects.filter(company=company).filter(
        name__icontains=nombre
    ) | InventoryItem.objects.filter(company=company, sku__icontains=nombre)
    items = items.distinct()[:5]
    on_hand = _on_hand_by_item(company)
    if not items:
        return {"answer": f"No encontré ningún producto que coincida con «{nombre}».", "data": {"nombre": nombre}}
    detalle = [{"sku": it.sku, "nombre": it.name, "existencia": str(on_hand.get(it.id, Decimal("0")))} for it in items]
    if len(detalle) == 1:
        d = detalle[0]
        answer = f"Hay {d['existencia']} de «{d['nombre']}» ({d['sku']}) en {company.name}."
    else:
        answer = "Encontré varios productos: " + "; ".join(f"{d['nombre']}: {d['existencia']}" for d in detalle) + "."
    return {"answer": answer, "data": {"nombre": nombre, "resultados": detalle}}
