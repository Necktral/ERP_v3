"""Modelos de la Caja de Venta.

La venta NO tiene modelo propio (es un ``BillingDocument`` del kernel facturacion).
Lo único que persiste este módulo es el pre-ticket de AUTO-FACTURACIÓN: el cliente
arma su compra solo en una tableta y la caja la cobra después por código corto.

El pre-ticket NO reserva stock ni fija precios: guarda artículos y cantidades; el
precio lo re-resuelve el servidor al leerlo y al cobrarlo (invariante anti-fraude
del POS). Expira solo (lazy) y su código se puede reciclar una vez cerrado.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.modulos.iam.models import OrgUnit


class SelfServiceStatus(models.TextChoices):
    OPEN = "OPEN", "Abierto"
    CHARGED = "CHARGED", "Cobrado"
    CANCELLED = "CANCELLED", "Cancelado"
    EXPIRED = "EXPIRED", "Vencido"


class SelfServiceTicket(models.Model):
    """Pre-ticket de auto-facturación (kiosko/tableta) pendiente de cobro en caja."""

    company = models.ForeignKey(
        OrgUnit, on_delete=models.PROTECT, related_name="ss_tickets_company"
    )
    branch = models.ForeignKey(
        OrgUnit, on_delete=models.PROTECT, related_name="ss_tickets_branch"
    )
    code = models.CharField(max_length=8)
    status = models.CharField(
        max_length=12, choices=SelfServiceStatus.choices, default=SelfServiceStatus.OPEN
    )
    # [{"inventory_item_id": int, "quantity": "decimal-str"}]; sin precios a propósito.
    lines = models.JSONField(default=list)
    currency = models.CharField(max_length=8, default="NIO")
    # Estimados informativos al momento de crear; la caja re-resuelve el precio real.
    estimated_subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    estimated_tax = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    estimated_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    expires_at = models.DateTimeField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="ss_tickets_created",
    )
    created_at = models.DateTimeField(default=timezone.now)
    # Id del BillingDocument que lo cobró (entero plano, sin FK cross-módulo).
    charged_doc_id = models.IntegerField(null=True, blank=True)
    charged_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "ventas"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"],
                condition=models.Q(status="OPEN"),
                name="uniq_ssticket_open_code",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "code"], name="ix_ssticket_c_code"),
            models.Index(
                fields=["company", "branch", "status", "created_at"],
                name="ix_ssticket_scope",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"SelfServiceTicket {self.code} [{self.status}]"
