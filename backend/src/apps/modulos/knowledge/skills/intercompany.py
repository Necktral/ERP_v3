"""Skills Intercompany (kernel accounting): cruces entre empresas pendientes de conciliar."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Q, Sum

from apps.kernels.accounting.models import IntercompanyTransaction

from . import skill

# Cruces que todavía no quedan cerrados/confirmados (requieren atención).
_PENDIENTES = (
    IntercompanyTransaction.Status.PENDING,
    IntercompanyTransaction.Status.DIFFERENCE,
    IntercompanyTransaction.Status.DISPUTED,
)


@skill(
    key="intercompany.cruces_pendientes",
    description="Transacciones intercompany (entre empresas del grupo) pendientes de conciliar y su diferencia.",
    required_permission="accounting.intercompany.read",
    keywords=(
        "cruces pendientes", "intercompany pendiente", "transacciones entre empresas",
        "cruces entre empresas", "conciliacion intercompany", "cuentas entre empresas",
    ),
    examples=("¿Hay cruces entre empresas pendientes?", "Transacciones intercompany sin conciliar"),
)
def cruces_pendientes(*, request, args):
    company = request.company
    qs = IntercompanyTransaction.objects.filter(
        Q(source_company=company) | Q(target_company=company), status__in=_PENDIENTES
    )
    n = qs.count()
    total = qs.aggregate(t=Sum("amount"))["t"] or Decimal("0.00")
    con_diferencia = qs.filter(status=IntercompanyTransaction.Status.DIFFERENCE).count()
    if n:
        answer = (
            f"{company.name} tiene {n} cruce{'s' if n != 1 else ''} intercompany pendiente"
            f"{'s' if n != 1 else ''} por C${total:,.2f}"
            + (f", de los cuales {con_diferencia} con diferencia." if con_diferencia else ".")
        )
    else:
        answer = f"{company.name} no tiene cruces intercompany pendientes."
    return {
        "answer": answer,
        "data": {"pendientes": n, "total": str(total), "con_diferencia": con_diferencia},
    }
