"""Skills de Caja/POS (retail_pos): corte del día y caja abierta."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.modulos.retail_pos.models import PosSession, PosSessionStatus, PosTicket, PosTicketStatus

from . import skill


@skill(
    key="pos.corte_hoy",
    description="Corte de caja POS de hoy: cuántos tickets cerrados y el total cobrado.",
    required_permission="sales.pos.report",
    keywords=(
        "corte de caja", "corte del dia", "cuantos tickets", "tickets de hoy", "ventas pos",
        "corte de hoy", "cuanto cobre en caja",
    ),
    examples=("¿Cómo va el corte de caja de hoy?", "Cuántos tickets se hicieron hoy"),
)
def corte_hoy(*, request, args):
    company = request.company
    hoy = timezone.localdate()
    qs = PosTicket.objects.filter(company=company, status=PosTicketStatus.CLOSED, created_at__date=hoy)
    n = qs.count()
    total = qs.aggregate(t=Sum("total_amount"))["t"] or Decimal("0.00")
    answer = f"Hoy se cerraron {n} ticket{'s' if n != 1 else ''} en caja por C${total:,.2f} en {company.name}."
    return {"answer": answer, "data": {"fecha": str(hoy), "tickets": n, "total": str(total)}}


@skill(
    key="pos.caja_abierta",
    description="Si hay sesiones de caja abiertas y cuántas.",
    required_permission="sales.pos.report",
    keywords=("caja abierta", "hay caja abierta", "cajas abiertas", "sesiones de caja abiertas"),
    examples=("¿Hay alguna caja abierta?",),
)
def caja_abierta(*, request, args):
    company = request.company
    n = PosSession.objects.filter(company=company, status=PosSessionStatus.OPEN).count()
    if n:
        answer = f"Hay {n} caja{'s' if n != 1 else ''} abierta{'s' if n != 1 else ''} en {company.name}."
    else:
        answer = f"No hay cajas abiertas en {company.name}."
    return {"answer": answer, "data": {"abiertas": n, "empresa": company.name}}
