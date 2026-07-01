from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.conf import settings
from django.db import models
from django.utils import timezone


class PurchaseDocType(models.TextChoices):
    GOODS_RECEIPT = "GOODS_RECEIPT", "Goods Receipt"
    SUPPLIER_INVOICE = "SUPPLIER_INVOICE", "Supplier Invoice"
    SUPPLIER_CREDIT_NOTE = "SUPPLIER_CREDIT_NOTE", "Supplier Credit Note"
    SUPPLIER_PAYMENT = "SUPPLIER_PAYMENT", "Supplier Payment"
    ADJUSTMENT = "ADJUSTMENT", "Adjustment"
    # Solo para PurchaseSequence (numeración); NO son doc_type válidos de PurchaseDocument
    # (create_purchase_draft los rechaza — la OC y la recepción tienen modelo propio).
    PURCHASE_ORDER = "PURCHASE_ORDER", "Purchase Order"
    PO_RECEIPT = "PO_RECEIPT", "PO Receipt"


class PurchaseDocStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    POSTED = "POSTED", "Posted"
    VOIDED = "VOIDED", "Voided"


class PurchaseSequence(models.Model):
    company = models.ForeignKey("iam.OrgUnit", on_delete=models.PROTECT, related_name="proc_seq_company")
    branch = models.ForeignKey("iam.OrgUnit", on_delete=models.PROTECT, related_name="proc_seq_branch")
    doc_type = models.CharField(max_length=32, choices=PurchaseDocType.choices)
    series = models.CharField(max_length=16, default="P")
    next_number = models.IntegerField(default=1)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "branch", "doc_type", "series"], name="uniq_proc_seq"),
        ]


class PurchaseDocument(models.Model):
    company = models.ForeignKey("iam.OrgUnit", on_delete=models.PROTECT, related_name="proc_docs_company")
    branch = models.ForeignKey("iam.OrgUnit", on_delete=models.PROTECT, related_name="proc_docs_branch")

    doc_type = models.CharField(max_length=32, choices=PurchaseDocType.choices)
    status = models.CharField(max_length=16, choices=PurchaseDocStatus.choices, default=PurchaseDocStatus.DRAFT)

    series = models.CharField(max_length=16, default="P")
    number = models.IntegerField(default=0)

    currency = models.CharField(max_length=8, default="NIO")
    supplier_name = models.CharField(max_length=160, blank=True, default="")
    supplier_ref = models.CharField(max_length=64, blank=True, default="")
    external_ref = models.CharField(max_length=96, blank=True, default="")
    supplier_party = models.ForeignKey(
        "parties.Party",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="purchase_documents",
    )
    # OC de origen (3-way match): la factura del proveedor queda ligada a su orden.
    purchase_order = models.ForeignKey(
        "compras.PurchaseOrder",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="invoices",
    )

    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    tax_total = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    notes = models.CharField(max_length=255, blank=True, default="")
    metadata_json = models.JSONField(default=dict)

    idempotency_key = models.CharField(max_length=96, blank=True, default="")
    posted_at = models.DateTimeField(null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=255, blank=True, default="")

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=["company", "branch", "created_at"], name="ix_proc_doc_c_b_ca"),
            models.Index(fields=["company", "branch", "doc_type", "status", "created_at"], name="ix_proc_doc_scope"),
            models.Index(fields=["company", "idempotency_key"], name="ix_proc_doc_idem"),
            models.Index(fields=["company", "supplier_party"], name="ix_proc_doc_co_supp_party"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "idempotency_key"],
                condition=models.Q(idempotency_key__gt=""),
                name="uniq_proc_idem_per_company",
            ),
            models.UniqueConstraint(
                fields=["company", "branch", "doc_type", "series", "number"],
                condition=models.Q(number__gt=0),
                name="uniq_proc_number",
            ),
        ]

    def clean(self):
        super().clean()
        if self.supplier_party_id and self.company_id and self.supplier_party.company_id != self.company_id:
            raise ValidationError({"supplier_party": "supplier_party debe pertenecer a PurchaseDocument.company."})


