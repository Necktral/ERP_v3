"""Skill de Controles internos: hallazgos de segregación de funciones (SoD) / anti-fraude abiertos.

`controls.ControlFinding` (FK company), gated por `controls.findings.read`.
"""
from __future__ import annotations

from django.db.models import Count

from apps.modulos.controls.models import ControlFinding

from . import skill

_ABIERTOS = (ControlFinding.Status.OPEN, ControlFinding.Status.ACKNOWLEDGED)


@skill(
    key="controles.hallazgos",
    description="Hallazgos de control interno / segregación de funciones (SoD, anti-fraude) abiertos por severidad.",
    required_permission="controls.findings.read",
    keywords=(
        "hallazgos", "violaciones de segregacion", "segregacion de funciones", "sod", "anti fraude",
        "controles internos", "hay hallazgos", "conflictos de permisos", "violaciones de control",
    ),
    examples=("¿Hay violaciones de segregación de funciones?", "¿Hallazgos de control abiertos?"),
)
def hallazgos(*, request, args):
    company = request.company
    qs = ControlFinding.objects.filter(company=company, status__in=_ABIERTOS)
    n = qs.count()
    por_sev = {r["severity"]: r["n"] for r in qs.values("severity").annotate(n=Count("pk"))}
    crit, high = por_sev.get("CRITICAL", 0), por_sev.get("HIGH", 0)

    if n:
        answer = (
            f"{company.name} tiene {n} hallazgo{'s' if n != 1 else ''} de control abierto"
            f"{'s' if n != 1 else ''} ({crit} crítico{'s' if crit != 1 else ''}, {high} alto"
            f"{'s' if high != 1 else ''}) — conviene revisar la segregación de funciones."
        )
    else:
        answer = f"{company.name} no tiene hallazgos de control abiertos."

    return {"answer": answer, "data": {"abiertos": n, "por_severidad": por_sev}}
