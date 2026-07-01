"""Órdenes de compra formales (Ola B): ciclo de vida + recepciones parciales +
3-way match + precios por proveedor + sugerencia de reorden.

Compone lo existente SIN duplicar:
- La recepción postea inventario real (y GL) vía ``inventarios.post_receive``
  (idempotencia determinista por línea de recepción).
- La factura del proveedor sigue siendo un ``PurchaseDocument`` (la CxP nace de su
  posteo por el flujo existente); aquí solo se liga a la OC y se valida el match.
- SoD maker≠checker con guard directo (patrón BillingSoDError → HTTP 409).
"""
from __future__ import annotations

import logging
from decimal import ROUND_CEILING, Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.kernels.inventarios.models import InventoryItem, StockBalance, Warehouse
from apps.kernels.inventarios.services import post_receive
from apps.modulos.audit.service_audit import emit_service_event
from apps.modulos.integration.services import publish_outbox_event

from .models import (
    PurchaseDocStatus,
    PurchaseDocType,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    PurchaseReceipt,
    PurchaseReceiptLine,
    SupplierItemPrice,
)
from .services import (
    ProcurementError,
    ProcurementNotFoundError,
    _load_supplier_party,
    allocate_sequence_number,
    create_purchase_draft,
)

logger = logging.getLogger(__name__)

_CENT = Decimal("0.01")


def _q2(x: Decimal) -> Decimal:
    return Decimal(x).quantize(_CENT)


class ProcurementSoDError(ProcurementError):
    """Maker≠checker violado (quien envía no puede aprobar) → HTTP 409."""


class ProcurementMatchError(ProcurementError):
    """Factura fuera de la tolerancia del 3-way match → HTTP 422."""


def _audit_order(*, request, actor, order: PurchaseOrder, event_type: str, before: str, metadata=None):
    emit_service_event(
        company=order.company,
        branch=order.branch,
        request=request,
        module="PROCUREMENT",
        event_type=event_type,
        reason_code="PROCUREMENT_OK",
        actor_user=actor,
        subject_type="PROCUREMENT_ORDER",
        subject_id=str(order.id),
        before_snapshot={"status": before},
        after_snapshot={"status": order.status, "total": str(order.total)},
        metadata=dict(metadata or {}),
    )


def _order_for_update(*, request, order_id: int) -> PurchaseOrder:
    try:
        return PurchaseOrder.objects.select_for_update().get(
            id=int(order_id), company=request.company, branch=request.branch
        )
    except PurchaseOrder.DoesNotExist as exc:
        raise ProcurementNotFoundError("orden de compra no encontrada") from exc


def _resolve_line_cost(
    *, company, supplier_party, item: InventoryItem, provided
) -> Decimal:
    """Costo de la línea: explícito → precio acordado → último costo → error."""
    if provided is not None:
        cost = Decimal(str(provided))
        if cost < 0:
            raise ProcurementError("PROCUREMENT_LINE_COST_INVALID")
        return cost
    price = SupplierItemPrice.objects.filter(
        company=company, supplier_party=supplier_party, item=item
    ).first()
    if price is not None:
        if price.agreed_price is not None:
            return Decimal(price.agreed_price)
        if price.last_cost is not None:
            return Decimal(price.last_cost)
    raise ProcurementError("PROCUREMENT_LINE_COST_REQUIRED")


