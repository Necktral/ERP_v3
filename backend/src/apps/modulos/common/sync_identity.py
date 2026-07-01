"""Identidad de sincronización entre nodos (F0 de la arquitectura offline-first).

Provee:
- `new_ulid()` — un ULID de 26 chars (Crockford base32), ordenable por tiempo y
  globalmente único **sin coordinar con un central**. Es la "identidad global" de una
  fila entre nodos (el `sync_uid` del mixin `Syncable`).
- `current_node_code()` — el código del nodo (PC de sitio) que origina una fila.
- helpers del **mapa de identidad** (`SyncIdentity`): traducen `sync_uid` ↔ PK local
  en el lado que **consume** eventos de otro nodo, de forma idempotente.

¿Por qué ULID y no `id=1`? Cada Postgres reinicia su autoincremental en 1, así que dos
nodos crean `id=1` y colisionan al consolidar. El ULID lleva tiempo + azar (128 bits) →
no choca aunque dos nodos creen filas a la vez, y no necesita un central que reparta
rangos. La PK entera sigue siendo **local**; el ULID viaja **entre** nodos.
"""
from __future__ import annotations

import secrets
import threading
import time

# Crockford Base32 (sin I, L, O, U para evitar confusiones al tipear/leer).
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_TIME_LEN = 10  # 48 bits de timestamp -> 10 chars
_RAND_LEN = 16  # 80 bits de azar      -> 16 chars
ULID_LEN = _TIME_LEN + _RAND_LEN  # 26

_TIME_MASK = (1 << 48) - 1
_RAND_MASK = (1 << 80) - 1

_lock = threading.Lock()
_last_ms = -1
_last_rand = 0


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        value, rem = divmod(value, 32)
        chars.append(_CROCKFORD[rem])
    return "".join(reversed(chars))


def new_ulid(*, now_ms: int | None = None) -> str:
    """Genera un ULID de 26 chars, **monotónico estricto** dentro del proceso.

    Si dos llamadas caen en el mismo milisegundo (o el reloj retrocede), se incrementa
    la parte aleatoria en vez de regenerarla, de modo que el orden lexicográfico siga
    reflejando el orden de creación.
    """
    global _last_ms, _last_rand
    ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    with _lock:
        if ms <= _last_ms:
            # mismo ms o reloj hacia atrás: mantener el tiempo previo y avanzar el azar
            _last_rand = (_last_rand + 1) & _RAND_MASK
            ms_used = _last_ms
        else:
            _last_ms = ms
            _last_rand = secrets.randbits(80)
            ms_used = ms
        rand = _last_rand
    return _encode(ms_used & _TIME_MASK, _TIME_LEN) + _encode(rand, _RAND_LEN)


def is_ulid(value: str) -> bool:
    """True si `value` tiene la forma de un ULID (26 chars Crockford base32)."""
    if not isinstance(value, str) or len(value) != ULID_LEN:
        return False
    return all(ch in _CROCKFORD for ch in value)


def current_node_code() -> str:
    """Código del nodo que origina las filas (lee `settings.SYNC_NODE_CODE`).

    En dev/central de prueba el default es ``"LOCAL"``; cada PC de sitio se configura
    con su propio código (ej. ``"FINCA-A"``) y el central usa ``"CENTRAL"``.
    """
    # Import perezoso: este módulo lo usan defaults de campo que se evalúan en migraciones.
    from django.conf import settings

    return getattr(settings, "SYNC_NODE_CODE", "") or "LOCAL"


# ---------------------------------------------------------------------------
# Mapa de identidad (sync_uid global ↔ PK local), idempotente por (modelo, uid).
# ---------------------------------------------------------------------------

def register_identity(*, model_label: str, sync_uid: str, local_id: int, origin_node: str = ""):
    """Registra/recupera la traducción `sync_uid` → PK local para `model_label`.

    Idempotente: registrar dos veces el mismo `sync_uid` no duplica ni reescribe el
    `local_id` ya guardado (la primera escritura gana). Devuelve la fila `SyncIdentity`.
    """
    from .models import SyncIdentity

    obj, _created = SyncIdentity.objects.get_or_create(
        model_label=model_label,
        sync_uid=sync_uid,
        defaults={"local_id": local_id, "origin_node": origin_node},
    )
    return obj


def resolve_local_id(*, model_label: str, sync_uid: str) -> int | None:
    """Traduce un `sync_uid` global a la PK local de este nodo (o None si no existe)."""
    from .models import SyncIdentity

    return (
        SyncIdentity.objects.filter(model_label=model_label, sync_uid=sync_uid)
        .values_list("local_id", flat=True)
        .first()
    )


def register_syncable(instance, *, origin_node: str | None = None):
    """Registra en el mapa una fila `Syncable` ya persistida (usa su `sync_uid`/PK)."""
    return register_identity(
        model_label=instance._meta.label_lower,
        sync_uid=instance.sync_uid,
        local_id=instance.pk,
        origin_node=origin_node if origin_node is not None else instance.origin_node,
    )
