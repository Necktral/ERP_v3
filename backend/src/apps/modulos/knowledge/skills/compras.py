"""Skills de Compras: órdenes de compra pendientes."""
from __future__ import annotations

from apps.modulos.compras.models import PurchaseOrder, PurchaseOrderStatus

from . import skill

_PENDIENTES = (
    PurchaseOrderStatus.PENDING_APPROVAL,
    PurchaseOrderStatus.APPROVED,
    PurchaseOrderStatus.SENT,
    PurchaseOrderStatus.PARTIALLY_RECEIVED,
)


@skill(
    key="compras.ordenes_pendientes",
    description="Cuántas órdenes de compra están pendientes (en aprobación, aprobadas, enviadas o recibidas parcial).",
    required_permission="procurement.order.read",
    keywords=(
        "ordenes de compra pendientes", "cuantas ordenes de compra", "compras pendientes",
        "ordenes pendientes", "oc pendientes",
    ),
    examples=("¿Cuántas órdenes de compra pendientes hay?",),
)
def ordenes_pendientes(*, request, args):
    from django.db.models import Count

    company = request.company
    qs = PurchaseOrder.objects.filter(company=company, status__in=_PENDIENTES)
    n = qs.count()
    por_estado = {
        row["status"]: row["c"]
        for row in qs.values("status").annotate(c=Count("id")).order_by("status")
    }
    answer = f"{company.name} tiene {n} orden{'es' if n != 1 else ''} de compra pendiente{'s' if n != 1 else ''}."
    return {"answer": answer, "data": {"total": n, "por_estado": por_estado}}
