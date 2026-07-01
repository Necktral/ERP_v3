"""Skill de Alertas: "¿qué necesita atención?" — alertas operativas abiertas por severidad/tipo.

`alertas.Alert` (FK company), gated por `alerts.read`. Genera CxC vencida, stock bajo, documentos de
flota por vencer, préstamos en mora, anomalías de rendimiento, etc.
"""
from __future__ import annotations

from django.db.models import Count

from apps.modulos.alertas.models import Alert, AlertSeverity, AlertStatus

from . import skill


@skill(
    key="alertas.pendientes",
    description="Qué necesita atención: alertas abiertas (CxC vencida, stock bajo, documentos por vencer, préstamos en mora) por severidad.",
    required_permission="alerts.read",
    keywords=(
        "que necesita atencion", "que requiere atencion", "alertas", "alertas abiertas",
        "alertas criticas", "hay alertas", "que esta pendiente", "problemas pendientes",
        "que anda mal", "que hay que atender",
    ),
    examples=("¿Qué necesita atención hoy?", "¿Hay alertas críticas?"),
)
def pendientes(*, request, args):
    company = request.company
    qs = Alert.objects.filter(company=company, status=AlertStatus.OPEN)
    n = qs.count()
    crit = qs.filter(severity=AlertSeverity.CRITICAL).count()
    warn = qs.filter(severity=AlertSeverity.WARNING).count()
    por_tipo = list(qs.values("alert_type").annotate(n=Count("pk")).order_by("-n")[:6])
    muestra = list(qs.order_by("-severity", "-last_seen_at")[:5])

    if n:
        det = ", ".join(f"{r['alert_type']} ({r['n']})" for r in por_tipo)
        answer = (
            f"{company.name} tiene {n} alerta{'s' if n != 1 else ''} abierta{'s' if n != 1 else ''} "
            f"({crit} crítica{'s' if crit != 1 else ''}, {warn} de advertencia): {det}."
        )
    else:
        answer = f"{company.name} no tiene alertas abiertas. Todo en orden por ahora."

    data = {
        "abiertas": n,
        "criticas": crit,
        "advertencias": warn,
        "por_tipo": por_tipo,
        "muestra": [
            {"tipo": a.alert_type, "severidad": a.severity, "titulo": a.title, "detalle": a.detail}
            for a in muestra
        ],
    }
    return {"answer": answer, "data": data}
