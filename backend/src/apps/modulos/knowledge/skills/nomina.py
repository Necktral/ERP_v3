"""Skills de Nómina: último período de planilla."""
from __future__ import annotations

from decimal import Decimal

from apps.kernels.nomina.models import PayrollPeriod

from . import skill


@skill(
    key="nomina.ultimo_periodo",
    description="Cuál es el último período de planilla, su estado y el neto total a pagar.",
    required_permission="nomina.period.read",
    keywords=(
        "ultima planilla", "ultimo periodo de planilla", "ultima nomina", "cuanto fue la planilla",
        "neto de la planilla", "total de la nomina",
    ),
    examples=("¿Cuál fue la última planilla?", "Cuánto fue el neto de la última nómina"),
)
def ultimo_periodo(*, request, args):
    company = request.company
    p = (
        PayrollPeriod.objects.filter(company=company)
        .order_by("-year", "-month", "-id")
        .first()
    )
    if p is None:
        return {"answer": f"{company.name} todavía no tiene períodos de planilla.", "data": {}}
    neto = p.total_net or Decimal("0.00")
    answer = (
        f"El último período de planilla de {company.name} es {p.month:02d}/{p.year} "
        f"(estado: {p.status}); neto total a pagar C${neto:,.2f}."
    )
    return {
        "answer": answer,
        "data": {
            "anio": p.year,
            "mes": p.month,
            "estado": p.status,
            "neto": str(neto),
            "bruto": str(p.total_gross or Decimal("0.00")),
        },
    }
