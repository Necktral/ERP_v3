"""Orquestador del asistente del sistema: enruta la pregunta a una CONSULTA de datos
(skill read-only, acotada a la empresa y al permiso) o a la documentación (RAG).

Seguridad: el LLM SOLO elige una `key` del catálogo de skills permitidas para el usuario;
jamás escribe consultas. Cada skill re-valida permiso + scope al ejecutarse. La parte
determinista (fast-path por palabras clave + búsqueda en docs) NUNCA depende del LLM.
"""
from __future__ import annotations

import json
import re
from typing import Any

import requests
from django.conf import settings

from apps.modulos.diagnostics.flags import ai_features_enabled
from apps.modulos.rbac.selectors import get_effective_permissions_for_scope

from .search import search_docs
from .skills import Skill, available_skills, get_skill, normalize
from .synthesis import synthesize_answer


def answer_question(*, request, query: str) -> dict[str, Any]:
    """Devuelve {kind: 'data'|'docs', answer, data?, results?, sources?, skill?, ai_used}."""
    q = (query or "").strip()
    if not q:
        return {"kind": "docs", "answer": None, "results": [], "ai_used": False}

    perms = _effective_perms(request)
    is_super = bool(getattr(request.user, "is_superuser", False))
    skills = available_skills(perms, is_superuser=is_super)

    chosen, args = _match_deterministic(q, skills)
    if chosen is None:
        chosen, args = _route_with_llm(q, skills)

    if chosen is not None:
        try:
            res = chosen.run(request=request, args=args or {})
        except Exception:
            return _docs_answer(request, q)  # fallback robusto: nunca rompe
        return {
            "kind": "data",
            "skill": chosen.key,
            "answer": res.get("answer"),
            "data": res.get("data", {}),
            "ai_used": False,
        }
    return _docs_answer(request, q)


def _effective_perms(request) -> set[str]:
    try:
        return get_effective_permissions_for_scope(
            request.user, company=request.company, branch=getattr(request, "branch", None)
        )
    except Exception:
        return set()


def _docs_answer(request, query: str) -> dict[str, Any]:
    results = search_docs(query, limit=6)
    ans = synthesize_answer(query, results)  # respeta el kill switch; None si IA off/falla
    return {
        "kind": "docs",
        "answer": ans.get("text") if ans else None,
        "results": results,
        "sources": ans.get("sources") if ans else None,
        "ai_used": ans is not None,
    }


# --------------------------------------------------------------------------- #
# Router determinista (sin LLM)
# --------------------------------------------------------------------------- #

def _match_deterministic(query: str, skills: list[Skill]) -> tuple[Skill | None, dict[str, Any]]:
    nq = normalize(query)
    best: Skill | None = None
    best_kw = ""
    for s in skills:
        for kw in s.keywords:
            if kw and kw in nq and len(kw) > len(best_kw):
                best, best_kw = s, kw
    if best is None:
        return None, {}
    args: dict[str, Any] = {}
    if best.args_schema == ("nombre",):
        # Toma lo que viene DESPUÉS del disparador como nombre del producto.
        idx = nq.find(best_kw)
        resto = query[idx + len(best_kw):].strip(" ¿?¡!.,:;\"'")
        if resto:
            args["nombre"] = resto
    return best, args


# --------------------------------------------------------------------------- #
# Router con LLM (fallback): el modelo elige una key del catálogo permitido
# --------------------------------------------------------------------------- #

_ROUTER_SYSTEM = (
    "Sos un enrutador del asistente de un sistema ERP. Te paso la PREGUNTA del usuario y una "
    "lista de CONSULTAS disponibles (cada una con su 'key' y qué responde). Elegí la consulta "
    "más adecuada para responder con datos del sistema. Si la pregunta es sobre CÓMO se usa el "
    "sistema (un procedimiento) o ninguna consulta aplica, devolvé la key especial \"docs\". "
    "Respondé EXCLUSIVAMENTE un JSON válido con esta forma: "
    '{"skill": "<key o docs>", "args": {}}. Sin texto extra.'
)


def _route_with_llm(query: str, skills: list[Skill]) -> tuple[Skill | None, dict[str, Any]]:
    if not skills or not ai_features_enabled():
        return None, {}
    base_url, model, timeout = _llm_config()
    if not base_url:
        return None, {}
    catalogo = "\n".join(f'- "{s.key}": {s.description}' for s in skills)
    user = f"PREGUNTA: {query}\n\nCONSULTAS DISPONIBLES:\n{catalogo}\n\nDevolvé el JSON."
    try:
        resp = requests.post(
            f"{base_url}/v1/chat/completions",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _ROUTER_SYSTEM},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.0,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        content = _strip_reasoning(str(resp.json()["choices"][0]["message"]["content"]))
        data = _extract_json(content)
    except (requests.RequestException, KeyError, ValueError, IndexError, TypeError):
        return None, {}
    if not isinstance(data, dict):
        return None, {}
    key = str(data.get("skill") or "").strip()
    if not key or key == "docs":
        return None, {}
    skill_obj = get_skill(key)
    # Solo si la skill existe Y está permitida para este usuario (defensa en profundidad).
    if skill_obj is None or skill_obj not in skills:
        return None, {}
    raw_args = data.get("args")
    args: dict[str, Any] = dict(raw_args) if isinstance(raw_args, dict) else {}
    return skill_obj, args


def _llm_config() -> tuple[str, str, float]:
    base = str(getattr(settings, "KNOWLEDGE_LLM_BASE_URL", "") or "").strip()
    if not base:
        base = str(getattr(settings, "DIAGNOSTICS_LLM_BASE_URL", "") or "").strip()
    model = str(getattr(settings, "KNOWLEDGE_LLM_MODEL", "") or "").strip() or str(
        getattr(settings, "DIAGNOSTICS_LLM_MODEL", "local") or "local"
    )
    timeout = float(getattr(settings, "KNOWLEDGE_LLM_TIMEOUT", 30.0))
    return base.rstrip("/"), model, timeout


def _strip_reasoning(content: str) -> str:
    # `<think>` SIN cerrar = razonamiento truncado, sin respuesta utilizable → cadena vacía
    # (nunca exponemos la cadena de razonamiento cruda como respuesta).
    if "</think>" in content:
        content = content.split("</think>", 1)[1]
    elif "<think>" in content:
        return ""
    return content.strip()


def _extract_json(content: str) -> Any:
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None