# --------------------------------------------------------------------------- Ola B
# Orden de compra FORMAL con líneas y ciclo de vida (estándar Odoo/ERPNext):
# DRAFT → PENDING_APPROVAL → APPROVED → SENT → PARTIALLY_RECEIVED → RECEIVED → CLOSED
# (+ CANCELLED solo sin recepciones). La factura del proveedor sigue siendo un
# PurchaseDocument (la CxP nace de su posteo, flujo existente); aquí solo se liga
# a la OC y se valida el 3-way match.


class PurchaseOrderStatus(models.TextChoices):
    DRAFT = "DRAFT", "Borrador"
    PENDING_APPROVAL = "PENDING_APPROVAL", "Pendiente de aprobación"
    APPROVED = "APPROVED", "Aprobada"
    SENT = "SENT", "Enviada al proveedor"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED", "Recibida parcial"
    RECEIVED = "RECEIVED", "Recibida"
    CLOSED = "CLOSED", "Cerrada"
    CANCELLED = "CANCELLED", "Cancelada"


class PurchaseOrder(models.Model):
    company = models.ForeignKey("iam.OrgUnit", on_delete=models.PROTECT, related_name="po_company")
    branch = models.ForeignKey("iam.OrgUnit", on_delete=models.PROTECT, related_name="po_branch")
    # La OC formal exige Party fuerte (sin proveedor textual): de ahí cuelgan
    # precios por proveedor y la CxP de la factura.
    supplier_party = models.ForeignKey(
        "parties.Party", on_delete=models.PROTECT, related_name="purchase_orders"
    )

    status = models.CharField(
        max_length=24, choices=PurchaseOrderStatus.choices, default=PurchaseOrderStatus.DRAFT
    )
    series = models.CharField(max_length=16, default="OC")
    number = models.IntegerField(default=0)
    currency = models.CharField(max_length=8, default="NIO")
    expected_date = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True, default="")

    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    tax_total = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True, default="")

    idempotency_key = models.CharField(max_length=96, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=["company", "branch", "status", "created_at"], name="ix_po_scope"),
            models.Index(fields=["company", "supplier_party"], name="ix_po_supp"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "branch", "series", "number"],
                condition=models.Q(number__gt=0),
                name="uniq_po_number",
            ),
            models.UniqueConstraint(
                fields=["company", "idempotency_key"],
                condition=models.Q(idempotency_key__gt=""),
                name="uniq_po_idem",
            ),
        ]

    def clean(self):
        super().clean()
        if self.supplier_party_id and self.company_id and self.supplier_party.company_id != self.company_id:
            raise ValidationError({"supplier_party": "supplier_party debe pertenecer a PurchaseOrder.company."})


class PurchaseOrderLine(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey("inventarios.InventoryItem", on_delete=models.PROTECT, related_name="+")
    description = models.CharField(max_length=200, blank=True, default="")
    qty_ordered = models.DecimalField(max_digits=18, decimal_places=4)
    # Acumulada por las recepciones posteadas; los estados de la OC derivan de aquí.
    qty_received = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))
    unit_cost = models.DecimalField(max_digits=18, decimal_places=4)
    tax_rate = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal("0.0000"))
    line_subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(qty_ordered__gt=0), name="ck_pol_qty_pos"),
            models.CheckConstraint(condition=models.Q(qty_received__gte=0), name="ck_pol_recv_nonneg"),
        ]
        indexes = [models.Index(fields=["order"], name="ix_pol_order")]


