"""Asistente CONVERSACIONAL del sistema (multi-turno, con memoria del hilo).

Evoluciona el asistente de "una pregunta → una respuesta" ([assistant.py](assistant.py)) a un agente
que conversa: junta DATOS REALES de varias skills + manual y redacta una respuesta natural, además
de sugerir el siguiente paso/mejora cuando ve algo accionable.

Reglas duras (filosofía del proyecto):
- **Las cifras las calculan las skills** (deterministas, acotadas a empresa + permiso). El LLM
  redacta pero **NUNCA inventa números**: solo usa la evidencia que le pasamos.
- Todo el LLM va **detrás del kill switch** `ai_features_enabled()`. Si está apagado o falla,
  **degrada** a la respuesta determinista (la skill/manual), sin romper.
- **Sin estado en servidor**: el frontend manda el historial (`messages`). Read-only: informa y
  aconseja, no ejecuta acciones.
"""
from __future__ import annotations

from typing import Any

import requests

from apps.modulos.diagnostics.flags import ai_features_enabled

from .assistant import _effective_perms, _extract_json, _match_deterministic
from .search import search_docs
from .skills import available_skills, get_skill
from .synthesis import _llm_config, _strip_reasoning

_MAX_TURNS = 8          # cuántos turnos del historial se le pasan al LLM
_MAX_CONTENT = 4000     # recorte por mensaje (defensa)
_MAX_SKILLS = 3         # cuántas skills puede juntar un turno

_SYSTEM = (
    "Sos el asistente del sistema ERP de Necktral. Conversás en español, con memoria del hilo, "
    "de forma natural, cálida y concisa. Para CUALQUIER cifra o dato usá EXCLUSIVAMENTE el bloque "
    "[CONTEXTO DEL SISTEMA] que viene con el último mensaje — NUNCA inventes números ni nombres. "
    "Si el contexto trae documentación, podés explicar el 'cómo se usa'. Cuando el contexto muestre "
    "PROBLEMAS detectados (alertas abiertas, errores del sistema, hallazgos de control, cajas sin "
    "cerrar, stock por agotarse, cuentas vencidas, asientos sin postear, documentos vencidos), "
    "resumí el problema con claridad y proponé con tacto la mejora o el siguiente paso. Si no hay "
    "datos ni documentación para la pregunta, decilo con franqueza y ofrecé qué SÍ podés consultar. "
    "No prometas ejecutar acciones: vos informás y aconsejás."
)

_PLAN_SYSTEM = (
    "Sos el planificador de un asistente ERP. Te paso la PREGUNTA del usuario y una lista de "
    "CONSULTAS de datos disponibles (key + qué responden). Elegí de 0 a 3 keys cuyos datos sirvan "
    "para responder, y si la pregunta es sobre CÓMO se usa el sistema marcá docs=true. Respondé "
    'EXCLUSIVAMENTE un JSON: {"skills": ["<key>", ...], "docs": true|false}. Sin texto extra.'
)

# Cuando no hay NI datos NI documentación, el modelo tiende a responder con conocimiento general
# (p. ej. trivia con cifras). Este asistente sólo habla del ERP: ante contexto vacío, declina.
_NO_CONTEXT_DIRECTIVE = (
    "IMPORTANTE: no hay datos del sistema ni documentación para responder esto. NO respondas con "
    "conocimiento general ni inventes cifras — este asistente sólo habla de este ERP. Decí con "
    "franqueza que no tenés ese dato en el sistema y ofrecé brevemente qué SÍ podés consultar "
    "(datos de la empresa o cómo se usa el sistema)."
)


