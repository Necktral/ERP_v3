"""Skills de Contabilidad (kernel accounting): período abierto, asientos por aprobar, último tipo de cambio."""
from __future__ import annotations

from apps.kernels.accounting.models import FiscalPeriod, FxRate, JournalDraft

from . import skill

_MESES = (
    "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

# Borradores que todavía requieren acción (no posteados ni reemplazados).
_DRAFTS_PENDIENTES = (
    JournalDraft.State.GENERATED,
    JournalDraft.State.VALIDATED,
    JournalDraft.State.EXCEPTION,
    JournalDraft.State.APPROVED_FOR_POSTING,
)


@skill(
    key="accounting.periodo_abierto",
    description="Qué período(s) fiscal(es) están abiertos en la contabilidad de la empresa.",
    required_permission="accounting.period.read",
    keywords=(
        "periodo abierto", "periodos abiertos", "periodo fiscal abierto", "que periodo esta abierto",
        "periodo contable abierto", "mes contable abierto",
    ),
    examples=("¿Qué período fiscal está abierto?", "Cuál es el mes contable abierto"),
)
def periodo_abierto(*, request, args):
    company = request.company
    abiertos = list(
        FiscalPeriod.objects.filter(company=company, status=FiscalPeriod.Status.OPEN).order_by("year", "month")
    )
    if not abiertos:
        answer = f"{company.name} no tiene ningún período fiscal abierto."
    else:
        etiquetas = [f"{_MESES[p.month]} {p.year}" for p in abiertos]
        if len(etiquetas) == 1:
            answer = f"El período fiscal abierto de {company.name} es {etiquetas[0]}."
        else:
            answer = f"{company.name} tiene {len(etiquetas)} períodos abiertos: {', '.join(etiquetas)}."
    return {
        "answer": answer,
        "data": {"abiertos": [{"anio": p.year, "mes": p.month} for p in abiertos]},
    }


@skill(
    key="accounting.borradores_pendientes",
    description="Asientos en borrador pendientes de aprobar/postear, y cuántos están en excepción.",
    required_permission="accounting.journal_draft.read",
    keywords=(
        "asientos pendientes", "borradores pendientes", "asientos por aprobar", "asientos por postear",
        "asientos en excepcion", "drafts pendientes", "asientos sin postear",
    ),
    examples=("¿Cuántos asientos hay por aprobar?", "Hay asientos en excepción"),
)
def borradores_pendientes(*, request, args):
    company = request.company
    qs = JournalDraft.objects.filter(
        economic_event__company=company, state__in=_DRAFTS_PENDIENTES
    )
    n = qs.count()
    excepciones = qs.filter(state=JournalDraft.State.EXCEPTION).count()
    answer = (
        f"{company.name} tiene {n} asiento{'s' if n != 1 else ''} en borrador pendiente"
        f"{'s' if n != 1 else ''} de aprobar/postear"
        + (f", de los cuales {excepciones} en excepción." if excepciones else ".")
    )
    return {"answer": answer, "data": {"pendientes": n, "en_excepcion": excepciones}}


@skill(
    key="accounting.tipo_cambio",
    description="El último tipo de cambio cargado en la contabilidad (córdobas por dólar u otra moneda).",
    required_permission="accounting.fx_rate.read",
    keywords=(
        "tipo de cambio", "ultimo tipo de cambio", "tasa de cambio", "cuanto esta el dolar",
        "cambio del dolar", "tc del dia",
    ),
    examples=("¿Cuál es el último tipo de cambio?", "A cuánto está el dólar"),
)
def tipo_cambio(*, request, args):
    company = request.company
    fx = (
        FxRate.objects.filter(company=company)
        .order_by("-rate_date", "-updated_at")
        .first()
    )
    if fx is None:
        answer = f"{company.name} no tiene tipos de cambio cargados."
        return {"answer": answer, "data": {}}
    answer = (
        f"El último tipo de cambio de {company.name} es 1 {fx.from_currency} = {fx.rate:,.4f} "
        f"{fx.to_currency} (al {fx.rate_date})."
    )
    return {
        "answer": answer,
        "data": {
            "fecha": str(fx.rate_date),
            "from": fx.from_currency,
            "to": fx.to_currency,
            "rate": str(fx.rate),
        },
    }