def _build_lines(*, company, supplier_party, lines: list[dict]) -> list[dict]:
    """Valida items y resuelve costo/IVA de cada línea; devuelve dicts listos para crear."""
    if not lines:
        raise ProcurementError("PROCUREMENT_LINES_REQUIRED")
    item_ids = [int(ln["item_id"]) for ln in lines]
    items = {
        it.id: it
        for it in InventoryItem.objects.filter(company=company, id__in=item_ids, is_active=True)
    }
    built: list[dict] = []
    for pos, ln in enumerate(lines):
        item = items.get(int(ln["item_id"]))
        if item is None:
            raise ProcurementError("PROCUREMENT_ITEM_NOT_FOUND")
        qty = Decimal(str(ln["qty"]))
        if qty <= 0:
            raise ProcurementError("PROCUREMENT_LINE_QTY_INVALID")
        unit_cost = _resolve_line_cost(
            company=company, supplier_party=supplier_party, item=item, provided=ln.get("unit_cost")
        )
        tax_rate = (
            Decimal(str(ln["tax_rate"]))
            if ln.get("tax_rate") is not None
            else Decimal(item.default_tax_rate)
        )
        line_subtotal = _q2(qty * unit_cost)
        line_total = _q2(line_subtotal * (Decimal("1") + tax_rate))
        built.append(
            {
                "item": item,
                "description": (ln.get("description") or item.name)[:200],
                "qty_ordered": qty,
                "unit_cost": unit_cost,
                "tax_rate": tax_rate,
                "line_subtotal": line_subtotal,
                "line_total": line_total,
                "position": pos,
            }
        )
    return built


def _write_order_lines(order: PurchaseOrder, built: list[dict]) -> None:
    """Reemplaza las líneas y recalcula los totales de la OC."""
    order.lines.all().delete()
    PurchaseOrderLine.objects.bulk_create(
        PurchaseOrderLine(order=order, **ln) for ln in built
    )
    subtotal = sum((ln["line_subtotal"] for ln in built), Decimal("0.00"))
    total = sum((ln["line_total"] for ln in built), Decimal("0.00"))
    order.subtotal = _q2(subtotal)
    order.total = _q2(total)
    order.tax_total = _q2(total - subtotal)
    order.save(update_fields=["subtotal", "tax_total", "total"])


def _order_payload(order: PurchaseOrder) -> dict:
    lines = [
        {
            "id": ln.id,
            "item_id": ln.item_id,
            "item_sku": ln.item.sku,
            "item_name": ln.item.name,
            "description": ln.description,
            "qty_ordered": str(ln.qty_ordered),
            "qty_received": str(ln.qty_received),
            "qty_pending": str(ln.qty_ordered - ln.qty_received),
            "unit_cost": str(ln.unit_cost),
            "tax_rate": str(ln.tax_rate),
            "line_subtotal": str(ln.line_subtotal),
            "line_total": str(ln.line_total),
        }
        for ln in order.lines.select_related("item").order_by("position", "id")
    ]
    return {
        "id": order.id,
        "status": order.status,
        "series": order.series,
        "number": order.number,
        "currency": order.currency,
        "supplier_party_id": order.supplier_party_id,
        "supplier_display_name": order.supplier_party.display_name,
        "expected_date": order.expected_date.isoformat() if order.expected_date else None,
        "notes": order.notes,
        "subtotal": str(order.subtotal),
        "tax_total": str(order.tax_total),
        "total": str(order.total),
        "submitted_by": getattr(order.submitted_by, "username", None),
        "approved_by": getattr(order.approved_by, "username", None),
        "created_at": order.created_at.isoformat(),
        "lines": lines,
    }


# --------------------------------------------------------------------------- ciclo OC