def answer_chat(*, request, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Devuelve {reply, used_skills, sources, ai_used}. `messages` = historial del frontend."""
    history = _clean_messages(messages)
    last_user = _last_user_text(history)
    if not last_user:
        return {"reply": None, "used_skills": [], "sources": None, "ai_used": False}

    perms = _effective_perms(request)
    is_super = bool(getattr(request.user, "is_superuser", False))
    skills = available_skills(perms, is_superuser=is_super)

    # 1) PLAN: qué skills + docs (LLM si está encendido; si no, fast-path determinista)
    plan_keys, want_docs = _plan(last_user, skills)

    # 2) EVIDENCIA determinista (única fuente de cifras), re-chequeando permiso + scope
    allowed = {s.key for s in skills}
    evidence: list[dict[str, Any]] = []
    for key in plan_keys:
        if key not in allowed:
            continue
        s = get_skill(key)
        if s is None:
            continue
        try:
            res = s.run(request=request, args={})
        except Exception:
            continue
        evidence.append({"skill": key, "answer": res.get("answer"), "data": res.get("data", {})})

    doc_results = search_docs(last_user, limit=5) if want_docs else []

    # 3) REDACCIÓN conversacional (LLM); si IA off o falla → respuesta determinista
    reply = _compose(history, evidence, doc_results) if ai_features_enabled() else None
    ai_used = reply is not None
    if reply is None:
        reply = _fallback_reply(evidence, doc_results)

    return {
        "reply": reply,
        "used_skills": [e["skill"] for e in evidence],
        "sources": (
            [{"source_path": r["source_path"], "heading": r["heading"]} for r in doc_results]
            if doc_results
            else None
        ),
        "ai_used": ai_used,
    }


# --------------------------------------------------------------------------- #
# Historial
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# Plan (qué consultar)
# --------------------------------------------------------------------------- #

def _plan(text: str, skills: list) -> tuple[list[str], bool]:
    if ai_features_enabled():
        llm = _plan_with_llm(text, skills)
        if llm is not None:
            keys, docs = llm
            allowed = {s.key for s in skills}
            keys = [k for k in keys if k in allowed][:_MAX_SKILLS]
            return keys, bool(docs)
    # Determinista (IA off o el plan LLM falló): 1 skill por keywords, o docs.
    det, _ = _match_deterministic(text, skills)
    if det is not None:
        return [det.key], False
    return [], True


def _plan_with_llm(text: str, skills: list) -> tuple[list[str], bool] | None:
    if not skills:
        return [], True
    base_url, model, timeout = _llm_config()
    if not base_url:
        return None
    catalogo = "\n".join(f'- "{s.key}": {s.description}' for s in skills)
    user = f"PREGUNTA: {text}\n\nCONSULTAS DISPONIBLES:\n{catalogo}\n\nDevolvé el JSON."
    try:
        resp = requests.post(
            f"{base_url}/v1/chat/completions",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _PLAN_SYSTEM},
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
        return None
    if not isinstance(data, dict):
        return None
    keys = data.get("skills")
    keys = [str(k) for k in keys] if isinstance(keys, list) else []
    return keys, bool(data.get("docs"))


# --------------------------------------------------------------------------- #
# Redacción
# --------------------------------------------------------------------------- #

def _context_block(evidence: list[dict[str, Any]], doc_results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    if evidence:
        parts.append("Datos del sistema (cifras reales, usalas tal cual):")
        parts += [f"- {e['answer']}" for e in evidence if e.get("answer")]
    if doc_results:
        parts.append("\nDocumentación (manual del sistema):")
        parts += [
            f"[{i + 1}] ({r['source_path']} — {r['heading'] or 'sin título'})\n"
            f"{(r.get('content') or r.get('excerpt') or '').strip()}"
            for i, r in enumerate(doc_results)
        ]
    if not parts:
        return "No hay datos del sistema ni documentación para esta pregunta."
    return "\n".join(parts)


def _compose(
    history: list[dict[str, str]], evidence: list[dict[str, Any]], doc_results: list[dict[str, Any]]
) -> str | None:
    base_url, model, timeout = _llm_config()
    if not base_url:
        return None
    ctx = _context_block(evidence, doc_results)
    llm_messages: list[dict[str, str]] = [{"role": "system", "content": _SYSTEM}]
    llm_messages += history[:-1]  # turnos previos (memoria del hilo)
    last = history[-1]
    user_content = f"{last['content']}\n\n[CONTEXTO DEL SISTEMA]\n{ctx}"
    if not evidence and not doc_results:
        user_content += f"\n\n{_NO_CONTEXT_DIRECTIVE}"
    llm_messages.append({"role": "user", "content": user_content})
    try:
        resp = requests.post(
            f"{base_url}/v1/chat/completions",
            json={"model": model, "messages": llm_messages, "temperature": 0.3},
            timeout=timeout,
        )
        resp.raise_for_status()
        text = _strip_reasoning(str(resp.json()["choices"][0]["message"]["content"]))
    except (requests.RequestException, KeyError, ValueError, IndexError, TypeError):
        return None
    return text or None


def _fallback_reply(evidence: list[dict[str, Any]], doc_results: list[dict[str, Any]]) -> str:
    """Sin IA (o si falló): respuesta determinista honesta."""
    if evidence:
        return "\n".join(e["answer"] for e in evidence if e.get("answer"))
    if doc_results:
        r = doc_results[0]
        snippet = (r.get("content") or r.get("excerpt") or "").strip()
        head = r.get("heading") or r.get("source_path")
        return f"Según la documentación ({head}): {snippet}"
    return "No encontré datos ni documentación para eso. Probá preguntando algo más concreto."
