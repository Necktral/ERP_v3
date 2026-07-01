"""Ingesta de corpus → `KnowledgeChunk` (idempotente, determinista, sin IA).

Dos corpus en la MISMA tabla, separados por `corpus`:
- `docs` (default): `docs/**/*.md` + `backend/src/apps/**/README.md` + `README.md`. Se parte
  por headings markdown; cuerpos largos por párrafos. FTS español.
- `code`: código fuente (`backend/src/apps/**/*.py`, `backend/src/config/**/*.py`,
  `frontend/src/**/*.{vue,ts}`), excluyendo migraciones/tests/typings. Se parte en ventanas
  de líneas. FTS `simple` (los identificadores no son palabras en español).

El checksum por archivo evita re-trabajo. La poda y el recálculo del tsvector están
ACOTADOS al corpus que se ingiere, así una ingesta de código nunca toca los docs (ni viceversa).
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from django.contrib.postgres.search import SearchVector
from django.db import transaction
from django.db.models import Value
from django.db.models.functions import Replace
from django.utils import timezone

from .models import KnowledgeChunk

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
_MAX_CHUNK_CHARS = 4000
_CORPUS_GLOBS = ("docs/**/*.md", "backend/src/apps/**/README.md", "README.md")

# --- Corpus de CÓDIGO (asistente de desarrollo) -------------------------------------
_CODE_GLOBS = (
    "backend/src/apps/**/*.py",
    "backend/src/config/**/*.py",
    "frontend/src/**/*.vue",
    "frontend/src/**/*.ts",
)
# Excluir por subcadena de path (rápido y robusto contra el glob recursivo).
_CODE_EXCLUDE_PARTS = (
    "/migrations/",
    "/tests/",
    "/node_modules/",
    "/__pycache__/",
    "/.quasar/",
    "/dist/",
)
_CODE_EXCLUDE_SUFFIXES = (".spec.ts", ".test.ts", ".d.ts", ".spec.js", ".test.js")
_CODE_WINDOW_LINES = 150

# Primer "símbolo" de un bloque de código → se usa como heading buscable del chunk.
_SYMBOL_RE = re.compile(
    r"^(export\s+)?(default\s+)?(async\s+)?"
    r"(def|class|function|interface|type|enum|const|let|var|public|private|protected)\b"
)


@dataclass(frozen=True)
class ChunkDraft:
    heading: str
    content: str


@dataclass
class IngestResult:
    files_seen: int = 0
    files_ingested: int = 0
    files_unchanged: int = 0
    files_removed: int = 0
    chunks_written: int = 0


def _split_long(text: str) -> list[str]:
    """Divide un cuerpo largo por párrafos respetando el tope de caracteres."""
    if len(text) <= _MAX_CHUNK_CHARS:
        return [text]
    parts: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        if len(para) > _MAX_CHUNK_CHARS:
            if current:
                parts.append(current)
                current = ""
            parts.extend(_split_oversized_paragraph(para))
            continue
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) > _MAX_CHUNK_CHARS and current:
            parts.append(current)
            current = para
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def _split_oversized_paragraph(text: str) -> list[str]:
    """Fallback para OCR/markdown sin saltos: corta por palabras antes del límite."""
    pieces: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if len(candidate) > _MAX_CHUNK_CHARS and current:
            pieces.append(current)
            current = word
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces or [text[:_MAX_CHUNK_CHARS]]


def chunk_markdown(text: str) -> list[ChunkDraft]:
    """Parte un markdown por headings (#..###). Determinista: mismo texto → mismos chunks."""
    out: list[ChunkDraft] = []
    heading = ""
    body: list[str] = []

    def _flush() -> None:
        content = "\n".join(body).strip()
        if not content and not heading:
            return
        if not content:
            content = heading  # heading sin cuerpo: el título igual es buscable
        for piece in _split_long(content):
            out.append(ChunkDraft(heading=heading[:255], content=piece))

    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            _flush()
            heading = m.group(2).strip()
            body = []
        else:
            body.append(line)
    _flush()
    return out


def _first_symbol(lines: list[str]) -> str:
    """Primer declaración (def/class/function/…) dentro de la ventana, recortada."""
    for ln in lines:
        stripped = ln.strip()
        if _SYMBOL_RE.match(stripped):
            return stripped[:120]
    return ""


def chunk_code(text: str) -> list[ChunkDraft]:
    """Parte código en ventanas de líneas (determinista).

    Heading = primer símbolo de la ventana (def/class/function/…) o, si no hay, el rango
    de líneas `L{ini}-{fin}`. Respeta el tope de caracteres por si hay líneas larguísimas.
    """
    lines = text.splitlines()
    out: list[ChunkDraft] = []
    if not lines:
        return out
    for start in range(0, len(lines), _CODE_WINDOW_LINES):
        window = lines[start : start + _CODE_WINDOW_LINES]
        content = "\n".join(window).strip()
        if not content:
            continue
        end = start + len(window)
        heading = _first_symbol(window) or f"L{start + 1}-{end}"
        for piece in _split_long(content):
            out.append(ChunkDraft(heading=heading[:255], content=piece))
    return out


def _corpus_files(
    root: Path,
    *,
    globs: tuple[str, ...],
    exclude_parts: tuple[str, ...] = (),
    exclude_suffixes: tuple[str, ...] = (),
) -> list[Path]:
    seen: set[Path] = set()
    for pattern in globs:
        for p in root.glob(pattern):
            if not p.is_file():
                continue
            posix = p.as_posix()
            if any(part in posix for part in exclude_parts):
                continue
            if any(posix.endswith(sfx) for sfx in exclude_suffixes):
                continue
            seen.add(p)
    return sorted(seen)


def ingest_corpus(
    *,
    root: Path,
    corpus: str = KnowledgeChunk.Corpus.DOCS,
    globs: tuple[str, ...] = _CORPUS_GLOBS,
    exclude_parts: tuple[str, ...] = (),
    exclude_suffixes: tuple[str, ...] = (),
    chunker: Callable[[str], list[ChunkDraft]] = chunk_markdown,
    fts_config: str = "spanish",
) -> IngestResult:
    """Sincroniza el índice de UN corpus con el repo (agrega/reemplaza/poda). Idempotente."""
    result = IngestResult()
    now = timezone.now()
    alive_paths: set[str] = set()

    for path in _corpus_files(
        root, globs=globs, exclude_parts=exclude_parts, exclude_suffixes=exclude_suffixes
    ):
        result.files_seen += 1
        rel = path.relative_to(root).as_posix()
        alive_paths.add(rel)
        raw = path.read_text(encoding="utf-8", errors="replace")
        checksum = hashlib.sha256(raw.encode("utf-8")).hexdigest()

        existing = (
            KnowledgeChunk.objects.filter(corpus=corpus, source_path=rel)
            .values_list("file_checksum", flat=True)
            .first()
        )
        if existing == checksum:
            result.files_unchanged += 1
            continue

        drafts = chunker(raw)
        with transaction.atomic():
            KnowledgeChunk.objects.filter(corpus=corpus, source_path=rel).delete()
            KnowledgeChunk.objects.bulk_create(
                KnowledgeChunk(
                    corpus=corpus,
                    source_path=rel,
                    heading=d.heading,
                    order=i,
                    content=d.content,
                    file_checksum=checksum,
                    ingested_at=now,
                )
                for i, d in enumerate(drafts)
            )
        result.files_ingested += 1
        result.chunks_written += len(drafts)

    # Poda ACOTADA al corpus: archivos que ya no existen salen del índice (sin tocar el otro corpus).
    removed_qs = KnowledgeChunk.objects.filter(corpus=corpus).exclude(source_path__in=alive_paths)
    result.files_removed = removed_qs.values("source_path").distinct().count()
    removed_qs.delete()

    # tsvector con la config del corpus (docs=spanish, code=simple): heading peso A, content peso B.
    vector = SearchVector("heading", weight="A", config=fts_config) + SearchVector(
        "content", weight="B", config=fts_config
    )
    if corpus == KnowledgeChunk.Corpus.CODE:
        # El path tokenizado (estacion_servicios/fuel.py → "estacion servicios fuel py") entra al
        # índice con peso A: así una consulta en español pega al archivo aunque el código esté en inglés.
        path_tokens = Replace(
            Replace(Replace("source_path", Value("/"), Value(" ")), Value("_"), Value(" ")),
            Value("."),
            Value(" "),
        )
        vector = SearchVector(path_tokens, weight="A", config=fts_config) + vector
    KnowledgeChunk.objects.filter(corpus=corpus).update(search=vector)
    return result


def ingest_code_corpus(*, root: Path) -> IngestResult:
    """Indexa el CÓDIGO fuente (backend .py + frontend .vue/.ts) para el asistente de desarrollo."""
    return ingest_corpus(
        root=root,
        corpus=KnowledgeChunk.Corpus.CODE,
        globs=_CODE_GLOBS,
        exclude_parts=_CODE_EXCLUDE_PARTS,
        exclude_suffixes=_CODE_EXCLUDE_SUFFIXES,
        chunker=chunk_code,
        fts_config="simple",
    )