def create_purchase_order(
    *,
    request,
    actor,
    supplier_party_id: int,
    lines: list[dict],
    currency: str = "NIO",
    series: str = "OC",
    expected_date=None,
    notes: str = "",
    idempotency_key: str = "",
) -> dict:
    company = request.company
    branch = request.branch

    supplier_party = _load_supplier_party(supplier_party_id=supplier_party_id, company=company)
    if supplier_party is None:
        raise ProcurementError("PROCUREMENT_SUPPLIER_REQUIRED")

    with transaction.atomic():
        if idempotency_key:
            existing = PurchaseOrder.objects.filter(
                company=company, idempotency_key=idempotency_key
            ).first()
            if existing is not None:
                return {"order_id": existing.id, "number": existing.number, "duplicate": True}

        built = _build_lines(company=company, supplier_party=supplier_party, lines=lines)
        order = PurchaseOrder.objects.create(
            company=company,
            branch=branch,
            supplier_party=supplier_party,
            series=(series or "OC").strip().upper(),
            number=allocate_sequence_number(
                company=company,
                branch=branch,
                doc_type=PurchaseDocType.PURCHASE_ORDER,
                series=(series or "OC").strip().upper(),
            ),
            currency=(currency or "NIO").strip().upper(),
            expected_date=expected_date,
            notes=notes or "",
            idempotency_key=idempotency_key or "",
            created_by=actor,
        )
        _write_order_lines(order, built)
        _audit_order(
            request=request, actor=actor, order=order,
            event_type="PROCUREMENT_ORDER_CREATED", before="",
            metadata={"supplier_party_id": supplier_party.id, "lines": len(built)},
        )
        return {"order_id": order.id, "number": order.number, "duplicate": False}


def update_purchase_order(
    *, request, actor, order_id: int, lines: list[dict] | None = None,
    expected_date=None, notes: str | None = None,
) -> dict:
    with transaction.atomic():
        order = _order_for_update(request=request, order_id=order_id)
        if order.status != PurchaseOrderStatus.DRAFT:
            raise ProcurementError("PROCUREMENT_ORDER_NOT_DRAFT")
        if lines is not None:
            built = _build_lines(
                company=order.company, supplier_party=order.supplier_party, lines=lines
            )
            _write_order_lines(order, built)
        updates = []
        if expected_date is not None:
            order.expected_date = expected_date
            updates.append("expected_date")
        if notes is not None:
            order.notes = notes
            updates.append("notes")
        if updates:
            order.save(update_fields=updates)
        return {"order_id": order.id, "status": order.status, "total": str(order.total)}


def submit_purchase_order(*, request, actor, order_id: int) -> dict:
    with transaction.atomic():
        order = _order_for_update(request=request, order_id=order_id)
        if order.status != PurchaseOrderStatus.DRAFT:
            raise ProcurementError("PROCUREMENT_ORDER_NOT_DRAFT")
        if not order.lines.exists():
            raise ProcurementError("PROCUREMENT_LINES_REQUIRED")
        before = order.status
        order.status = PurchaseOrderStatus.PENDING_APPROVAL
        order.submitted_by = actor
        order.submitted_at = timezone.now()
        order.save(update_fields=["status", "submitted_by", "submitted_at"])
        _audit_order(request=request, actor=actor, order=order,
                     event_type="PROCUREMENT_ORDER_SUBMITTED", before=before)
        return {"order_id": order.id, "status": order.status}


def approve_purchase_order(*, request, actor, order_id: int) -> dict:
    with transaction.atomic():
        order = _order_for_update(request=request, order_id=order_id)
        if order.status != PurchaseOrderStatus.PENDING_APPROVAL:
            raise ProcurementError("PROCUREMENT_ORDER_NOT_PENDING")
        maker = order.submitted_by_id or order.created_by_id
        if maker is not None and actor is not None and actor.id == maker:
            raise ProcurementSoDError("PROCUREMENT_SOD_SELF_APPROVAL")
        before = order.status
        order.status = PurchaseOrderStatus.APPROVED
        order.approved_by = actor
        order.approved_at = timezone.now()
        order.save(update_fields=["status", "approved_by", "approved_at"])

        publish_outbox_event(
            request=request,
            source_module="PROCUREMENT",
            event_type="PurchaseOrderApproved",
            payload={
                "order_id": order.id,
                "series": order.series,
                "number": order.number,
                "currency": order.currency,
                "total": str(order.total),
                "supplier_party_id": order.supplier_party_id,
            },
            actor_user=actor,
            company=order.company,
            branch=order.branch,
        )
        _audit_order(request=request, actor=actor, order=order,
                     event_type="PROCUREMENT_ORDER_APPROVED", before=before)
        return {"order_id": order.id, "status": order.status}