class PurchaseReceipt(models.Model):
    """Recepción de mercadería de una OC: se crea y postea en un acto (sin DRAFT).

    Cada línea postea inventario real vía ``post_receive`` (idempotencia determinista
    por línea) y actualiza el último costo del proveedor. No hay anulación en v1:
    un error se corrige con un ajuste de inventario.
    """

    company = models.ForeignKey("iam.OrgUnit", on_delete=models.PROTECT, related_name="po_recv_company")
    branch = models.ForeignKey("iam.OrgUnit", on_delete=models.PROTECT, related_name="po_recv_branch")
    order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="receipts")
    warehouse = models.ForeignKey("inventarios.Warehouse", on_delete=models.PROTECT, related_name="+")

    series = models.CharField(max_length=16, default="RC")
    number = models.IntegerField(default=0)
    notes = models.CharField(max_length=255, blank=True, default="")
    idempotency_key = models.CharField(max_length=96, blank=True, default="")

    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    posted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["company", "order"], name="ix_porecv_order")]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "idempotency_key"],
                condition=models.Q(idempotency_key__gt=""),
                name="uniq_po_recv_idem",
            ),
        ]


class PurchaseReceiptLine(models.Model):
    receipt = models.ForeignKey(PurchaseReceipt, on_delete=models.CASCADE, related_name="lines")
    order_line = models.ForeignKey(PurchaseOrderLine, on_delete=models.PROTECT, related_name="receipt_lines")
    qty = models.DecimalField(max_digits=18, decimal_places=4)
    # Costo REAL de esta recepción (editable al recibir; default el de la línea OC).
    unit_cost = models.DecimalField(max_digits=18, decimal_places=4)
    # StockMovement que la posteó (trazabilidad al kardex).
    movement_id = models.IntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(qty__gt=0), name="ck_porl_qty_pos"),
        ]


class SupplierItemPrice(models.Model):
    """Precio por proveedor: último costo recibido (automático) + precio acordado (manual)."""

    company = models.ForeignKey("iam.OrgUnit", on_delete=models.PROTECT, related_name="supp_price_company")
    supplier_party = models.ForeignKey("parties.Party", on_delete=models.PROTECT, related_name="item_prices")
    item = models.ForeignKey("inventarios.InventoryItem", on_delete=models.PROTECT, related_name="supplier_prices")
    last_cost = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    agreed_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    currency = models.CharField(max_length=8, default="NIO")
    last_receipt_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "supplier_party", "item"], name="uniq_supprice"
            ),
        ]
        indexes = [models.Index(fields=["company", "item"], name="ix_supprice_item")]


class PurchaseRequisitionStatus(models.TextChoices):
    DRAFT = "DRAFT", "Borrador"
    SUBMITTED = "SUBMITTED", "Enviada"
    APPROVED = "APPROVED", "Aprobada"
    REJECTED = "REJECTED", "Rechazada"
    CONVERTED = "CONVERTED", "Convertida a OC"


class PurchaseRequisition(models.Model):
    """Requisición interna: 'necesito esto' → aprobación (maker≠checker) → OC."""

    company = models.ForeignKey("iam.OrgUnit", on_delete=models.PROTECT, related_name="preq_company")
    branch = models.ForeignKey("iam.OrgUnit", on_delete=models.PROTECT, related_name="preq_branch")
    status = models.CharField(
        max_length=16, choices=PurchaseRequisitionStatus.choices, default=PurchaseRequisitionStatus.DRAFT
    )
    notes = models.CharField(max_length=255, blank=True, default="")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=255, blank=True, default="")
    converted_order = models.ForeignKey(
        PurchaseOrder, null=True, blank=True, on_delete=models.SET_NULL, related_name="requisitions"
    )
    converted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["company", "branch", "status", "created_at"], name="ix_preq_scope"),
        ]


class PurchaseRequisitionLine(models.Model):
    requisition = models.ForeignKey(PurchaseRequisition, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey("inventarios.InventoryItem", on_delete=models.PROTECT, related_name="+")
    qty = models.DecimalField(max_digits=18, decimal_places=4)
    note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(qty__gt=0), name="ck_prl_qty_pos"),
        ]
