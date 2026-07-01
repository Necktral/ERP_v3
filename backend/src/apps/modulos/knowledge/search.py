"""Retrieval DETERMINISTA sobre el índice FTS (funciona SIEMPRE, sin IA).

Dos corpus en la misma tabla, separados por `corpus` y por config FTS:
- `search_docs` → documentación (config `spanish`, stemming: "cierres" matchea "cierre").
- `search_code` → código fuente (config `simple`, sin stemming: respeta identificadores).

Ambos rankean por `SearchRank` y devuelven fragmentos con su fuente (path + heading) — las
CITAS son parte del contrato, con o sin LLM. Mismo índice + misma consulta → mismos resultados.

Dos pasadas para no castigar las preguntas naturales: primero `websearch` (AND de lexemas,
preciso); si no encuentra nada, se reintenta uniendo los términos con OR. Ambas deterministas.
"""
from __future__ import annotations

import re
from typing import Any

from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchRank
from django.db.models import F

from .models import KnowledgeChunk

MAX_RESULTS = 20

# Palabras a descartar al armar la consulta OR (operadores de websearch + ruido).
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_OR_STOP = {"or", "and", "not"}


def _or_query(query: str, *, config: str) -> SearchQuery | None:
    """Consulta OR sobre los términos del texto (o None si no hay términos usables)."""
    words = [w for w in _WORD_RE.findall(query.lower()) if w not in _OR_STOP]
    if not words:
        return None
    return SearchQuery(" OR ".join(words), config=config, search_type="websearch")


def _run(sq: SearchQuery, limit: int, *, corpus: str, config: str) -> list[dict[str, Any]]:
    qs = (
        KnowledgeChunk.objects.filter(corpus=corpus)
        .annotate(
            rank=SearchRank(F("search"), sq),
            excerpt=SearchHeadline(
                "content",
                sq,
                config=config,
                start_sel="**",
                stop_sel="**",
                max_words=60,
                min_words=20,
            ),
        )
        .filter(search=sq)
        .order_by("-rank", "source_path", "order")[:limit]
    )
    return [
        {
            "source_path": c.source_path,
            "heading": c.heading,
            "excerpt": c.excerpt,
            # Texto completo del fragmento: la síntesis LLM lo usa como contexto coherente
            # (el `excerpt` resaltado es solo para mostrar). Los chunks son chicos.
            "content": c.content,
            "rank": round(float(c.rank), 6),
        }
        for c in qs
    ]


def _search(query: str, *, limit: int, corpus: str, config: str) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), MAX_RESULTS))
    # 1) Pasada precisa: websearch (AND de lexemas, respeta frases y -exclusiones).
    results = _run(
        SearchQuery(query, config=config, search_type="websearch"), limit, corpus=corpus, config=config
    )
    if results:
        return results
    # 2) Fallback de recall: OR de los términos (preguntas naturales sin match exacto).
    or_sq = _or_query(query, config=config)
    if or_sq is None:
        return results
    return _run(or_sq, limit, corpus=corpus, config=config)


def search_docs(query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """Retrieval sobre la DOCUMENTACIÓN (corpus docs, FTS español). Para el usuario final."""
    return _search(query, limit=limit, corpus=KnowledgeChunk.Corpus.DOCS, config="spanish")


def search_code(query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """Retrieval sobre el CÓDIGO fuente (corpus code, FTS simple). Para el asistente de desarrollo."""
    return _search(query, limit=limit, corpus=KnowledgeChunk.Corpus.CODE, config="simple")
