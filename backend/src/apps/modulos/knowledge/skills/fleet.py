"""Skills de Flota: activos que requieren mantenimiento + documentos vencidos, y combustible del mes."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.modulos.fleet.models import AssetStatus, DocumentStatus, FleetAsset, FleetDocument, FuelLog

from . import skill


@skill(
    key="fleet.mantenimiento_pendiente",
    description="Activos de flota que requieren mantenimiento y cuántos documentos están vencidos o por vencer.",
    required_permission="fleet.asset.read",
    keywords=(
        "mantenimiento pendiente", "activos por mantener", "mantenimiento de flota", "documentos vencidos",
        "vehiculos en mantenimiento", "flota en mantenimiento", "mantenimiento de vehiculos",
        "necesitan mantenimiento", "activos necesitan mantenimiento",
    ),
    examples=("¿Qué activos necesitan mantenimiento?", "Hay documentos de flota vencidos"),
)
def mantenimiento_pendiente(*, request, args):
    company = request.company
    por_mantener = FleetAsset.objects.filter(
        company=company, status__in=(AssetStatus.MAINTENANCE_DUE, AssetStatus.IN_MAINTENANCE)
    ).count()
    docs = FleetDocument.objects.filter(
        company=company, status__in=(DocumentStatus.EXPIRING, DocumentStatus.EXPIRED)
    ).count()
    answer = (
        f"En {company.name}, {por_mantener} activo{'s' if por_mantener != 1 else ''} de flota "
        f"requiere{'n' if por_mantener != 1 else ''} mantenimiento y hay {docs} "
        f"documento{'s' if docs != 1 else ''} vencido{'s' if docs != 1 else ''} o por vencer."
    )
    return {"answer": answer, "data": {"por_mantener": por_mantener, "documentos_vencidos": docs}}


@skill(
    key="fleet.combustible_periodo",
    description="Combustible consumido por la flota este mes: litros y costo total.",
    required_permission="fleet.cost.read",
    keywords=(
        "combustible de la flota", "combustible del mes", "cuanto combustible consumio la flota",
        "consumo de combustible de la flota", "gasto de combustible flota", "litros de la flota",
    ),
    examples=("¿Cuánto combustible consumió la flota este mes?", "Gasto de combustible de la flota"),
)
def combustible_periodo(*, request, args):
    company = request.company
    hoy = timezone.localdate()
    qs = FuelLog.objects.filter(company=company, occurred_at__year=hoy.year, occurred_at__month=hoy.month)
    litros = qs.aggregate(t=Sum("liters"))["t"] or Decimal("0.00")
    costo = qs.aggregate(t=Sum("total_cost"))["t"] or Decimal("0.00")
    answer = (
        f"Este mes la flota de {company.name} consumió {litros:,.2f} litros de combustible "
        f"por C${costo:,.2f}."
    )
    return {"answer": answer, "data": {"fecha": str(hoy), "litros": str(litros), "costo": str(costo)}}
