"""Skills de Finca: órdenes de trabajo de campo por estado (con jornales) y lotes/área sembrada.

Las fincas son OrgUnit de tipo BRANCH; se acotan a la empresa del request con `finca__parent=company`
(mismo patrón que las vistas de finca).
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum

from apps.modulos.finca.models import Plot, WorkOrder

from . import skill


@skill(
    key="finca.ordenes_trabajo",
    description="Órdenes de trabajo de campo por estado (planificadas, en proceso, hechas) y el total de jornales.",
    required_permission="finca.work.read",
    keywords=(
        "ordenes de trabajo", "ordenes de campo", "cuantas ordenes de trabajo", "labores de campo",
        "trabajo de campo", "ordenes de finca", "jornales del campo",
    ),
    examples=("¿Cuántas órdenes de trabajo hay?", "Cuántos jornales se han usado en el campo"),
)
def ordenes_trabajo(*, request, args):
    company = request.company
    qs = WorkOrder.objects.filter(finca__parent=company)
    total = qs.count()
    planned = qs.filter(status=WorkOrder.Status.PLANNED).count()
    in_progress = qs.filter(status=WorkOrder.Status.IN_PROGRESS).count()
    done = qs.filter(status=WorkOrder.Status.DONE).count()
    jornales = qs.aggregate(t=Sum("jornales"))["t"] or Decimal("0.00")
    ordenes = "orden" if total == 1 else "órdenes"
    answer = (
        f"{company.name} tiene {total} {ordenes} de trabajo de campo: "
        f"{planned} planificada{'s' if planned != 1 else ''}, {in_progress} en proceso, "
        f"{done} hecha{'s' if done != 1 else ''} ({jornales:,.2f} jornales en total)."
    )
    return {
        "answer": answer,
        "data": {
            "total": total,
            "planificadas": planned,
            "en_proceso": in_progress,
            "hechas": done,
            "jornales": str(jornales),
        },
    }


@skill(
    key="finca.lotes_area",
    description="Lotes activos de las fincas y el total de manzanas sembradas.",
    required_permission="finca.plot.read",
    keywords=(
        "lotes activos", "cuantos lotes", "manzanas sembradas", "area sembrada", "cuantas manzanas",
        "lotes de la finca", "area de las fincas",
    ),
    examples=("¿Cuántos lotes hay?", "Cuántas manzanas están sembradas"),
)
def lotes_area(*, request, args):
    company = request.company
    qs = Plot.objects.filter(finca__parent=company, is_active=True)
    n = qs.count()
    area = qs.aggregate(t=Sum("area_manzanas"))["t"] or Decimal("0.00")
    answer = (
        f"{company.name} tiene {n} lote{'s' if n != 1 else ''} activo{'s' if n != 1 else ''} "
        f"con {area:,.2f} manzanas sembradas."
    )
    return {"answer": answer, "data": {"lotes": n, "manzanas": str(area)}}
