"""Skills de Tesorería (kernel payments): arqueo de caja, cobros/pagos en curso, bancos sin conciliar."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.kernels.payments.models import BankStatement, CashSession, PaymentIntent

from . import skill

# Intents "en curso" (todavía no capturados/cancelados/reembolsados del todo).
_INTENTS_EN_CURSO = (
    PaymentIntent.Status.INTENDED,
    PaymentIntent.Status.AUTHORIZED,
    PaymentIntent.Status.PARTIALLY_CAPTURED,
)


@skill(
    key="payments.caja_hoy",
    description="Arqueo de caja del día: sesiones abiertas, cerradas hoy y la diferencia (faltante/sobrante).",
    required_permission="payments.cash_session.read",
    keywords=(
        "arqueo de caja", "cuadre de caja", "diferencia de caja", "diferencias de caja",
        "faltante de caja", "sobrante de caja", "descuadre de caja", "como esta el arqueo",
    ),
    examples=("¿Cómo va el arqueo de caja de hoy?", "Hubo faltante o sobrante de caja"),
)
def caja_hoy(*, request, args):
    company = request.company
    hoy = timezone.localdate()
    abiertas = CashSession.objects.filter(company=company, status=CashSession.Status.OPEN).count()
    cerradas_hoy = CashSession.objects.filter(
        company=company, status=CashSession.Status.CLOSED, closed_at__date=hoy
    )
    n_cerradas = cerradas_hoy.count()
    dif = cerradas_hoy.aggregate(t=Sum("difference_amount"))["t"] or Decimal("0.00")
    if dif > 0:
        nota = f"sobrante neto de C${dif:,.2f}"
    elif dif < 0:
        nota = f"faltante neto de C${abs(dif):,.2f}"
    else:
        nota = "sin diferencia"
    sesiones = "sesión" if n_cerradas == 1 else "sesiones"
    answer = (
        f"En {company.name} hay {abiertas} caja{'s' if abiertas != 1 else ''} abierta{'s' if abiertas != 1 else ''}. "
        f"Hoy se cerraron {n_cerradas} {sesiones} de caja ({nota})."
    )
    return {
        "answer": answer,
        "data": {"fecha": str(hoy), "abiertas": abiertas, "cerradas_hoy": n_cerradas, "diferencia": str(dif)},
    }


@skill(
    key="payments.intents_pendientes",
    description="Cobros/pagos en curso (intents autorizados o parcialmente capturados) y su monto total.",
    required_permission="payments.intent.read",
    keywords=(
        "cobros en curso", "pagos en curso", "intents pendientes", "cobros pendientes",
        "transacciones en curso", "cuanto hay por capturar",
    ),
    examples=("¿Cuántos cobros hay en curso?", "Monto de pagos pendientes de capturar"),
)
def intents_pendientes(*, request, args):
    company = request.company
    qs = PaymentIntent.objects.filter(company=company, status__in=_INTENTS_EN_CURSO)
    n = qs.count()
    total = qs.aggregate(t=Sum("amount"))["t"] or Decimal("0.00")
    answer = (
        f"{company.name} tiene {n} cobro{'s' if n != 1 else ''}/pago{'s' if n != 1 else ''} en curso "
        f"por C${total:,.2f}."
    )
    return {"answer": answer, "data": {"en_curso": n, "total": str(total)}}


@skill(
    key="payments.bancos_sin_conciliar",
    description="Cuántos extractos bancarios están abiertos (sin conciliar todavía).",
    required_permission="payments.bank.read",
    keywords=(
        "bancos sin conciliar", "extractos abiertos", "conciliacion bancaria pendiente",
        "cuentas sin conciliar", "extractos sin conciliar", "bancarios sin conciliar",
    ),
    examples=("¿Hay extractos bancarios sin conciliar?", "Cuántas conciliaciones bancarias faltan"),
)
def bancos_sin_conciliar(*, request, args):
    company = request.company
    n = BankStatement.objects.filter(company=company, status=BankStatement.Status.OPEN).count()
    if n:
        answer = (
            f"{company.name} tiene {n} extracto{'s' if n != 1 else ''} bancario{'s' if n != 1 else ''} "
            f"sin conciliar."
        )
    else:
        answer = f"Todos los extractos bancarios de {company.name} están conciliados."
    return {"answer": answer, "data": {"sin_conciliar": n}}
