from __future__ import annotations

from rest_framework.exceptions import ValidationError as _DRFValidationError


def coerce_int_param(value, *, field: str, default=None):
    """Coerciona un parámetro (query/body) a int de forma DEFENSIVA.

    Robustez: muchas vistas hacían `int(query_param)` crudo → un valor no
    numérico (p. ej. ?warehouse_id=abc) levantaba ValueError no atrapado → 500
    en producción (el exception handler global solo normaliza APIException). Este
    helper convierte ese borde en un 4xx contractual (DRF ValidationError → 422)
    con un mensaje claro, en vez de un 500.

    - `None`/`""` → devuelve `default` (no es un error: parámetro ausente).
    - valor no entero → ValidationError(field=...).
    """
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        raise _DRFValidationError({field: f"Debe ser un entero válido (recibido: {value!r})."})


def get_limit_offset(request, *, default_limit: int = 50, max_limit: int = 200) -> tuple[int, int]:
    try:
        limit = int(request.query_params.get("limit") or default_limit)
    except Exception:
        limit = default_limit
    try:
        offset = int(request.query_params.get("offset") or 0)
    except Exception:
        offset = 0

    limit = max(1, min(limit, max_limit))
    offset = max(0, offset)
    return limit, offset


def paginate_queryset(qs, *, limit: int, offset: int):
    total = qs.count()
    rows = qs[offset : offset + limit]
    return total, rows


def paginate_list(items: list, *, limit: int, offset: int):
    total = len(items)
    return total, items[offset : offset + limit]
