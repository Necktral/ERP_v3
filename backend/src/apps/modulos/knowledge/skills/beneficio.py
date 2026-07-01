"""Skills de Beneficio (procesamiento de café): órdenes en proceso/cerradas, rendimiento y merma."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Avg, Sum

from apps.modulos.beneficio.models import OrderStatus, ProcessingOrder

from . import skill


@skill(
    key="beneficio.ordenes_proceso",
    description="Órdenes de beneficio en proceso y cerradas, con el rendimiento promedio y la merma total.",
    required_permission="beneficio.order.read",
    keywords=(
        "ordenes de beneficio", "beneficio en proceso", "rendimiento de beneficio",
        "merma de beneficio", "procesamiento de cafe", "ordenes de proceso", "como va el beneficio",
    ),
    examples=("¿Cuántas órdenes de beneficio hay en proceso?", "Cómo va el rendimiento del beneficio"),
)
def ordenes_proceso(*, request, args):
    company = request.company
    en_proceso = ProcessingOrder.objects.filter(company=company, status=OrderStatus.IN_PROCESS).count()
    hechas = ProcessingOrder.objects.filter(company=company, status=OrderStatus.DONE)
    n_hechas = hechas.count()
    agg = hechas.aggregate(rend=Avg("yield_pct"), merma=Sum("shrinkage_qty"))
    rend = agg["rend"]
    merma = agg["merma"] or Decimal("0.00")
    rend_txt = f"{rend:.1f}%" if rend is not None else "sin dato"
    ordenes = "orden" if en_proceso == 1 else "órdenes"
    answer = (
        f"{company.name} tiene {en_proceso} {ordenes} de beneficio en proceso "
        f"y {n_hechas} cerrada{'s' if n_hechas != 1 else ''} (rendimiento promedio {rend_txt}, "
        f"merma {merma:,.2f})."
    )
    return {
        "answer": answer,
        "data": {
            "en_proceso": en_proceso,
            "cerradas": n_hechas,
            "rendimiento_prom": str(rend) if rend is not None else None,
            "merma": str(merma),
        },
    }
