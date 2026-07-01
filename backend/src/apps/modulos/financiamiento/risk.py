"""Motor DETERMINISTA de riesgo de la cartera de préstamos a productores.

- **PD (probabilidad de mora)** por préstamo: heurística transparente y monótona; si el Random
  Forest opcional está disponible (`risk_ml.predict_pd`), se usa esa PD y se marca `fuente="modelo"`.
- **EAD/LGD:** exposición = saldo vivo consolidado C$/US$; LGD = 1 − recuperación estimada de la
  garantía de café.
- **Monte Carlo** de pérdidas de cartera con un **factor sistémico** (shock de mercado/cosecha común
  a todos los productores) — modelo de un factor con cópula gaussiana. Usa solo la stdlib
  (`random`, `math`, `statistics`) con semilla fija → **reproducible**.

Read-only y asesor: NO escribe nada, NO toca gates. La parte "IA" (RF) está detrás del kill switch
dentro de `risk_ml`.
"""
from __future__ import annotations

import math
import random
from decimal import Decimal
from statistics import NormalDist

from apps.kernels.portfolio.models import ObligationStatus
from apps.modulos.financiamiento.models import Currency, ExchangeRate, FinancingLoan, LoanStatus

from . import risk_ml

_MORA_STATES = (ObligationStatus.OVERDUE, ObligationStatus.WRITTEN_OFF)

# Parámetros por defecto (configurables al construir el paquete).
DEFAULT_SIMULATIONS = 10_000
MAX_SIMULATIONS = 50_000
DEFAULT_RHO = 0.15           # correlación sistémica (cópula de un factor)
DEFAULT_SEED = 20260614
DEFAULT_PRECIO_QQ = Decimal("3000")  # C$ por quintal de café (estimación de garantía)
DEFAULT_RECOVERY_BASE = 0.40         # recuperación sin garantía → LGD 0.60
RECOVERY_MAX = 0.90                  # recuperación con cobertura plena de garantía
DEFAULT_FX_FALLBACK = Decimal("36.60")  # C$/US$ si no hay ExchangeRate cargada

_PD_FLOOR, _PD_CAP = 1e-6, 1 - 1e-6
_NORMAL = NormalDist()


# --------------------------------------------------------------------------- #
# PD heurística (determinista, monótona)
# --------------------------------------------------------------------------- #

def heuristic_pd(*, status: str, days_overdue: int, producer_default_rate: float) -> float:
    """PD transparente: peor estado / más atraso ⇒ mayor PD; historial de mora del productor sube
    la PD. Monótona en `days_overdue` y en `producer_default_rate`."""
    if status == ObligationStatus.WRITTEN_OFF:
        base = 0.98
    elif status == ObligationStatus.DISPUTED:
        base = 0.60
    else:
        d = max(0, int(days_overdue or 0))
        if d <= 0:
            base = 0.03
        elif d <= 30:
            base = 0.15
        elif d <= 60:
            base = 0.35
        elif d <= 90:
            base = 0.55
        elif d <= 120:
            base = 0.75
        else:
            base = 0.90
    dr = min(1.0, max(0.0, producer_default_rate))
    base = base + (1.0 - base) * 0.5 * dr  # el historial de mora empuja hacia 1
    return min(_PD_CAP, max(_PD_FLOOR, base))


def recovery_rate(*, garantia_cobertura: float) -> float:
    """Recuperación estimada (0..RECOVERY_MAX) creciente con la cobertura de garantía café."""
    cob = min(1.0, max(0.0, garantia_cobertura))
    rec = DEFAULT_RECOVERY_BASE + (RECOVERY_MAX - DEFAULT_RECOVERY_BASE) * cob
    return min(RECOVERY_MAX, max(0.0, rec))


# --------------------------------------------------------------------------- #
# Monte Carlo: pérdida de cartera con factor sistémico (cópula de un factor)
# --------------------------------------------------------------------------- #