def mark_purchase_order_sent(*, request, actor, order_id: int) -> dict:
    with transaction.atomic():
        order = _order_for_update(request=request, order_id=order_id)
        if order.status != PurchaseOrderStatus.APPROVED:
            raise ProcurementError("PROCUREMENT_ORDER_NOT_APPROVED")
        before = order.status
        order.status = PurchaseOrderStatus.SENT
        order.sent_at = timezone.now()
        order.save(update_fields=["status", "sent_at"])
        _audit_order(request=request, actor=actor, order=order,
                     event_type="PROCUREMENT_ORDER_SENT", before=before)
        return {"order_id": order.id, "status": order.status}


def _refresh_order_reception_status(order: PurchaseOrder) -> None:
    """Deriva el estado de recepción de las cantidades acumuladas por línea."""
    if order.status not in (PurchaseOrderStatus.SENT, PurchaseOrderStatus.PARTIALLY_RECEIVED):
        return
    lines = list(order.lines.all())
    if all(ln.qty_received >= ln.qty_ordered for ln in lines):
        order.status = PurchaseOrderStatus.RECEIVED
    elif any(ln.qty_received > 0 for ln in lines):
        order.status = PurchaseOrderStatus.PARTIALLY_RECEIVED
    order.save(update_fields=["status"])


