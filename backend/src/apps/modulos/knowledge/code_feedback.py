"""Feedback de DESARROLLO con el LLM local — sobre fragmentos de CÓDIGO recuperados.

Espejo de `synthesis.py` pero para código: el LLM (OpenAI-compat, el llama-server local)
lee SOLO los fragmentos de código recuperados y redacta una nota corta de revisión (qué
hace el flujo + huecos evidentes), citando [n]. Reglas duras idénticas:
- kill switch apagado / sin URL / CUALQUIER fallo → devuelve None y el endpoint responde con
  el retrieval determinista (que ya es útil). La nota JAMÁS rompe ni lanza.
- Es un modelo local chico (7B): su nota es un PRIMER triage, no un diagnóstico de fondo (ese
  lo hace la skill de Claude `feedback-flujo`).
- `KNOWLEDGE_LLM_BASE_URL` vacío hereda `DIAGNOSTICS_LLM_BASE_URL` (un solo servidor local).
"""
from __future__ import annotations

from typing import Any

import requests
from django.conf import settings

from apps.modulos.diagnostics.flags import ai_features_enabled

_PROMPT_SYSTEM = (
    "Sos un asistente de DESARROLLO de un ERP (Django + Vue/Quasar). Te paso fragmentos "
    "NUMERADOS de código fuente recuperados para un flujo. Usando SOLO esos fragmentos, "
    "respondé en español, breve (3 a 6 viñetas): (1) qué hace el flujo; (2) huecos evidentes "
    "—endpoint sin UI que lo llame, handler/botón vacío, comentarios de pendiente (to-do, fix-me), validación faltante—; "
    "(3) qué archivo conviene revisar para cada punto. Citá [n] al final de cada afirmación. "
    "Si los fragmentos no alcanzan, decílo. No inventes archivos ni código fuera de los fragmentos."
)


def _llm_config() -> tuple[str, str, float]:
    base = str(getattr(settings, "KNOWLEDGE_LLM_BASE_URL", "") or "").strip()
    if not base:
        base = str(getattr(settings, "DIAGNOSTICS_LLM_BASE_URL", "") or "").strip()
    model = str(getattr(settings, "KNOWLEDGE_LLM_MODEL", "") or "").strip()
    if not model:
        model = str(getattr(settings, "DIAGNOSTICS_LLM_MODEL", "local") or "local")
    timeout = float(getattr(settings, "KNOWLEDGE_LLM_TIMEOUT", 30.0))
    return base.rstrip("/"), model, timeout


def _strip_reasoning(content: str) -> str:
    # Modelos razonadores locales (OpenThinker) envuelven su razonamiento en <think>.
    if "</think>" in content:
        content = content.split("</think>", 1)[1]
    return content.strip()


def synthesize_code_feedback(query: str, results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Nota de revisión con citas, o None (sin IA / sin config / fallo)."""
    if not results or not ai_features_enabled():
        return None
    base_url, model, timeout = _llm_config()
    if not base_url:
        return None

    fragments = "\n\n".join(
        f"[{i + 1}] ({r['source_path']} — {r['heading'] or 'sin símbolo'})\n"
        f"{(r.get('content') or r.get('excerpt') or '').strip()}"
        for i, r in enumerate(results)
    )
    try:
        resp = requests.post(
            f"{base_url}/v1/chat/completions",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _PROMPT_SYSTEM},
                    {
                        "role": "user",
                        "content": f"Flujo/consulta: {query}\n\nFragmentos de código:\n{fragments}",
                    },
                ],
                "temperature": 0.1,
                "max_tokens": 600,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        text = _strip_reasoning(str(data["choices"][0]["message"]["content"]))
    except (requests.RequestException, KeyError, ValueError, IndexError, TypeError):
        return None  # degradación: el retrieval determinista queda en pie
    if not text:
        return None
    return {
        "text": text,
        "sources": [
            {"n": i + 1, "source_path": r["source_path"], "heading": r["heading"]}
            for i, r in enumerate(results)
        ],
    }
