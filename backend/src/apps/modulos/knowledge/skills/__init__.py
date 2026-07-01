"""Catálogo de "consultas" (skills) del asistente de datos.

Cada skill es una consulta de **solo lectura**, **acotada a la empresa del request** y
**gated por un permiso**. El asistente NUNCA deja que el LLM escriba consultas: el LLM solo
elige una `key` de este catálogo; el backend ejecuta la consulta segura y arma la respuesta
con cifras reales (plantilla determinista).

Agregar una skill = decorar una función con `@skill(...)` en uno de los módulos
(`org`, `rh`, `ventas`, `inventario`, `compras`, `cartera`, `nomina`). El router no se toca.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Skill:
    key: str
    description: str  # qué responde (lo lee el LLM-router y las sugerencias)
    required_permission: str  # permiso efectivo necesario para ejecutarla
    run: Callable[..., dict[str, Any]]  # run(*, request, args) -> {"answer": str, "data": dict}
    keywords: tuple[str, ...] = ()  # disparadores del fast-path determinista (sin tildes, minúscula)
    examples: tuple[str, ...] = ()  # preguntas tipo (para sugerencias)
    args_schema: tuple[str, ...] = ()  # nombres de args opcionales que el LLM puede extraer


_REGISTRY: dict[str, Skill] = {}


def register(skill_obj: Skill) -> None:
    _REGISTRY[skill_obj.key] = skill_obj


def skill(
    *,
    key: str,
    description: str,
    required_permission: str,
    keywords: tuple[str, ...] = (),
    examples: tuple[str, ...] = (),
    args_schema: tuple[str, ...] = (),
) -> Callable[[Callable[..., dict[str, Any]]], Callable[..., dict[str, Any]]]:
    def deco(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        register(
            Skill(
                key=key,
                description=description,
                required_permission=required_permission,
                run=fn,
                keywords=tuple(normalize(k) for k in keywords),
                examples=tuple(examples),
                args_schema=tuple(args_schema),
            )
        )
        return fn

    return deco


def all_skills() -> list[Skill]:
    return list(_REGISTRY.values())


def get_skill(key: str) -> Skill | None:
    return _REGISTRY.get(key)


def available_skills(perms: set[str], *, is_superuser: bool = False) -> list[Skill]:
    """Skills que el usuario PUEDE usar según sus permisos efectivos (superuser ve todo)."""
    if is_superuser or "*" in perms:
        return all_skills()
    return [s for s in _REGISTRY.values() if s.required_permission in perms]


def normalize(text: str) -> str:
    """minúsculas + sin tildes + espacios colapsados (para el match determinista)."""
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.split())


# Importar los módulos de skills registra sus consultas en el catálogo.
from . import (  # noqa: E402,F401
    accounting,
    alertas,
    auditoria,
    beneficio,
    cartera,
    comisariato,
    compras,
    controles,
    diagnostico,
    estacion_servicios,
    financiamiento,
    finca,
    fleet,
    intercompany,
    inventario,
    nomina,
    org,
    parties,
    payments,
    pos,
    resumen,
    rh,
    ventas,
)