def receive_purchase_order(
    *,
    request,
    actor,
    order_id: int,
    warehouse_id: int,
    lines: list[dict],
    idempotency_key: str,
    notes: str = "",
) -> dict:
    """Recepción (parcial o total) de una OC: postea inventario real + GL por línea.

    Idempotente por ``idempotency_key`` (reintento de red devuelve la recepción ya
    posteada sin duplicar movimientos). Sin over-receipt: qty ≤ pendiente por línea.
    """
    if not idempotency_key:
        raise ProcurementError("PROCUREMENT_IDEMPOTENCY_REQUIRED")
    if not lines:
        raise ProcurementError("PROCUREMENT_LINES_REQUIRED")

    company = request.company
    branch = request.branch

    with transaction.atomic():
        existing = PurchaseReceipt.objects.filter(
            company=company, idempotency_key=idempotency_key
        ).first()
        if existing is not None:
            return {
                "receipt_id": existing.id,
                "number": existing.number,
                "order_id": existing.order_id,
                "order_status": existing.order.status,
                "duplicate": True,
            }

        order = _order_for_update(request=request, order_id=order_id)
        if order.status not in (PurchaseOrderStatus.SENT, PurchaseOrderStatus.PARTIALLY_RECEIVED):
            raise ProcurementError("PROCUREMENT_ORDER_NOT_RECEIVABLE")

        warehouse = Warehouse.objects.filter(
            id=int(warehouse_id), company=company, branch=branch
        ).first()
        if warehouse is None:
            raise ProcurementNotFoundError("bodega no encontrada")

        order_lines = {ln.id: ln for ln in order.lines.select_for_update()}
        receipt = PurchaseReceipt.objects.create(
            company=company,
            branch=branch,
            order=order,
            warehouse=warehouse,
            series="RC",
            number=allocate_sequence_number(
                company=company, branch=branch,
                doc_type=PurchaseDocType.PO_RECEIPT, series="RC",
            ),
            notes=notes or "",
            idempotency_key=idempotency_key,
            received_by=actor,
        )

        received_lines = []
        for ln in lines:
            order_line = order_lines.get(int(ln["order_line_id"]))
            if order_line is None:
                raise ProcurementNotFoundError("línea de la orden no encontrada")
            qty = Decimal(str(ln["qty"]))
            if qty <= 0:
                raise ProcurementError("PROCUREMENT_LINE_QTY_INVALID")
            pending = order_line.qty_ordered - order_line.qty_received
            if qty > pending:
                raise ProcurementError("PROCUREMENT_OVER_RECEIPT")
            unit_cost = (
                Decimal(str(ln["unit_cost"]))
                if ln.get("unit_cost") is not None
                else Decimal(order_line.unit_cost)
            )
            if unit_cost < 0:
                raise ProcurementError("PROCUREMENT_LINE_COST_INVALID")

            rline = PurchaseReceiptLine.objects.create(
                receipt=receipt, order_line=order_line, qty=qty, unit_cost=unit_cost
            )
            result = post_receive(
                request=request,
                actor=actor,
                warehouse_id=warehouse.id,
                item_id=order_line.item_id,
                qty=qty,
                unit_cost=unit_cost,
                idempotency_key=f"po-recv:{receipt.id}:{rline.id}",
                note=f"Recepción OC {order.series}-{order.number}",
                source_module="PROCUREMENT",
                source_type="PO_RECEIPT",
                source_id=str(receipt.id),
            )
            rline.movement_id = result.movement_id
            rline.save(update_fields=["movement_id"])

            order_line.qty_received = order_line.qty_received + qty
            order_line.save(update_fields=["qty_received"])

            # Último costo del proveedor (automático; el acordado es manual).
            SupplierItemPrice.objects.update_or_create(
                company=company,
                supplier_party=order.supplier_party,
                item=order_line.item,
                defaults={
                    "last_cost": unit_cost,
                    "currency": order.currency,
                    "last_receipt_at": timezone.now(),
                },
            )
            received_lines.append(
                {"order_line_id": order_line.id, "qty": str(qty), "movement_id": result.movement_id}
            )

        before = order.status
        _refresh_order_reception_status(order)

        publish_outbox_event(
            request=request,
            source_module="PROCUREMENT",
            event_type="PurchaseReceiptPosted",
            payload={
                "receipt_id": receipt.id,
                "order_id": order.id,
                "warehouse_id": warehouse.id,
                "lines": received_lines,
                "order_status": order.status,
            },
            actor_user=actor,
            company=company,
            branch=branch,
        )
        emit_service_event(
            company=company,
            branch=branch,
            request=request,
            module="PROCUREMENT",
            event_type="PROCUREMENT_ORDER_RECEIVED",
            reason_code="PROCUREMENT_OK",
            actor_user=actor,
            subject_type="PROCUREMENT_RECEIPT",
            subject_id=str(receipt.id),
            before_snapshot={"status": before},
            after_snapshot={"status": order.status, "lines": len(received_lines)},
            metadata={"order_id": order.id, "warehouse_id": warehouse.id},
        )
        return {
            "receipt_id": receipt.id,
            "number": receipt.number,
            "order_id": order.id,
            "order_status": order.status,
            "lines": received_lines,
            "duplicate": False,
        }


def close_purchase_order(*, request, actor, order_id: int) -> dict:
    with transaction.atomic():
        order = _order_for_update(request=request, order_id=order_id)
        if order.status not in (
            PurchaseOrderStatus.SENT,
            PurchaseOrderStatus.PARTIALLY_RECEIVED,
            PurchaseOrderStatus.RECEIVED,
        ):
            raise ProcurementError("PROCUREMENT_ORDER_NOT_CLOSABLE")
        before = order.status
        order.status = PurchaseOrderStatus.CLOSED
        order.closed_at = timezone.now()
        order.save(update_fields=["status", "closed_at"])
        _audit_order(request=request, actor=actor, order=order,
                     event_type="PROCUREMENT_ORDER_CLOSED", before=before)
        return {"order_id": order.id, "status": order.status}


