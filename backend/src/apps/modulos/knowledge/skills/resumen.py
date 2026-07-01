"""Skill "resumen del día": un panel que combina varias consultas operativas en una sola
respuesta, **reutilizando** las skills ya construidas y **filtrando por permiso** (cada sección
solo aparece si el usuario puede verla). Read-only, sin lógica de consulta nueva.
"""
from __future__ import annotations

from typing import Any

from apps.modulos.org.services_modules import enabled_codes
from apps.modulos.rbac.selectors import get_effective_permissions_for_scope

from . import get_skill, skill

# Secciones del panel, en orden de prioridad operativa de un holding cafetalero.
# (clave de skill, etiqueta corta, código de módulo). Cada sección se reúsa tal cual
# y se gatea DOBLEMENTE adentro del compositor: por el `required_permission` de su
# skill Y por el módulo habilitado de la empresa (así el Comisariato no muestra
# tarjetas vacías de finca, y cada empresa pinta solo lo suyo).
_SECCIONES: tuple[tuple[str, str, str], ...] = (
    ("alertas.pendientes", "Necesita atención", "alertas"),
    ("financiamiento.solicitudes_pendientes", "Solicitudes", "financiamiento"),
    ("financiamiento.prestamos_activos", "Préstamos activos", "financiamiento"),
    ("financiamiento.cafe_en_custodia", "Café en custodia", "financiamiento"),
    ("financiamiento.riesgo_cartera", "Riesgo de cartera", "financiamiento"),
    ("beneficio.ordenes_proceso", "Beneficio en proceso", "beneficio"),
    ("finca.ordenes_trabajo", "Órdenes de finca", "finca"),
    ("ventas.hoy", "Ventas de hoy", "billing"),
    ("pos.corte_hoy", "Caja (POS)", "pos"),
    ("payments.caja_hoy", "Arqueo de caja", "payments"),
    ("comisariato.cuentas", "Comisariato", "comisariato"),
    ("estacion.combustible_hoy", "Combustible hoy", "fuel"),
    ("cartera.cxc", "Por cobrar", "portfolio"),
    ("cartera.cxp", "Por pagar", "portfolio"),
    ("inventario.stock_bajo", "Stock bajo", "inventory"),
    ("compras.ordenes_pendientes", "Compras pendientes", "procurement"),
    ("nomina.ultimo_periodo", "Última nómina", "payroll"),
    ("fleet.mantenimiento_pendiente", "Mantenimiento flota", "fleet"),
    ("intercompany.cruces_pendientes", "Cruces intercompañía", "accounting"),
)


def _effective_perms(request) -> set[str]:
    try:
        return get_effective_permissions_for_scope(
            request.user, company=request.company, branch=getattr(request, "branch", None)
        )
    except Exception:
        return set()


def _enabled_modules(company) -> set[str]:
    """Módulos habilitados de la empresa (catálogo ⊕ overrides); core siempre dentro."""
    try:
        return set(enabled_codes(company))
    except Exception:
        return set()


def build_daily_summary(*, request) -> dict[str, Any]:
    """Arma el panel del día con SOLO las secciones que el usuario puede ver Y cuyo
    módulo está habilitado en la empresa (doble gateo: permiso + módulo)."""
    perms = _effective_perms(request)
    is_super = bool(getattr(request.user, "is_superuser", False)) or "*" in perms
    company = request.company
    enabled = _enabled_modules(company)

    secciones: list[dict[str, Any]] = []
    for key, etiqueta, module_code in _SECCIONES:
        if module_code not in enabled:
            continue  # la empresa no ocupa ese módulo → la tarjeta no aplica
        s = get_skill(key)
        if s is None:
            continue
        if not (is_super or s.required_permission in perms):
            continue
        try:
            res = s.run(request=request, args={})
        except Exception:
            continue  # una sección que falle no rompe el panel
        secciones.append(
            {"skill": key, "etiqueta": etiqueta, "answer": res.get("answer"), "data": res.get("data", {})}
        )

    if secciones:
        cuerpo = "\n".join(f"• {sec['answer']}" for sec in secciones)
        answer = f"Resumen de hoy en {company.name}:\n{cuerpo}"
    else:
        answer = (
            "No tenés permisos para ver el resumen del día. Probá preguntando algo puntual "
            "sobre lo que sí podés consultar."
        )
    return {"answer": answer, "data": {"empresa": company.name, "secciones": secciones}}


@skill(
    key="sistema.resumen_dia",
    description="Resumen del día: ventas, caja, cobros/pagos y stock bajo en una sola respuesta.",
    required_permission="knowledge.docs.read",
    keywords=(
        "resumen del dia", "resumen del sistema", "resumen general", "como va el dia",
        "como va el negocio", "como va todo hoy", "dame un resumen", "panel del dia",
        "resumen de hoy", "como va el dia hoy",
    ),
    examples=("¿Cómo va el día hoy?", "Dame un resumen del día"),
)
def resumen_dia(*, request, args):
    return build_daily_summary(request=request)
