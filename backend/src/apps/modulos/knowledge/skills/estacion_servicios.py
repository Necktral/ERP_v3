"""Skills de Estación de Servicio: combustible vendido hoy (córdobas y litros)."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.modulos.estacion_servicios.models import FuelDispense, FuelSale, FuelSaleStatus

from . import skill


@skill(
    key="estacion.combustible_hoy",
    description="Cuánto combustible se vendió hoy (en córdobas y en litros).",
    required_permission="fuel.sale.read",
    keywords=(
        "combustible vendido hoy", "cuanto combustible", "ventas de combustible", "litros vendidos hoy",
        "cuantos litros", "venta de combustible hoy", "diesel vendido",
    ),
    examples=("¿Cuánto combustible se vendió hoy?", "Cuántos litros se vendieron hoy"),
)
def combustible_hoy(*, request, args):
    company = request.company
    hoy = timezone.localdate()
    ventas = FuelSale.objects.filter(company=company, status=FuelSaleStatus.ACTIVE, created_at__date=hoy)
    n = ventas.count()
    total = ventas.aggregate(t=Sum("total_amount"))["t"] or Decimal("0.00")
    litros = (
        FuelDispense.objects.filter(company=company, occurred_at__date=hoy).aggregate(t=Sum("liters"))["t"]
        or Decimal("0.000")
    )
    answer = (
        f"Hoy {company.name} vendió C${total:,.2f} de combustible en {n} venta{'s' if n != 1 else ''} "
        f"({litros:,.2f} litros despachados)."
    )
    return {"answer": answer, "data": {"fecha": str(hoy), "ventas": n, "total": str(total), "litros": str(litros)}}
