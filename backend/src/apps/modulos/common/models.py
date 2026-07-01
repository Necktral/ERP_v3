"""Modelos transversales del backend.

F0 de la arquitectura offline-first: el mixin `Syncable` (identidad global de fila
entre nodos) y el mapa `SyncIdentity` (traducción `sync_uid` ↔ PK local).
Ver `docs/operacion/ARQUITECTURA_NODOS_OFFLINE.md` §4.
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone

from .sync_identity import ULID_LEN, current_node_code, new_ulid


class Syncable(models.Model):
    """Mixin de identidad de sincronización entre nodos.

    Agrega a la tabla una identidad **global** (`sync_uid`, ULID) y la **procedencia**
    (`origin_node`) **sin tocar la PK entera local**. La PK sigue siendo local a cada
    nodo (no se migran FKs); el `sync_uid` es lo que viaja entre nodos para que las
    filas no colisionen al consolidar (dos nodos crean `id=1`, pero su `sync_uid` es
    único). Heredá de este mixin en las entidades **operativas** (las que suben).
    """

    sync_uid = models.CharField(
        max_length=ULID_LEN,
        unique=True,
        editable=False,
        default=new_ulid,
        help_text="Identidad global de la fila entre nodos (ULID).",
    )
    origin_node = models.CharField(
        max_length=40,
        editable=False,
        default=current_node_code,
        help_text="Código del nodo que creó la fila.",
    )

    class Meta:
        abstract = True


class SyncIdentity(models.Model):
    """Mapa de identidad: traduce `sync_uid` (global) ↔ PK local, por modelo.

    Lo usa el lado que **consume** eventos de otro nodo (el central, o un nodo que
    recibe de un par): al aplicar un evento entrante que referencia un `sync_uid`, se
    resuelve a la PK local de este nodo. Idempotente por `(model_label, sync_uid)`.
    """

    model_label = models.CharField(max_length=100, db_index=True)
    sync_uid = models.CharField(max_length=ULID_LEN)
    origin_node = models.CharField(max_length=40, blank=True, default="")
    local_id = models.BigIntegerField()
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        app_label = "common"
        constraints = [
            models.UniqueConstraint(
                fields=["model_label", "sync_uid"], name="uq_syncidentity_model_uid"
            ),
        ]
        indexes = [
            models.Index(fields=["model_label", "local_id"], name="ix_syncidentity_model_local"),
        ]

    def __str__(self) -> str:  # pragma: no cover - representación trivial
        return f"{self.model_label}:{self.sync_uid}->{self.local_id}"
