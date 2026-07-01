"""Skills de Financiamiento (ex-SIFA): préstamos activos (doble saldo C$/US$), café en
custodia y solicitudes de crédito por aprobar."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import F, Sum

from apps.kernels.portfolio.models import Credit
from apps.modulos.financiamiento.models import (
    ApplicationStatus,
    CoffeeReception,
    CreditApplication,
    FinancingLoan,
    LoanStatus,
)
from apps.modulos.financiamiento.risk import build_risk_package

from . import skill

# Saldo vivo de una obligación = capital + intereses + comisión + mora − abonado.
_OUTSTANDING = (
    F("principal_amount") + F("interest_amount") + F("fee_amount") + F("penalty_amount") - F("allocated_amount")
)


def _saldo_credits(pks):
    if not pks:
        return Decimal("0.00")
    return Credit.objects.filter(pk__in=pks).aggregate(t=Sum(_OUTSTANDING))["t"] or Decimal("0.00")


@skill(
    key="financiamiento.prestamos_activos",
    description="Préstamos a productores activos, con el saldo pendiente en córdobas (C$) y en dólares (US$).",
    required_permission="financing.loan.read",
    keywords=(
        "prestamos activos", "prestamos vigentes", "cuantos prestamos", "saldo de prestamos",
        "prestamos a productores", "cartera de prestamos", "prestamos pendientes",
    ),
    examples=("¿Cuántos préstamos activos hay?", "Saldo de los préstamos a productores"),
)
def prestamos_activos(*, request, args):
    company = request.company
    pares = list(
        FinancingLoan.objects.filter(company=company, status=LoanStatus.ACTIVE)
        .values_list("credit_nio_id", "credit_usd_id")
    )
    n = len(pares)
    saldo_nio = _saldo_credits([a for a, _ in pares if a])
    saldo_usd = _saldo_credits([b for _, b in pares if b])
    answer = (
        f"{company.name} tiene {n} préstamo{'s' if n != 1 else ''} activo{'s' if n != 1 else ''}: "
        f"saldo C${saldo_nio:,.2f} y US${saldo_usd:,.2f}."
    )
    return {
        "answer": answer,
        "data": {"activos": n, "saldo_nio": str(saldo_nio), "saldo_usd": str(saldo_usd)},
    }


@skill(
    key="financiamiento.cafe_en_custodia",
    description="Café recibido en custodia: cuántas recepciones, libras netas y sacos.",
    required_permission="financing.reception.read",
    keywords=(
        "cafe en custodia", "recepciones de cafe", "cafe acopiado", "acopio de cafe",
        "cuanto cafe hay", "libras de cafe", "cafe recibido", "cafe en bodega",
    ),
    examples=("¿Cuánto café hay en custodia?", "Cuántas libras de café se recibieron"),
)
def cafe_en_custodia(*, request, args):
    company = request.company
    qs = CoffeeReception.objects.filter(company=company)
    n = qs.count()
    agg = qs.aggregate(net=Sum("net_lb"), sacos=Sum("sacks"))
    net = agg["net"] or Decimal("0.00")
    sacos = int(agg["sacos"] or 0)
    recep = "recepción" if n == 1 else "recepciones"
    answer = (
        f"{company.name} ha recibido {n} {recep} de café en custodia por {net:,.2f} libras netas "
        f"({sacos} saco{'s' if sacos != 1 else ''})."
    )
    return {"answer": answer, "data": {"recepciones": n, "libras_netas": str(net), "sacos": sacos}}


@skill(
    key="financiamiento.riesgo_cartera",
    description="Riesgo de la cartera de préstamos: pérdida esperada y VaR (peor 5%) por simulación Monte Carlo.",
    required_permission="financing.risk.read",
    keywords=(
        "riesgo de la cartera", "riesgo de prestamos", "riesgo crediticio", "perdida esperada",
        "var de la cartera", "que tan riesgosa es la cartera", "simulacion de riesgo",
        "monte carlo", "montecarlo", "riesgo de mora",
    ),
    examples=("¿Qué tan riesgosa es la cartera de préstamos?", "Pérdida esperada y VaR de la cartera"),
)
def riesgo_cartera(*, request, args):
    pkg = build_risk_package(request.company)
    sim = pkg.get("simulacion")
    if not sim:
        answer = (
            f"{pkg['empresa']} no tiene préstamos activos con saldo para analizar el riesgo de cartera."
        )
        return {"answer": answer, "data": pkg}
    fuente = "un modelo (Random Forest)" if pkg["ai_used"] else "una heurística determinista"
    answer = (
        f"La cartera de {pkg['empresa']} ({pkg['prestamos_activos']} préstamos, exposición "
        f"C${float(pkg['exposicion_total']):,.2f}) tiene una pérdida esperada de "
        f"C${float(sim['perdida_esperada']):,.2f}; en el 5% peor de los casos las pérdidas podrían "
        f"superar C${float(sim['var_95']):,.2f} (VaR 95%). PD estimada por {fuente}."
    )
    return {"answer": answer, "data": pkg}


@skill(
    key="financiamiento.solicitudes_pendientes",
    description="Solicitudes de crédito presentadas pendientes de aprobar, y el monto solicitado (C$ y US$).",
    required_permission="financing.application.read",
    keywords=(
        "solicitudes pendientes", "solicitudes de credito", "creditos por aprobar",
        "solicitudes por aprobar", "prestamos por aprobar", "solicitudes presentadas",
    ),
    examples=("¿Cuántas solicitudes de crédito hay por aprobar?", "Solicitudes presentadas pendientes"),
)
def solicitudes_pendientes(*, request, args):
    company = request.company
    qs = CreditApplication.objects.filter(company=company, status=ApplicationStatus.SUBMITTED)
    n = qs.count()
    agg = qs.aggregate(nio=Sum("requested_nio"), usd=Sum("requested_usd"))
    nio = agg["nio"] or Decimal("0.00")
    usd = agg["usd"] or Decimal("0.00")
    sol = "solicitud" if n == 1 else "solicitudes"
    answer = (
        f"{company.name} tiene {n} {sol} de crédito por aprobar "
        f"(C${nio:,.2f} y US${usd:,.2f} solicitados)."
    )
    return {
        "answer": answer,
        "data": {"pendientes": n, "solicitado_nio": str(nio), "solicitado_usd": str(usd)},
    }
