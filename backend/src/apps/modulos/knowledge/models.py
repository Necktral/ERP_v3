"""RAG interno — el índice vive en Postgres (FTS, sin vector DB).

`KnowledgeChunk` es un fragmento indexado de una fuente del repo. Dos corpus conviven en
la MISMA tabla, separados por `corpus`:
- `docs`: documentación markdown (`docs/` + READMEs), particionada por headings, FTS español.
  La consume el asistente de USUARIO FINAL (`search/`, `assistant/`, `chat/`).
- `code`: código fuente (`.py/.vue/.ts`), particionado por ventanas de líneas, FTS `simple`
  (los identificadores no son palabras en español). La consume el asistente de DESARROLLO
  (`dev/feedback/`, permiso `knowledge.dev.read`), NUNCA el usuario final.
La columna `search` (tsvector, índice GIN) la mantiene la ingesta con la config que
corresponde a cada corpus. El retrieval es DETERMINISTA y funciona siempre; la síntesis
LLM es opcional y va detrás del kill switch.
"""
from __future__ import annotations

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.utils import timezone


class KnowledgeChunk(models.Model):
    class Corpus(models.TextChoices):
        DOCS = "docs", "Documentación"
        CODE = "code", "Código fuente"

    class Meta:
        app_label = "knowledge"
        ordering = ["source_path", "order"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_path", "order"], name="uniq_knowledgechunk_path_order"
            )
        ]
        indexes = [
            GinIndex(fields=["search"], name="gin_knowledgechunk_search"),
            models.Index(fields=["source_path"]),
        ]

    # Corpus al que pertenece el fragmento (separa docs de código en la misma tabla).
    corpus = models.CharField(
        max_length=8, choices=Corpus.choices, default=Corpus.DOCS, db_index=True
    )

    # Identidad del fragmento dentro del corpus.
    source_path = models.CharField(max_length=512)  # path repo-relativo de la fuente
    heading = models.CharField(max_length=255, blank=True, default="")
    order = models.PositiveIntegerField(default=0)  # posición del chunk en el archivo

    content = models.TextField()
    file_checksum = models.CharField(max_length=64)  # sha256 del archivo fuente completo

    # tsvector mantenido por la ingesta (heading peso A, content peso B; config por corpus).
    search = SearchVectorField(null=True)

    ingested_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        return f"KnowledgeChunk[{self.corpus}]({self.source_path}#{self.order} '{self.heading[:40]}')"
