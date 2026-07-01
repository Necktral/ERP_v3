"""Asistente de DESARROLLO CONVERSACIONAL sobre el CÓDIGO (multi-turno).

Versión conversacional del feedback de código ([code_feedback.py](code_feedback.py) es de un
solo tiro). El usuario itera ("¿cómo se crea un cargo?", "¿por qué no carga?", "¿cuál de esas
vías es la real?") y el LLM local explica CÓMO ESTÁ CABLEADO el flujo usando SOLO los fragmentos
de código recuperados con `search_code`. Es la pata "consulto al LLM local" del loop de 3:
usuario ↔ LLM local → exporta la charla ([dev_export.py](dev_export.py)) → Claude la revisa y repara.

Reglas duras (idénticas a [chat.py](chat.py)):
- El LLM va detrás del kill switch `ai_features_enabled()`. Si está apagado o falla → degrada a
  una respuesta determinista (lista de archivos/lugares encontrados). El retrieval funciona siempre.
- Sin estado en servidor: el frontend manda el historial (`messages`). Read-only.
- El 7B es chico → se le prohíbe inventar; el código real (fragments) es la fuente de verdad que
  viaja a Claude para reparar.
"""
from __future__ import annotations

from typing import Any

import requests

from apps.modulos.diagnostics.flags import ai_features_enabled

from .search import search_code
from .synthesis import _llm_config, _strip_reasoning

_MAX_TURNS = 6          # turnos del historial que viajan al LLM (memoria acotada = más rápido)
_MAX_CONTENT = 2000     # recorte por mensaje del historial
_FRAGMENTS = 6          # fragmentos recuperados (todos se devuelven para el export)
_LLM_FRAG_CHARS = 1000  # pero al LLM se le manda cada fragmento RECORTADO → prompt chico = respuesta rápida
_MAX_TOKENS = 600       # cota de generación (evita respuestas eternas del 7B)

_SYSTEM = (
    "Sos un asistente de DESARROLLO de un ERP (Django + Vue/Quasar). Conversás en español con "
    "memoria del hilo, claro y conciso. En cada turno te paso fragmentos NUMERADOS de CÓDIGO "
    "FUENTE recuperados para la consulta, en el bloque [CÓDIGO]. Usá SOLO esos fragmentos para "
    "explicar CÓMO ESTÁ CABLEADO el flujo: qué archivos/funciones participan, qué llama a qué, y "
    "—si aplica— enumerá las DISTINTAS vías que aparecen para hacer la acción. Citá [n] al final "
    "de cada afirmación. NUNCA inventes archivos, funciones ni huecos que no estén en los "
    "fragmentos; si no alcanzan, decilo y sugerí con qué término volver a buscar. Para REPARAR de "
    "fondo conviene EXPORTAR esta conversación y pasársela a Claude. No prometas ejecutar cambios."
)


def answer_dev_chat(*, request=None, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Devuelve {reply, used_files, fragments, ai_used}. `messages` = historial del frontend.

    El código no se acota por empresa (es global del repo); el permiso `knowledge.dev.read` ya se
    valida en la vista. `request` se acepta por simetría con el resto del módulo.
    """
    history = _clean_messages(messages)
    last_user = _last_user_text(history)
    if not last_user:
        return {"reply": None, "used_files": [], "fragments": [], "ai_used": False}

    results = search_code(last_user, limit=_FRAGMENTS)
    reply = _compose(history, results) if ai_features_enabled() else None
    ai_used = reply is not None
    if reply is None:
        reply = _fallback_reply(last_user, results)

    return {
        "reply": reply,
        "used_files": _unique_paths(results),
        "fragments": [
            {"source_path": r["source_path"], "heading": r["heading"], "content": r["content"]}
            for r in results
        ],
        "ai_used": ai_used,
    }


def _clean_messages(messages: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(messages, list):
        return out
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "").strip()
        content = str(m.get("content") or "").strip()[:_MAX_CONTENT]
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content})
    return out[-_MAX_TURNS:]


def _last_user_text(history: list[dict[str, str]]) -> str:
    for m in reversed(history):
        if m["role"] == "user":
            return m["content"]
    return ""


def _unique_paths(results: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for r in results:
        p = r.get("source_path")
        if p and p not in seen:
            seen.append(p)
    return seen


def _context_block(results: list[dict[str, Any]]) -> str:
    if not results:
        return "No se encontró código relacionado con la consulta."
    parts: list[str] = []
    for i, r in enumerate(results):
        body = (r.get("content") or r.get("excerpt") or "").strip()
        if len(body) > _LLM_FRAG_CHARS:
            # Al LLM se le manda recortado (prompt chico = rápido); el fragmento COMPLETO ya viaja
            # en `fragments` (lo que se exporta a Claude), así que no se pierde nada para reparar.
            body = body[:_LLM_FRAG_CHARS].rstrip() + "\n… (recortado; completo en el export)"
        parts.append(f"[{i + 1}] ({r['source_path']} — {r['heading'] or 'sin símbolo'})\n{body}")
    return "\n\n".join(parts)


def _compose(history: list[dict[str, str]], results: list[dict[str, Any]]) -> str | None:
    base_url, model, timeout = _llm_config()
    if not base_url:
        return None
    llm_messages: list[dict[str, str]] = [{"role": "system", "content": _SYSTEM}]
    llm_messages += history[:-1]  # memoria del hilo
    last = history[-1]
    user_content = f"{last['content']}\n\n[CÓDIGO]\n{_context_block(results)}"
    llm_messages.append({"role": "user", "content": user_content})
    try:
        resp = requests.post(
            f"{base_url}/v1/chat/completions",
            json={"model": model, "messages": llm_messages, "temperature": 0.1, "max_tokens": _MAX_TOKENS},
            timeout=timeout,
        )
        resp.raise_for_status()
        text = _strip_reasoning(str(resp.json()["choices"][0]["message"]["content"]))
    except (requests.RequestException, KeyError, ValueError, IndexError, TypeError):
        return None
    return text or None


def _fallback_reply(query: str, results: list[dict[str, Any]]) -> str:
    """Sin IA (o si falló): ubicación determinista de los lugares del código relacionados."""
    if not results:
        return (
            f"No encontré código relacionado con «{query}» en el índice. Probá con el nombre del "
            "módulo o de la función. ¿Corriste `make ai-reindex`?"
        )
    lugares = "\n".join(f"- {r['source_path']} :: {r['heading'] or ''}".rstrip(" :") for r in results)
    return (
        f"Estos son los lugares del código relacionados con «{query}» (retrieval determinista, sin "
        f"IA):\n{lugares}\n\nExportá esta conversación y pasásela a Claude para el diagnóstico de fondo."
    )
