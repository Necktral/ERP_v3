"""Exporta una conversación del asistente de desarrollo como 'feedback packet' Markdown.

El packet reúne la conversación (preguntas del usuario + lecturas del LLM local) y, sobre todo,
los FRAGMENTOS DE CÓDIGO REALES citados (únicos por archivo+símbolo). Es lo que el usuario guarda
y le lleva a Claude para reparar: la prosa del 7B puede ser superficial, pero el código adjunto es
la FUENTE DE VERDAD desde la que Claude diagnostica y arregla. Sin IA: es puro formateo determinista.
"""
from __future__ import annotations

import re
from typing import Any

from django.utils import timezone


def build_feedback_markdown(
    *, messages: list[dict[str, Any]], fragments: list[dict[str, Any]] | None = None, title: str = "Feedback de código"
) -> str:
    fragments = fragments or []
    lines: list[str] = [
        f"# {title}",
        "",
        "> Conversación con el asistente de desarrollo local (Qwen 7B) sobre el código del ERP. "
        "Llevar a Claude para diagnóstico de fondo y reparación. El código adjunto es la fuente de verdad.",
        "",
        "## Conversación",
        "",
    ]
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "").strip()
        content = str(m.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        who = "🧑 Usuario" if role == "user" else "🤖 LLM local"
        lines += [f"### {who}", "", content, ""]

    seen: set[tuple[str, str]] = set()
    cited: list[dict[str, Any]] = []
    for f in fragments:
        if not isinstance(f, dict):
            continue
        path = str(f.get("source_path") or "").strip()
        heading = str(f.get("heading") or "").strip()
        if not path or (path, heading) in seen:
            continue
        seen.add((path, heading))
        cited.append(f)

    if cited:
        lines += ["## Fragmentos de código citados (fuente de verdad)", ""]
        for f in cited:
            path = str(f.get("source_path") or "").strip()
            heading = str(f.get("heading") or "").strip()
            body = str(f.get("content") or f.get("excerpt") or "").strip()
            lines += [f"### `{path}`" + (f" — {heading}" if heading else ""), "", "```", body, "```", ""]

    lines += [
        "## Para Claude",
        "",
        "Revisá la conversación + los fragmentos y entregá: causa raíz (archivo:línea), las vías "
        "involucradas y el fix propuesto. Es report-only salvo que el dueño pida reparar.",
        "",
    ]
    return "\n".join(lines)


def default_filename(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (title or "feedback").lower()).strip("_")[:48] or "feedback"
    stamp = timezone.now().strftime("%Y-%m-%d")
    return f"FEEDBACK_{slug}_{stamp}.md"
