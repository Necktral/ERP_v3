"""F1 — lazo de subida de eventos operativos entre nodos (replicación append-only).

Mecanismo (opt-in, NO enganchado a `save()` para no cambiar el comportamiento actual):

    nodo:    fila Syncable creada  ──►  publish_syncable_event()  ──►  outbox de integration
    central: outbox/lote firmado   ──►  apply_syncable_event()    ──►  fila recreada local

El evento lleva la **identidad global** (`model_label` + `sync_uid` + `origin_node`), los
**campos** (los `*_id` de FKs a maestros viajan tal cual) y las **referencias** a otras
filas `Syncable` (FK a Syncable → se manda el `sync_uid` del destino, NO su id local).

Al aplicar en el central:
- se resuelve la identidad por el **mapa `SyncIdentity`** (idempotente: si ya existe, no duplica);
- las FK a Syncable se **traducen** del `sync_uid` al id local del central (su evento debe haberse
  aplicado antes);
- la idempotencia a nivel de evento la da el **inbox** de integration (por `event_id`).

Reusa: `apps.modulos.integration` (outbox/inbox) y `common.sync_identity` (mapa + ULID).
Ver `docs/operacion/ARQUITECTURA_NODOS_OFFLINE.md` §5 (transporte).
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from django.apps import apps as django_apps
from django.utils import timezone

from apps.modulos.integration.models import InboxEvent
from apps.modulos.integration.services import create_or_get_inbox_event, publish_outbox_event

from .models import Syncable
from .sync_identity import register_identity, resolve_local_id

SYNC_SOURCE_MODULE = "sync_replication"
SYNC_EVENT_TYPE = "syncable.upsert"
CENTRAL_CONSUMER = "central"


class SyncReplicationError(Exception):
    """Falla al aplicar un evento de replicación (p. ej. una FK aún no resuelta)."""


def _to_jsonable(value: Any) -> Any:
    """Convierte tipos no-JSON (Decimal, date/datetime, UUID) a una forma serializable."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "isoformat"):  # date / datetime
        return value.isoformat()
    return value


def build_event_payload(instance: Syncable) -> dict[str, Any]:
    """Arma el payload del evento desde una fila `Syncable` (sin la PK local)."""
    meta = instance._meta
    fields: dict[str, Any] = {}
    refs: dict[str, Any] = {}
    for f in meta.concrete_fields:
        if f.primary_key or f.name in ("sync_uid", "origin_node"):
            continue
        if f.is_relation and f.many_to_one:
            fk_id = f.value_from_object(instance)
            if fk_id is not None and isinstance(f.related_model, type) and issubclass(f.related_model, Syncable):
                # FK a otra fila Syncable → viaja el sync_uid del destino (se traduce al aplicar).
                related = getattr(instance, f.name)
                refs[f.attname] = {
                    "model_label": f.related_model._meta.label_lower,
                    "sync_uid": related.sync_uid,
                }
            else:
                # FK a un maestro (no Syncable) o None → viaja el id tal cual.
                fields[f.attname] = fk_id
        else:
            fields[f.attname] = _to_jsonable(f.value_from_object(instance))
    return {
        "model_label": meta.label_lower,
        "sync_uid": instance.sync_uid,
        "origin_node": instance.origin_node,
        "fields": fields,
        "refs": refs,
    }


def publish_syncable_event(instance: Syncable, *, company=None, actor_user=None, request=None):
    """Publica al outbox el evento de creación de una fila `Syncable` (subida)."""
    return publish_outbox_event(
        source_module=SYNC_SOURCE_MODULE,
        event_type=SYNC_EVENT_TYPE,
        payload=build_event_payload(instance),
        company=company,
        actor_user=actor_user,
        request=request,
    )


def _coerce(model, attname: str, value: Any) -> Any:
    if value is None:
        return None
    field = next((f for f in model._meta.concrete_fields if f.attname == attname), None)
    if field is None:
        return value
    if field.is_relation:
        return value  # ya es el id del maestro
    return field.to_python(value)


def _apply_payload(data: dict[str, Any]) -> tuple[Any, bool]:
    """Crea (o reconoce) la fila local desde el payload, traduciendo identidad. Idempotente."""
    model_label = data["model_label"]
    sync_uid = data["sync_uid"]
    model = django_apps.get_model(*model_label.split("."))

    existing_id = resolve_local_id(model_label=model_label, sync_uid=sync_uid)
    if existing_id is not None:
        # Ya aplicado antes (mismo sync_uid) → no se duplica.
        return model.objects.get(pk=existing_id), False

    instance = model()
    for attname, value in (data.get("fields") or {}).items():
        setattr(instance, attname, _coerce(model, attname, value))
    for attname, ref in (data.get("refs") or {}).items():
        target_id = resolve_local_id(model_label=ref["model_label"], sync_uid=ref["sync_uid"])
        if target_id is None:
            raise SyncReplicationError(
                f"FK '{attname}' sin resolver: falta aplicar antes {ref['model_label']}:{ref['sync_uid']}"
            )
        setattr(instance, attname, target_id)

    instance.sync_uid = sync_uid
    instance.origin_node = data.get("origin_node", "") or ""
    instance.save()
    register_identity(
        model_label=model_label, sync_uid=sync_uid, local_id=instance.pk, origin_node=instance.origin_node
    )
    return instance, True


def apply_replication_payload(data: dict[str, Any]) -> tuple[Any, bool]:
    """Aplica el `data` de un evento de replicación en el central (recrea la fila, traduce FKs).

    Wrapper público de `_apply_payload` para el **riel del sync_engine** (la idempotencia de
    transporte la da `AppliedCommand`; la de dominio, el `sync_uid` vía `SyncIdentity`). El otro
    consumidor, `apply_syncable_event`, lo usa vía el inbox para el camino simulado de los tests.
    """
    return _apply_payload(data)


def apply_syncable_event(outbox_event, *, consumer: str = CENTRAL_CONSUMER) -> tuple[Any, bool]:
    """Aplica un evento de replicación (lado central/consumidor). Idempotente por inbox + mapa."""
    inbox_event, _created = create_or_get_inbox_event(event=outbox_event, consumer=consumer)
    data = (outbox_event.payload or {}).get("data") or {}
    instance, created = _apply_payload(data)

    if inbox_event.status != InboxEvent.Status.PROCESSED:
        inbox_event.status = InboxEvent.Status.PROCESSED
        inbox_event.processed_at = timezone.now()
        inbox_event.save(update_fields=["status", "processed_at"])
    return instance, created
