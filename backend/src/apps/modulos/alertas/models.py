"""Alertas operativas deterministas (el "actividades programadas" de Odoo, aterrizado).

Una `Alert` es el ESTADO VIGENTE de una condición operativa (CxC vencida, préstamo en
mora, stock bajo mínimo, documento de flota por vencer), deduplicada por
(company, alert_type, subject): el re-escaneo actualiza `last_seen_at`, no duplica; si
la condición desaparece, el escáner la RESUELVE; si reaparece tras resuelta, se REABRE.
La notificación (in-app/push) se emite por el módulo `notifications` SOLO al abrir o
reabrir — el estado vive aquí, el aviso allá.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.modulos.iam.models import OrgUnit


class AlertSeverity(models.TextChoices):
    INFO = "INFO", "Informativa"
    WARNING = "WARNING", "Advertencia"
    CRITICAL = "CRITICAL", "Crítica"


class AlertStatus(models.TextChoices):
    OPEN = "OPEN", "Abierta"
    ACKNOWLEDGED = "ACKNOWLEDGED", "Vista (reconocida)"
    RESOLVED = "RESOLVED", "Resuelta"


class Alert(models.Model):
    company = models.ForeignKey(
        OrgUnit, on_delete=models.PROTECT, related_name="alerts",
    )
    alert_type = models.CharField(
        max_length=48, db_index=True,
        help_text="Tipo estable (RECEIVABLE_OVERDUE, LOW_STOCK, …) — clave del escáner.",
    )
    severity = models.CharField(
        max_length=16, choices=AlertSeverity.choices, default=AlertSeverity.WARNING,
    )
    subject_type = models.CharField(max_length=64)
    subject_id = models.CharField(max_length=64)
    title = models.CharField(max_length=200)
    detail = models.CharField(max_length=500, blank=True, default="")
    payload_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16, choices=AlertStatus.choices, default=AlertStatus.OPEN, db_index=True,
    )
    first_seen_at = models.DateTimeField(default=timezone.now, editable=False)
    last_seen_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="alerts_acknowledged",
    )

    class Meta:
        app_label = "alertas"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "alert_type", "subject_type", "subject_id"],
                name="uq_alert_subject",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "status", "severity"]),
            models.Index(fields=["company", "alert_type", "status"]),
        ]

    def __str__(self) -> str:
        return f"[{self.severity}] {self.alert_type} {self.subject_type}:{self.subject_id} ({self.status})"