def simulate_portfolio_loss(
    positions: list[dict],
    *,
    simulations: int = DEFAULT_SIMULATIONS,
    rho: float = DEFAULT_RHO,
    seed: int = DEFAULT_SEED,
) -> dict:
    """`positions`: lista de {"pd": float, "loss_given_default": float (=EAD*LGD)}.

    Por escenario: factor común Z~N(0,1); cada préstamo i incumple si
    `√ρ·Z + √(1−ρ)·ε_i < Φ⁻¹(PD_i)`. Pérdida = Σ (incumple_i · EAD_i·LGD_i).
    Devuelve la distribución (esperada, P50, VaR95, VaR99, máxima) — determinista por `seed`.
    """
    n = max(1, min(int(simulations), MAX_SIMULATIONS))
    rho = min(0.99, max(0.0, float(rho)))
    sqrt_rho = math.sqrt(rho)
    sqrt_1mrho = math.sqrt(1.0 - rho)
    umbrales = [_NORMAL.inv_cdf(min(_PD_CAP, max(_PD_FLOOR, p["pd"]))) for p in positions]
    severidades = [float(p["loss_given_default"]) for p in positions]

    rng = random.Random(seed)
    perdidas: list[float] = []
    for _ in range(n):
        z = rng.gauss(0.0, 1.0)
        total = 0.0
        for thr, sev in zip(umbrales, severidades):
            if sev <= 0.0:
                continue
            eps = rng.gauss(0.0, 1.0)
            if sqrt_rho * z + sqrt_1mrho * eps < thr:
                total += sev
        perdidas.append(total)

    perdidas.sort()
    return {
        "simulaciones": n,
        "rho": round(rho, 4),
        "seed": seed,
        "perdida_esperada": _money(sum(perdidas) / n),
        "perdida_p50": _money(_percentil(perdidas, 50)),
        "var_95": _money(_percentil(perdidas, 95)),
        "var_99": _money(_percentil(perdidas, 99)),
        "perdida_maxima": _money(perdidas[-1]),
    }


def _percentil(ordenados: list[float], p: int) -> float:
    if not ordenados:
        return 0.0
    k = max(1, math.ceil(p / 100.0 * len(ordenados)))  # nearest-rank
    return ordenados[min(k - 1, len(ordenados) - 1)]


def _money(x: float) -> str:
    return f"{round(float(x), 2):.2f}"


# --------------------------------------------------------------------------- #
# Construcción del paquete de riesgo (read-only)
# --------------------------------------------------------------------------- #

def _fx_rate(company) -> Decimal:
    fx = ExchangeRate.objects.filter(company=company).order_by("-rate_date", "-id").first()
    return fx.rate if fx else DEFAULT_FX_FALLBACK


def _consolidated_ead(loan, *, fx: Decimal) -> Decimal:
    total = Decimal("0")
    for credit in (loan.credit_nio, loan.credit_usd):
        if credit is None:
            continue
        out = credit.outstanding_amount or Decimal("0")
        if str(credit.currency) == Currency.USD:
            out = out * fx
        total += out
    return total


def _worst_credit_view(loan) -> tuple[str, int]:
    """Estado 'peor' y máximo de días de atraso entre los créditos del préstamo."""
    estados: list[str] = []
    dias: list[int] = []
    for credit in (loan.credit_nio, loan.credit_usd):
        if credit is None:
            continue
        estados.append(str(credit.status))
        dias.append(int(credit.days_overdue or 0))
    status: str
    if ObligationStatus.WRITTEN_OFF in estados:
        status = str(ObligationStatus.WRITTEN_OFF)
    elif ObligationStatus.DISPUTED in estados:
        status = str(ObligationStatus.DISPUTED)
    elif ObligationStatus.OVERDUE in estados:
        status = str(ObligationStatus.OVERDUE)
    else:
        status = estados[0] if estados else str(ObligationStatus.PENDING)
    return status, (max(dias) if dias else 0)


