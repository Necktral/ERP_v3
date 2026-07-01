from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.modulos.knowledge.ingest import ingest_code_corpus


class Command(BaseCommand):
    help = (
        "Indexa el CÓDIGO fuente (backend .py + frontend .vue/.ts; sin migraciones/tests/typings) "
        "al índice FTS para el asistente de DESARROLLO (endpoint knowledge/dev/feedback/, permiso "
        "knowledge.dev.read). Idempotente por checksum. Determinista, sin IA. El índice vive en la "
        "DB → re-correr tras cada wipe (o usar `make ai-reindex`)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--root", default=None, help="Raíz del repo (default: BASE_DIR/../..)")

    def handle(self, *args, **options):
        root = Path(options["root"]) if options["root"] else Path(settings.BASE_DIR).parent.parent
        r = ingest_code_corpus(root=root)
        self.stdout.write(
            self.style.SUCCESS(
                f"Code ingest: vistos={r.files_seen} ingresados={r.files_ingested} "
                f"sin_cambio={r.files_unchanged} podados={r.files_removed} chunks={r.chunks_written}"
            )
        )
