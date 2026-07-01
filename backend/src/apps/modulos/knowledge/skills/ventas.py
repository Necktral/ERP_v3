"""Skills de Ventas/Caja: ventas del día y del mes (facturas emitidas)."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.kernels.facturacion.models import BillingDocument, DocStatus, DocType

from . import skill


def _fmt(monto: Decimal) -> str:
    return f"C${monto:,.2f}"


def _ventas_facturadas(company, *, desde=None):
    # "Ventas" = facturas (BillingDocument INVOICE) EMITIDAS. Excluye notas de crédito y borradores.
    qs = BillingDocument.objects.filter(
        company=company, doc_type=DocType.INVOICE, status=DocStatus.ISSUED
    )
    if desde is not None:
        qs = qs.filter(created_at__date__gte=desde)
    total = qs.aggregate(t=Sum("total"))["t"] or Decimal("0.00")
    return qs.count(), total


@skill(
    key="ventas.hoy",
    description="Cuánto se vendió hoy (total facturado del día) y cuántas facturas.",
    required_permission="billing.invoice.read",
    keywords=("cuanto vendi hoy", "ventas de hoy", "ventas del dia", "cuanto se vendio hoy", "venta de hoy"),
    examples=("¿Cuánto vendí hoy?", "Ventas de hoy"),
)
def ventas_hoy(*, request, args):
    company = request.company
    hoy = timezone.localdate()
    n, total = _ventas_facturadas(company, desde=hoy)
    answer = f"Hoy {company.name} facturó {_fmt(total)} en {n} factura{'s' if n != 1 else ''}."
    return {"answer": answer, "data": {"fecha": str(hoy), "facturas": n, "total": str(total)}}


@skill(
    key="ventas.mes",
    description="Cuánto se vendió este mes (total facturado del mes en curso).",
    required_permission="billing.invoice.read",
    keywords=("cuanto vendi este mes", "ventas del mes", "ventas de este mes", "cuanto se vendio este mes"),
    examples=("¿Cuánto vendí este mes?", "Ventas del mes"),
)
def ventas_mes(*, request, args):
    company = request.company
    hoy = timezone.localdate()
    primero = hoy.replace(day=1)
    n, total = _ventas_facturadas(company, desde=primero)
    answer = (
        f"En lo que va del mes (desde el {primero.strftime('%d/%m/%Y')}), "
        f"{company.name} facturó {_fmt(total)} en {n} factura{'s' if n != 1 else ''}."
    )
    return {"answer": answer, "data": {"desde": str(primero), "facturas": n, "total": str(total)}}