def cancel_purchase_order(*, request, actor, order_id: int, reason: str = "") -> dict:
    with transaction.atomic():
        order = _order_for_update(request=request, order_id=order_id)
        if order.status in (PurchaseOrderStatus.CLOSED, PurchaseOrderStatus.CANCELLED):
            raise ProcurementError("PROCUREMENT_ORDER_NOT_CANCELLABLE")
        if order.lines.filter(qty_received__gt=0).exists():
            # Con mercadería recibida la OC no se cancela: se cierra (acepta restos).
            raise ProcurementError("PROCUREMENT_ORDER_HAS_RECEIPTS")
        before = order.status
        order.status = PurchaseOrderStatus.CANCELLED
        order.cancelled_at = timezone.now()
        order.cancel_reason = (reason or "")[:255]
        order.save(update_fields=["status", "cancelled_at", "cancel_reason"])
        _audit_order(request=request, actor=actor, order=order,
                     event_type="PROCUREMENT_ORDER_CANCELLED", before=before,
                     metadata={"reason": order.cancel_reason})
        return {"order_id": order.id, "status": order.status}


def get_purchase_order_detail(*, request, order_id: int) -> dict:
    order = (
        PurchaseOrder.objects.select_related("supplier_party")
        .filter(id=int(order_id), company=request.company, branch=request.branch)
        .first()
    )
    if order is None:
        raise ProcurementNotFoundError("orden de compra no encontrada")
    payload = _order_payload(order)
    payload["receipts"] = [
        {
            "id": r.id,
            "number": r.number,
            "warehouse_id": r.warehouse_id,
            "warehouse_name": r.warehouse.name,
            "posted_at": r.posted_at.isoformat(),
            "received_by": getattr(r.received_by, "username", None),
            "lines": [
                {
                    "order_line_id": rl.order_line_id,
                    "item_sku": rl.order_line.item.sku,
                    "item_name": rl.order_line.item.name,
                    "qty": str(rl.qty),
                    "unit_cost": str(rl.unit_cost),
                }
                for rl in r.lines.select_related("order_line__item")
            ],
        }
        for r in order.receipts.select_related("warehouse", "received_by").order_by("id")
    ]
    payload["invoices"] = [
        {
            "id": d.id,
            "series": d.series,
            "number": d.number,
            "status": d.status,
            "total": str(d.total),
            "supplier_ref": d.supplier_ref,
            "created_at": d.created_at.isoformat(),
        }
        for d in order.invoices.order_by("id")
    ]
    payload["pending_to_invoice"] = str(_pending_to_invoice(order))
    return payload


# --------------------------------------------------------------------------- 3-way match

def match_tolerance_pct() -> Decimal:
    return Decimal(str(getattr(settings, "PROCUREMENT_MATCH_TOLERANCE_PCT", "2.0")))


def _received_value(order: PurchaseOrder) -> Decimal:
    """Valor recibido (con IVA de la línea) según cantidades acumuladas."""
    value = Decimal("0.00")
    for ln in order.lines.all():
        value += _q2(ln.qty_received * ln.unit_cost * (Decimal("1") + ln.tax_rate))
    return _q2(value)


def _invoiced_value(order: PurchaseOrder) -> Decimal:
    """Σ facturas ligadas NO anuladas (DRAFT incluidas: anti doble factura).

    Un borrador huérfano bloquea el match — escape: anularlo o match_override.
    """
    total = Decimal("0.00")
    for d in order.invoices.exclude(status=PurchaseDocStatus.VOIDED):
        total += Decimal(d.total)
    return _q2(total)


def _pending_to_invoice(order: PurchaseOrder) -> Decimal:
    return _q2(_received_value(order) - _invoiced_value(order))


