"""Resolución de precio de venta con listas de precios (única fuente para vender).

Precedencia (de más específico a más general):
  1. lista asignada al PARTY (cliente concreto),
  2. lista asignada al SEGMENTO (EMPLOYEE/PRODUCER/PUBLIC del comisariato),
  3. mayoreo del ítem (``wholesale_price`` si qty ≥ ``wholesale_min_qty``),
  4. precio base (``sale_price``).
Dentro de una lista gana el tramo con el MAYOR ``min_qty`` alcanzado por la cantidad.
Las listas se filtran por moneda de la venta: una lista USD no aplica a una venta NIO.

Invariante anti-fraude intacta: el precio lo resuelve SIEMPRE el servidor; el cliente
jamás manda precios (salvo override con permiso explícito, que se audita aparte).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .models import InventoryItem, PriceListAssignment, PriceListItem


def _best_listed_price(
    *, company, item: InventoryItem, qty: Decimal, currency: str,
    party=None, segment: str = "",
) -> Optional[Decimal]:
    flt = {
        "company": company, "is_active": True,
        "pricelist__is_active": True, "pricelist__currency": currency,
    }
    if party is not None:
        flt["party"] = party
    else:
        flt["party__isnull"] = True
        flt["segment"] = segment
    pricelist_ids = list(
        PriceListAssignment.objects.filter(**flt).values_list("pricelist_id", flat=True)
    )
    if not pricelist_ids:
        return None
    row = (
        PriceListItem.objects
        .filter(pricelist_id__in=pricelist_ids, item=item, min_qty__lte=qty)
        .order_by("-min_qty", "price")
        .first()
    )
    return row.price if row else None


def resolve_sale_price(
    *, company, item: InventoryItem, qty: Decimal, party=None, segment: str = "",
    currency: str = "NIO",
) -> Optional[Decimal]:
    """Precio de venta efectivo para (ítem, cantidad, cliente). ``None`` = sin precio
    definido (el llamador decide si eso es error, como hace la caja POS)."""
    qty = Decimal(qty)
    if party is not None:
        price = _best_listed_price(
            company=company, item=item, qty=qty, currency=currency, party=party,
        )
        if price is not None:
            return price
    if segment:
        price = _best_listed_price(
            company=company, item=item, qty=qty, currency=currency, segment=segment,
        )
        if price is not None:
            return price
    if (
        item.wholesale_price is not None
        and item.wholesale_min_qty is not None
        and qty >= item.wholesale_min_qty
    ):
        return item.wholesale_price
    return item.sale_price
