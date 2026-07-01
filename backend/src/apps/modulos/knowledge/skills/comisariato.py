"""Skills del Comisariato: cuentas de crédito (el saldo vive en cartera/CxC)."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum

from apps.modulos.comisariato.models import CustomerCreditAccount

from . import skill


@skill(
    key="comisariato.cuentas",
    description="Cuántas cuentas de crédito de comisariato hay y el límite total otorgado.",
    required_permission="comisariato.read",
    keywords=(
        "cuentas de comisariato", "cuantas cuentas de comisariato", "comisariato cuentas",
        "credito de comisariato", "limite de comisariato",
    ),
    examples=("¿Cuántas cuentas de comisariato hay?",),
)
def cuentas(*, request, args):
    company = request.company
    qs = CustomerCreditAccount.objects.filter(company=company)
    n = qs.count()
    limite = qs.aggregate(t=Sum("credit_limit"))["t"] or Decimal("0.00")
    answer = (
        f"{company.name} tiene {n} cuenta{'s' if n != 1 else ''} de crédito en el comisariato, "
        f"con un límite total de C${limite:,.2f}. (El saldo adeudado se ve en Cartera/CxC.)"
    )
    return {"answer": answer, "data": {"cuentas": n, "limite_total": str(limite)}}