def create_invoice_for_order(
    *,
    request,
    actor,
    order_id: int,
    subtotal: Decimal,
    tax_total: Decimal,
    total: Decimal,
    supplier_ref: str = "",
    external_ref: str = "",
    notes: str = "",
    match_override: bool = False,
    allow_match_override: bool = False,
    idempotency_key: str = "",
) -> dict:
    """Factura del proveedor ligada a la OC con 3-way match (OC↔recepción↔factura).

    Crea el ``PurchaseDocument`` SUPPLIER_INVOICE en DRAFT; el posteo (y la CxP)
    siguen el flujo existente de documentos de compra.
    """
    company = request.company

    with transaction.atomic():
        order = _order_for_update(request=request, order_id=order_id)
        if order.status not in (
            PurchaseOrderStatus.SENT,
            PurchaseOrderStatus.PARTIALLY_RECEIVED,
            PurchaseOrderStatus.RECEIVED,
            PurchaseOrderStatus.CLOSED,
        ):
            raise ProcurementError("PROCUREMENT_ORDER_NOT_INVOICEABLE")

        total = _q2(Decimal(str(total)))
        pending = _pending_to_invoice(order)
        tolerance = match_tolerance_pct()
        overridden = bool(match_override and allow_match_override)
        deviation = abs(total - pending)
        allowed = _q2(pending * tolerance / Decimal("100")) if pending > 0 else Decimal("0.00")

        if not overridden:
            if pending <= 0:
                raise ProcurementMatchError("PROCUREMENT_MATCH_NOTHING_TO_INVOICE")
            if deviation > allowed:
                raise ProcurementMatchError("PROCUREMENT_MATCH_OUT_OF_TOLERANCE")

        res = create_purchase_draft(
            request=request,
            actor=actor,
            doc_type=PurchaseDocType.SUPPLIER_INVOICE,
            series="P",
            currency=order.currency,
            supplier_name=order.supplier_party.display_name,
            supplier_ref=supplier_ref,
            external_ref=external_ref,
            subtotal=Decimal(str(subtotal)),
            tax_total=Decimal(str(tax_total)),
            total=total,
            supplier_party_id=order.supplier_party_id,
            notes=notes,
            idempotency_key=idempotency_key,
            purchase_order_id=order.id,
        )
        emit_service_event(
            company=company,
            branch=request.branch,
            request=request,
            module="PROCUREMENT",
            event_type="PROCUREMENT_INVOICE_MATCHED",
            reason_code="PROCUREMENT_OK",
            actor_user=actor,
            subject_type="PROCUREMENT_DOC",
            subject_id=str(res.doc_id),
            metadata={
                "order_id": order.id,
                "invoice_total": str(total),
                "pending_to_invoice": str(pending),
                "deviation": str(_q2(deviation)),
                "tolerance_pct": str(tolerance),
                "override": overridden,
            },
        )
        return {
            "doc_id": res.doc_id,
            "order_id": order.id,
            "pending_to_invoice": str(pending),
            "deviation": str(_q2(deviation)),
            "override": overridden,
        }


# --------------------------------------------------------------------------- reorden

def reorder_suggestions(*, company, branch) -> list[dict]:
    """Artículos bajo el punto de reorden con cantidad y proveedor sugeridos.

    qty sugerida = (max_stock_qty ?? reorder_point×2) − existencia (mínimo 1, entero
    hacia arriba). Proveedor sugerido = el del último costo recibido más reciente.
    """
    balances = (
        StockBalance.objects.filter(
            company=company, branch=branch, qty_on_hand__lt=F("item__reorder_point")
        )
        .select_related("item")
        .order_by("item__sku")
    )
    # Existencia total por item en la sucursal (puede haber varias bodegas).
    by_item: dict[int, dict] = {}
    for bal in balances:
        agg = by_item.setdefault(
            bal.item_id,
            {"item": bal.item, "qty_on_hand": Decimal("0")},
        )
        agg["qty_on_hand"] += Decimal(bal.qty_on_hand)

    suggestions = []
    for item_id, agg in by_item.items():
        item = agg["item"]
        on_hand = agg["qty_on_hand"]
        target = (
            Decimal(item.max_stock_qty)
            if item.max_stock_qty is not None
            else Decimal(item.reorder_point) * 2
        )
        suggested = (target - on_hand).quantize(Decimal("1"), rounding=ROUND_CEILING)
        if suggested < 1:
            suggested = Decimal("1")
        price = (
            SupplierItemPrice.objects.filter(company=company, item_id=item_id)
            .exclude(last_receipt_at=None)
            .select_related("supplier_party")
            .order_by("-last_receipt_at")
            .first()
        )
        suggestions.append(
            {
                "item_id": item_id,
                "sku": item.sku,
                "name": item.name,
                "qty_on_hand": str(on_hand),
                "reorder_point": str(item.reorder_point),
                "suggested_qty": str(suggested),
                "supplier_party_id": price.supplier_party_id if price else None,
                "supplier_display_name": price.supplier_party.display_name if price else None,
                "last_cost": str(price.last_cost) if price and price.last_cost is not None else None,
                "agreed_price": str(price.agreed_price) if price and price.agreed_price is not None else None,
                "currency": price.currency if price else "NIO",
            }
        )
    return suggestions


