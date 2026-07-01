"""Notas de usuario por registro — la pieza que faltaba del "chatter" de Odoo.

El historial unificado de un registro se compone de TRES fuentes y este módulo solo
aporta la tercera: (1) bitácora de auditoría (`/api/audit/bitacora/?subject_type&subject_id`,
ya existe, append-only con hash chain), (2) adjuntos (`documents.ScannedDocument` por
`linked_object_type/id`, ya existe), (3) NOTAS humanas (esto). Append-only: corregir es
escribir otra nota; no hay edición ni borrado — coherente con la bitácora.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.modulos.iam.models import OrgUnit


class RecordNote(models.Model):
    company = models.ForeignKey(
        OrgUnit, on_delete=models.PROTECT, related_name="record_notes",
    )
    subject_type = models.CharField(
        max_length=64, help_text="Tipo del registro anotado (p.ej. FINANCING_LOAN, RECEIVABLE).",
    )
    subject_id = models.CharField(max_length=64)
    body = models.TextField(max_length=2000)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="record_notes",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        app_label = "chatter"
        indexes = [
            models.Index(fields=["company", "subject_type", "subject_id", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"Nota de {self.created_by} en {self.subject_type}:{self.subject_id}"
