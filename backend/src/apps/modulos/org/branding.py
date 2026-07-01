"""Validación del logo de branding (data-URL base64).

El logo se guarda como **data-URL base64** dentro del JSON (offline-first: viaja con
el sync de nodos, sin media-server). Acá vive la validación reusable (formato, mime y
tamaño) para poder testearla aislada del modelo/serializer.
"""
from __future__ import annotations

import base64
import binascii
import re

from django.core.exceptions import ValidationError

#: MIME permitidos para el logo (SVG/PNG/JPEG). El navegador NO ejecuta scripts de un
#: SVG cargado vía <img src="data:...">, así que el data-URL es seguro para el topbar.
ALLOWED_LOGO_MIMES = {"image/svg+xml", "image/png", "image/jpeg"}

#: Tope de tamaño del logo (bytes ya decodificados).
MAX_LOGO_BYTES = 256 * 1024  # 256 KB

_DATA_URL_RE = re.compile(
    r"^data:(?P<mime>[\w.+-]+/[\w.+-]+);base64,(?P<payload>.+)$", re.DOTALL
)


def parse_logo_data_url(data_url: str) -> tuple[str, int]:
    """Valida un data-URL base64 de logo.

    Devuelve ``(mime, n_bytes)``; ``("", 0)`` si está vacío. Lanza
    ``django.core.exceptions.ValidationError`` si el formato, el MIME o el tamaño no
    son válidos.
    """
    value = (data_url or "").strip()
    if not value:
        return ("", 0)

    m = _DATA_URL_RE.match(value)
    if not m:
        raise ValidationError("El logo debe ser un data-URL base64 (data:<mime>;base64,<...>).")

    mime = m.group("mime").lower()
    if mime not in ALLOWED_LOGO_MIMES:
        raise ValidationError(f"Formato de logo no permitido ({mime}). Use SVG, PNG o JPEG.")

    payload = re.sub(r"\s+", "", m.group("payload"))
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise ValidationError("El contenido del logo no es base64 válido.")

    if len(raw) > MAX_LOGO_BYTES:
        raise ValidationError(f"El logo supera el tope de {MAX_LOGO_BYTES // 1024} KB.")

    return (mime, len(raw))