def create_draft_orders_from_suggestions(*, request, actor, items: list[dict]) -> dict:
    """Convierte sugerencias seleccionadas en OC borrador, agrupando por proveedor."""
    if not items:
        raise ProcurementError("PROCUREMENT_LINES_REQUIRED")
    by_supplier: dict[int, list[dict]] = {}
    for it in items:
        supplier_id = it.get("supplier_party_id")
        if not supplier_id:
            raise ProcurementError("PROCUREMENT_SUPPLIER_REQUIRED")
        by_supplier.setdefault(int(supplier_id), []).append(
            {"item_id": int(it["item_id"]), "qty": str(it["qty"])}
        )
    orders = []
    for supplier_id, lines in by_supplier.items():
        res = create_purchase_order(
            request=request,
            actor=actor,
            supplier_party_id=supplier_id,
            lines=lines,
            notes="Generada desde sugerencia de reorden",
        )
        orders.append(
            {"order_id": res["order_id"], "supplier_party_id": supplier_id, "lines": len(lines)}
        )
    return {"orders": orders}


# --------------------------------------------------------------------------- precios

def upsert_supplier_item_price(
    *, request, actor, supplier_party_id: int, item_id: int, agreed_price, currency: str = "NIO"
) -> dict:
    company = request.company
    supplier_party = _load_supplier_party(supplier_party_id=supplier_party_id, company=company)
    if supplier_party is None:
        raise ProcurementError("PROCUREMENT_SUPPLIER_REQUIRED")
    item = InventoryItem.objects.filter(company=company, id=int(item_id)).first()
    if item is None:
        raise ProcurementError("PROCUREMENT_ITEM_NOT_FOUND")
    agreed = Decimal(str(agreed_price)) if agreed_price is not None else None
    if agreed is not None and agreed < 0:
        raise ProcurementError("PROCUREMENT_LINE_COST_INVALID")

    price, _created = SupplierItemPrice.objects.update_or_create(
        company=company,
        supplier_party=supplier_party,
        item=item,
        defaults={"agreed_price": agreed, "currency": (currency or "NIO").strip().upper()},
    )
    emit_service_event(
        company=company,
        branch=request.branch,
        request=request,
        module="PROCUREMENT",
        event_type="PROCUREMENT_PRICE_UPSERTED",
        reason_code="PROCUREMENT_OK",
        actor_user=actor,
        subject_type="SUPPLIER_PRICE",
        subject_id=str(price.id),
        metadata={
            "supplier_party_id": supplier_party.id,
            "item_id": item.id,
            "agreed_price": str(agreed) if agreed is not None else None,
        },
    )
    return {
        "id": price.id,
        "supplier_party_id": supplier_party.id,
        "item_id": item.id,
        "agreed_price": str(price.agreed_price) if price.agreed_price is not None else None,
        "last_cost": str(price.last_cost) if price.last_cost is not None else None,
        "currency": price.currency,
    }
