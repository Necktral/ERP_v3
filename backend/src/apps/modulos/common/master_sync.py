"""F2 — bajada de datos maestros (snapshot + cursor/delta).

Los **maestros** son propiedad del **central** (single-writer) y BAJAN a los nodos: RBAC,
feriados, tablas IR, registro de empresas, etc. Como el central es el único que los escribe,
**su PK es la identidad global** del maestro (no necesitan `sync_uid`): cada nodo guarda el
maestro con la MISMA PK del central. Conflicto = **gana el central**.

Este módulo provee:
- `build_master_snapshot(dataset, since=None, limit)` — lado central: devuelve las filas del
  dataset ordenadas por un **cursor** (keyset), con `next_cursor` para pedir solo el **delta**
  la próxima vez. Sin `since` = snapshot completo.
- `apply_master_rows(dataset, rows)` — lado nodo: **upsert por PK** (gana el central),
  idempotente (reaplicar no duplica; un valor cambiado se sobrescribe).

Cursor por dataset: `updated_at` (capta inserts y updates) si el modelo lo tiene; si no, `pk`
(append-only). Es **aditivo** y opt-in: no toca los modelos maestros ni agrega rutas todavía
(el endpoint HTTP va cuando exista el central real). Ver `ARQUITECTURA_NODOS_OFFLINE.md` §5.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from django.apps import apps as django_apps
from django.db import models, transaction


class MasterSyncError(Exception):
    """Dataset desconocido o fila inaplicable."""


# Registro de datasets maestros que bajan. `cursor`: campo monotónico para el delta.
MASTER_DATASETS: dict[str, dict[str, str]] = {
    "nomina.holiday": {"model": "nomina.Holiday", "cursor": "updated_at"},
    "nomina.irbracket": {"model": "nomina.IRBracket", "cursor": "pk"},
    "rbac.permission": {"model": "rbac.Permission", "cursor": "pk"},
    "rbac.role": {"model": "rbac.Role", "cursor": "pk"},
}

DEFAULT_LIMIT = 500


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "isoformat"):  # date / datetime
        return value.isoformat()
    return value


def _entry(dataset: str) -> dict[str, str]:
    entry = MASTER_DATASETS.get(dataset)
    if entry is None:
        raise MasterSyncError(f"dataset maestro desconocido: {dataset}")
    return entry


def _model_for(dataset: str):
    app_label, model_name = _entry(dataset)["model"].split(".", 1)
    return django_apps.get_model(app_label, model_name)


def serialize_master_row(model, instance) -> dict[str, Any]:
    """Todos los campos concretos (incluida la PK, que es la identidad del maestro)."""
    return {f.attname: _to_jsonable(f.value_from_object(instance)) for f in model._meta.concrete_fields}


def build_master_snapshot(dataset: str, *, since: dict | None = None, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """Lado central: snapshot completo (since=None) o delta (since=cursor previo).

    Paginación **keyset** estable por `(cursor_field, pk)` — sin saltos ni duplicados aunque
    haya filas con el mismo timestamp.
    """
    model = _model_for(dataset)
    cursor_field = _entry(dataset)["cursor"]
    pk_attname = model._meta.pk.attname
    pk_mode = cursor_field in ("pk", pk_attname)
    order = [pk_attname] if pk_mode else [cursor_field, pk_attname]

    qs = model.objects.all().order_by(*order)
    if since is not None:
        last_pk = since.get("pk")
        if pk_mode:
            qs = qs.filter(**{f"{pk_attname}__gt": last_pk})
        else:
            field = model._meta.get_field(cursor_field)
            last_value = field.to_python(since.get("value"))
            qs = qs.filter(
                models.Q(**{f"{cursor_field}__gt": last_value})
                | models.Q(**{cursor_field: last_value, f"{pk_attname}__gt": last_pk})
            )

    window = list(qs[: limit + 1])
    has_more = len(window) > limit
    rows_qs = window[:limit]
    rows = [serialize_master_row(model, obj) for obj in rows_qs]

    next_cursor = None
    if rows_qs:
        last = rows_qs[-1]
        last_pk = getattr(last, pk_attname)
        if pk_mode:
            next_cursor = {"pk": last_pk}
        else:
            next_cursor = {"value": _to_jsonable(getattr(last, cursor_field)), "pk": last_pk}

    return {
        "dataset": dataset,
        "rows": rows,
        "count": len(rows),
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def _coerce(model, attname: str, value: Any) -> Any:
    if value is None:
        return None
    field = next((f for f in model._meta.concrete_fields if f.attname == attname), None)
    if field is None or field.is_relation:
        return value  # FK a otro maestro: el id viaja tal cual (misma PK en todos los nodos)
    return field.to_python(value)


@transaction.atomic
def apply_master_rows(dataset: str, rows: list[dict[str, Any]]) -> dict[str, int]:
    """Lado nodo: upsert por PK (gana el central). Idempotente."""
    model = _model_for(dataset)
    pk_attname = model._meta.pk.attname
    created = updated = 0
    for row in rows:
        if pk_attname not in row:
            raise MasterSyncError(f"fila sin PK '{pk_attname}' para {dataset}")
        pk_value = row[pk_attname]
        defaults = {
            attname: _coerce(model, attname, value)
            for attname, value in row.items()
            if attname != pk_attname
        }
        _obj, was_created = model.objects.update_or_create(**{pk_attname: pk_value}, defaults=defaults)
        if was_created:
            created += 1
        else:
            updated += 1
    return {"created": created, "updated": updated}