def _producer_default_rate(loan) -> tuple[float, int]:
    """Tasa de mora histórica del productor (sobre sus OTROS préstamos) y cuántos previos tuvo."""
    prior = (
        FinancingLoan.objects.filter(producer_id=loan.producer_id)
        .exclude(pk=loan.pk)
        .select_related("credit_nio", "credit_usd")
    )
    n = 0
    bad = 0
    for other in prior:
        n += 1
        if any(c is not None and str(c.status) in _MORA_STATES for c in (other.credit_nio, other.credit_usd)):
            bad += 1
    return ((bad / n) if n else 0.0), n


def build_risk_package(
    company,
    *,
    simulations: int = DEFAULT_SIMULATIONS,
    seed: int = DEFAULT_SEED,
    rho: float = DEFAULT_RHO,
    precio_qq: Decimal = DEFAULT_PRECIO_QQ,
) -> dict:
    """Paquete asesor de riesgo de la cartera de préstamos ACTIVOS (read-only)."""
    fx = _fx_rate(company)
    loans = (
        FinancingLoan.objects.filter(company=company, status=LoanStatus.ACTIVE)
        .select_related("producer", "producer__party", "credit_nio", "credit_usd", "application")
    )

    posiciones: list[dict] = []
    detalle: list[dict] = []
    exposicion_total = Decimal("0")
    ai_used = False

    for loan in loans:
        ead = _consolidated_ead(loan, fx=fx)
        if ead <= 0:
            continue
        exposicion_total += ead
        status, days_overdue = _worst_credit_view(loan)
        producer_dr, prestamos_previos = _producer_default_rate(loan)

        app = loan.application
        garantia_cafe_qq = getattr(app, "guarantee_coffee_qq", Decimal("0")) if app else Decimal("0")
        garantia_finca_mz = getattr(app, "guarantee_farm_area_mz", Decimal("0")) if app else Decimal("0")
        valor_garantia = (garantia_cafe_qq or Decimal("0")) * precio_qq
        cobertura = float(valor_garantia / ead) if ead > 0 else 0.0

        # PD: Random Forest si está disponible; si no, heurística determinista.
        features = risk_ml.extract_features(
            loan=loan,
            ead=ead,
            days_overdue=days_overdue,
            producer_default_rate=producer_dr,
            prestamos_previos=prestamos_previos,
            garantia_cafe_qq=garantia_cafe_qq,
            garantia_finca_mz=garantia_finca_mz,
        )
        pd_modelo = risk_ml.predict_pd(features)
        if pd_modelo is not None:
            pd = pd_modelo
            fuente = "modelo"
            ai_used = True
        else:
            pd = heuristic_pd(status=status, days_overdue=days_overdue, producer_default_rate=producer_dr)
            fuente = "heuristica"

        lgd = 1.0 - recovery_rate(garantia_cobertura=cobertura)
        loss_given_default = float(ead) * lgd
        posiciones.append({"pd": pd, "loss_given_default": loss_given_default})
        detalle.append(
            {
                "referencia": loan.reference,
                "productor": getattr(loan.producer.party, "display_name", str(loan.producer_id)),
                "exposicion": _money(float(ead)),
                "pd": round(pd, 4),
                "lgd": round(lgd, 4),
                "fuente_pd": fuente,
            }
        )

    simulacion = (
        simulate_portfolio_loss(posiciones, simulations=simulations, rho=rho, seed=seed)
        if posiciones
        else None
    )
    perdida_pct = None
    if simulacion and exposicion_total > 0:
        perdida_pct = round(float(simulacion["perdida_esperada"]) / float(exposicion_total) * 100, 2)

    return {
        "empresa": company.name,
        "prestamos_activos": len(detalle),
        "exposicion_total": _money(float(exposicion_total)),
        "tipo_cambio": _money(float(fx)),
        "ai_used": ai_used,
        "fuente_pd": "modelo" if ai_used else "heuristica",
        "detalle": detalle,
        "simulacion": simulacion,
        "perdida_esperada_pct": perdida_pct,
    }
