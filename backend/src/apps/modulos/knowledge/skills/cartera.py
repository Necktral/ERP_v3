"""Skills de Cartera: cuentas por cobrar (CxC) y por pagar (CxP)."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import F, Sum

from apps.kernels.portfolio.models import ObligationStatus, Payable, Receivable

from . import skill

# Estados con saldo vivo (excluye PAID / WRITTEN_OFF / CANCELLED).
_ACTIVOS = (
    ObligationStatus.PENDING,
    ObligationStatus.PARTIAL,
    ObligationStatus.OVERDUE,
    ObligationStatus.DISPUTED,
    ObligationStatus.RESTRUCTURED,
)

_OUTSTANDING = (
    F("principal_amount") + F("interest_amount") + F("fee_amount") + F("penalty_amount") - F("allocated_amount")
)


def _saldo(company, model):
    qs = model.objects.filter(company=company, status__in=_ACTIVOS)
    total = qs.aggregate(t=Sum(_OUTSTANDING))["t"] or Decimal("0.00")
    return qs.count(), total


@skill(
    key="cartera.cxc",
    description="Cuánto deben los clientes en total (cuentas por cobrar, CxC).",
    required_permission="portfolio.receivable.read",
    keywords=(
        "cuanto me deben", "cuentas por cobrar", "cuanto deben los clientes", "saldo por cobrar",
        "cxc", "deuda de clientes",
    ),
    examples=("¿Cuánto me deben los clientes?", "Total de cuentas por cobrar"),
)
def cxc(*, request, args):
    company = request.company
    n, total = _saldo(company, Receivable)
    answer = (
        f"Los clientes de {company.name} deben C${total:,.2f} en total "
        f"({n} cuenta{'s' if n != 1 else ''} por cobrar con saldo)."
    )
    return {"answer": answer, "data": {"cuentas": n, "total": str(total)}}


@skill(
    key="cartera.cxp",
    description="Cuánto debe la empresa a sus proveedores en total (cuentas por pagar, CxP).",
    required_permission="portfolio.payable.read",
    keywords=(
        "cuanto debo", "cuentas por pagar", "cuanto le debo a proveedores", "saldo por pagar",
        "cxp", "deuda con proveedores",
    ),
    examples=("¿Cuánto debo a proveedores?", "Total de cuentas por pagar"),
)
def cxp(*, request, args):
    company = request.company
    n, total = _saldo(company, Payable)
    answer = (
        f"{company.name} debe C${total:,.2f} a proveedores en total "
        f"({n} cuenta{'s' if n != 1 else ''} por pagar con saldo)."
    )
    return {"answer": answer, "data": {"cuentas": n, "total": str(total)}}
