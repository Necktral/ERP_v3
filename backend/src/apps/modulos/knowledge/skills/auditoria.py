"""Skill de Bitácora (auditoría): qué pasó hoy en el sistema y los últimos movimientos.

`audit.AuditEvent` no tiene FK de empresa; se acota por `partition_key="COMPANY:<id>"` (así lo setea
audit/writer.py). Gated por `audit.read`.
"""
from __future__ import annotations

from django.db.models import Count
from django.utils import timezone

from apps.modulos.audit.models import AuditEvent

from . import skill


@skill(
    key="auditoria.bitacora",
    description="Bitácora de auditoría: eventos registrados hoy (quién hizo qué) y los últimos movimientos del sistema.",
    required_permission="audit.read",
    keywords=(
        "bitacora", "detallame la bitacora", "registro de auditoria", "auditoria del sistema",
        "quien hizo que", "que paso hoy en el sistema", "ultimos eventos", "log del sistema",
        "historial de eventos",
    ),
    examples=("Detállame la bitácora", "¿Qué eventos hubo hoy?", "¿Quién hizo qué?"),
)
def bitacora(*, request, args):
    company = request.company
    pk = f"COMPANY:{company.id}"
    hoy = timezone.localdate()
    qs = AuditEvent.objects.filter(partition_key=pk)
    hoy_qs = qs.filter(timestamp_server__date=hoy)
    n_hoy = hoy_qs.count()
    por_tipo = list(hoy_qs.values("event_type").annotate(n=Count("pk")).order_by("-n")[:5])
    ultimos = list(qs.select_related("actor_user").order_by("-timestamp_server")[:8])

    if n_hoy:
        tipos = ", ".join(f"{r['event_type']} ({r['n']})" for r in por_tipo)
        answer = f"Hoy se registraron {n_hoy} evento{'s' if n_hoy != 1 else ''} en la bitácora de {company.name}: {tipos}."
    elif ultimos:
        e = ultimos[0]
        answer = (
            f"Hoy no hubo eventos en {company.name}; el último fue {e.event_type} "
            f"({e.timestamp_server:%d/%m %H:%M})."
        )
    else:
        answer = f"La bitácora de {company.name} aún no tiene eventos registrados."

    data = {
        "eventos_hoy": n_hoy,
        "por_tipo": por_tipo,
        "ultimos": [
            {
                "tipo": e.event_type,
                "modulo": e.module,
                "usuario": getattr(e.actor_user, "username", None),
                "cuando": e.timestamp_server.isoformat(),
            }
            for e in ultimos
        ],
    }
    return {"answer": answer, "data": data}
