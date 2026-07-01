from __future__ import annotations

import logging
import uuid

from django.http import JsonResponse

from config.error_envelope import build_error_envelope

logger = logging.getLogger(__name__)

# Prefijos de app (ya sin "/api/" o "/api/v1/") que NUNCA se bloquean por device.
# - auth/   : login/logout/refresh/bootstrap → el aparato bloqueado debe poder llegar
#             a login para ver el mensaje y, si re-enrola, generar identidad nueva.
# - sync/enroll/ y sync/batch/ : el propio motor de sync ya valida el estado del device.
# - schema/, csp/ : utilitarios públicos.
_EXEMPT_APP_PREFIXES = (
    "auth/",
    "sync/enroll/",
    "sync/batch/",
    "schema/",
    "csp/",
)

_API_PREFIXES = ("/api/v1/", "/api/")


def _app_path(path: str) -> str | None:
    """Devuelve la ruta sin el prefijo /api(/v1)/ o None si no es una ruta de API."""
    for pref in _API_PREFIXES:
        if path.startswith(pref):
            return path[len(pref):]
    return None


class DeviceRevocationGuardMiddleware:
    """Kill-switch real del aparato.

    Si un request de API trae `X-Device-Id` de un dispositivo **REVOCADO**, se rechaza
    con 403 y `error.code == "DEVICE_REVOKED"` — para CUALQUIER endpoint, no solo el
    canal de sync. Esto cierra el hueco de que revocar un device solo cortaba el canal
    offline Ed25519 mientras el aparato seguía operando por REST autenticado por usuario.

    Decisión de diseño: solo se bloquea REVOKED (acción deliberada del admin, terminal).
    QUARANTINED queda como estado solo-sync (automático/recuperable por desfase de reloj):
    bloquear todo el aparato por un reloj desajustado sería peligroso.

    Límite conocido: si el aparato borra su almacenamiento local, deja de mandar el header
    y el bloqueo no aplica (pero sin identidad tampoco puede operar el canal sync). El
    bloqueo per-persona real es deshabilitar al USUARIO, que es otra herramienta.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        block = self._blocked_response(request)
        if block is not None:
            return block
        return self.get_response(request)

    def _blocked_response(self, request) -> JsonResponse | None:
        device_id = (request.META.get("HTTP_X_DEVICE_ID") or "").strip()
        if not device_id:
            return None

        app_path = _app_path(getattr(request, "path", "") or "")
        if app_path is None:
            return None  # no es ruta de API
        if any(app_path.startswith(p) for p in _EXEMPT_APP_PREFIXES):
            return None

        try:
            device_uuid = uuid.UUID(device_id)
        except (ValueError, AttributeError, TypeError):
            return None  # header malformado → no es asunto nuestro (no 500)

        # Import perezoso: evita cargar modelos en el import del middleware.
        from apps.modulos.sync_engine.models import Device

        row = Device.objects.filter(id=device_uuid).values_list("status", flat=True).first()
        if row is None:
            return None  # device desconocido → lo maneja (o no) cada vista
        if row != Device.Status.REVOKED:
            return None

        # Marca el código contractual para el envelope (lo respeta error_code_for).
        request.error_code_override = "DEVICE_REVOKED"
        envelope = build_error_envelope(
            request=request,
            status_code=403,
            details={"detail": "Este dispositivo fue revocado. Contactá al administrador."},
        )
        return JsonResponse(envelope, status=403)
