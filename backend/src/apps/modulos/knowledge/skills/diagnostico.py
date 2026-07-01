"""Skill de Diagnóstico: errores del sistema detectados y aún abiertos, por clase de riesgo.

`diagnostics.ErrorEvent` (sin FK company; `company_id` es texto), gated por `diagnostics.error.read`.
Son errores TÉCNICOS (excepciones no manejadas) deduplicados por stack. Audiencia: admin.
"""
from __future__ import annotations

from django.db.models import Count

from apps.modulos.diagnostics.models import ErrorEvent, ErrorStatus

from . import skill

# "Abiertos" = aún requieren atención (excluye fixed / accepted_risk / false_positive).
_ABIERTOS = (
    ErrorStatus.OPEN,
    ErrorStatus.TRIAGED,
    ErrorStatus.CONFIRMED,
    ErrorStatus.REGRESSED,
)


@skill(
    key="diagnostico.errores",
    description="Errores del sistema detectados y aún abiertos, por clase de riesgo (C1 críticos / C2 / C3).",
    required_permission="diagnostics.error.read",
    keywords=(
        "el sistema detecto errores", "errores del sistema", "hay errores", "errores abiertos",
        "fallas del sistema", "errores c1", "diagnostico de errores", "errores tecnicos",
    ),
    examples=("¿El sistema detectó errores?", "¿Hay errores C1 abiertos?"),
)
def errores(*, request, args):
    company = request.company
    qs = ErrorEvent.objects.filter(company_id=str(company.id), status__in=_ABIERTOS)
    n = qs.count()
    por_clase = {r["risk_class"]: r["n"] for r in qs.values("risk_class").annotate(n=Count("pk"))}
    c1, c2, c3 = por_clase.get("C1", 0), por_clase.get("C2", 0), por_clase.get("C3", 0)

    if n:
        answer = (
            f"El sistema tiene {n} error{'es' if n != 1 else ''} abierto{'s' if n != 1 else ''} "
            f"en {company.name}: {c1} C1 (críticos), {c2} C2, {c3} C3."
        )
    else:
        answer = f"El sistema no tiene errores abiertos en {company.name}."

    return {"answer": answer, "data": {"abiertos": n, "C1": c1, "C2": c2, "C3": c3}}
