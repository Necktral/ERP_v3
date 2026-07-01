"""Handler del riel firmado para la replicación de filas `Syncable` (F1 — subida nodo→central).

El nodo publica cada fila `Syncable` al outbox (`publish_syncable_event`); el worker `sync_push`
empaqueta esos eventos como comandos `sync.replicate.v1` y los manda firmados por
`POST /api/sync/batch/`. Aquí, en el central, cada comando recrea la fila local traduciendo las FKs
por el mapa `SyncIdentity`.

Doble idempotencia: el transporte (`AppliedCommand` por `command_id`) y el dominio (`sync_uid` vía
`SyncIdentity` — re-aplicar el mismo `sync_uid` NO duplica). Ver `ARQUITECTURA_NODOS_OFFLINE.md` §5.
"""
from __future__ import annotations

from typing import Any

from apps.modulos.common.sync_replication import (
    SyncReplicationError,
    apply_replication_payload,
)

from .errors import SyncRejectError
from .registry import HandlerResult, register


@register("sync.replicate.v1")
def handle_sync_replicate(ctx: dict[str, Any], payload: dict[str, Any]) -> HandlerResult:
    """Aplica un evento de replicación: `payload = {"data": {model_label, sync_uid, fields, refs, ...}}`.

    Devuelve `refs` con el `sync_uid` y el id local resultante (queda en el recibo del comando, de
    modo que un reenvío DUPLICATE responde lo mismo). Una FK a otra fila `Syncable` aún no aplicada
    en el central → REJECTED contractual `SYNC_REF_UNRESOLVED` (el padre debe llegar antes que el
    hijo; el worker manda en orden FIFO y en el mismo lote, así que no debería ocurrir).
    """
    data = payload.get("data") or {}
    if not data.get("model_label") or not data.get("sync_uid"):
        raise SyncRejectError("SYNC_SCHEMA_INVALID", {"detail": "data.model_label/sync_uid requeridos"})
    try:
        instance, created = apply_replication_payload(data)
    except SyncReplicationError as exc:
        raise SyncRejectError("SYNC_REF_UNRESOLVED", {"detail": str(exc)})
    return {
        "refs": {
            "model_label": data["model_label"],
            "sync_uid": data["sync_uid"],
            "local_id": instance.pk,
            "created": bool(created),
        }
    }
