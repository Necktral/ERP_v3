"""Requisiciones de compra (Ola B): 'necesito esto' → aprobación SoD → OC.

La requisición NO lleva proveedor (eso se decide al convertirla); los costos de la
OC resultante salen de SupplierItemPrice (acordado → último costo → error claro).
"""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.kernels.inventarios.models import InventoryItem
from apps.modulos.audit.service_audit import emit_service_event

from .models import (
    PurchaseRequisition,
    PurchaseRequisitionLine,
    PurchaseRequisitionStatus,
)
from .services import ProcurementError, ProcurementNotFoundError
from .services_orders import ProcurementSoDError, create_purchase_order


def _audit_req(*, request, actor, req: PurchaseRequisition, event_type: str, before: str, metadata=None):
    emit_service_event(
        company=req.company,
        branch=req.branch,
        request=request,
        module="PROCUREMENT",
        event_type=event_type,
        reason_code="PROCUREMENT_OK",
        actor_user=actor,
        subject_type="PROCUREMENT_REQUISITION",
        subject_id=str(req.id),
        before_snapshot={"status": before},
        after_snapshot={"status": req.status},
        metadata=dict(metadata or {}),
    )


def _req_for_update(*, request, requisition_id: int) -> PurchaseRequisition:
    try:
        return PurchaseRequisition.objects.select_for_update().get(
            id=int(requisition_id), company=request.company, branch=request.branch
        )
    except PurchaseRequisition.DoesNotExist as exc:
        raise ProcurementNotFoundError("requisición no encontrada") from exc


def requisition_payload(req: PurchaseRequisition) -> dict:
    return {
        "id": req.id,
        "status": req.status,
        "notes": req.notes,
        "requested_by": getattr(req.requested_by, "username", None),
        "decided_by": getattr(req.decided_by, "username", None),
        "rejection_reason": req.rejection_reason,
        "converted_order_id": req.converted_order_id,
        "created_at": req.created_at.isoformat(),
        "lines": [
            {
                "id": ln.id,
                "item_id": ln.item_id,
                "item_sku": ln.item.sku,
                "item_name": ln.item.name,
                "qty": str(ln.qty),
                "note": ln.note,
            }
            for ln in req.lines.select_related("item").order_by("id")
        ],
    }


def create_requisition(*, request, actor, lines: list[dict], notes: str = "") -> dict:
    company = request.company
    branch = request.branch
    if not lines:
        raise ProcurementError("PROCUREMENT_LINES_REQUIRED")

    item_ids = [int(ln["item_id"]) for ln in lines]
    items = {
        it.id: it
        for it in InventoryItem.objects.filter(company=company, id__in=item_ids, is_active=True)
    }
    with transaction.atomic():
        req = PurchaseRequisition.objects.create(
            company=company, branch=branch, notes=notes or "", requested_by=actor
        )
        for ln in lines:
            item = items.get(int(ln["item_id"]))
            if item is None:
                raise ProcurementError("PROCUREMENT_ITEM_NOT_FOUND")
            qty = Decimal(str(ln["qty"]))
            if qty <= 0:
                raise ProcurementError("PROCUREMENT_LINE_QTY_INVALID")
            PurchaseRequisitionLine.objects.create(
                requisition=req, item=item, qty=qty, note=(ln.get("note") or "")[:200]
            )
        _audit_req(request=request, actor=actor, req=req,
                   event_type="PROCUREMENT_REQ_CREATED", before="",
                   metadata={"lines": len(lines)})
        return {"requisition_id": req.id, "status": req.status}


def submit_requisition(*, request, actor, requisition_id: int) -> dict:
    with transaction.atomic():
        req = _req_for_update(request=request, requisition_id=requisition_id)
        if req.status != PurchaseRequisitionStatus.DRAFT:
            raise ProcurementError("PROCUREMENT_REQ_NOT_DRAFT")
        if not req.lines.exists():
            raise ProcurementError("PROCUREMENT_LINES_REQUIRED")
        before = req.status
        req.status = PurchaseRequisitionStatus.SUBMITTED
        req.submitted_at = timezone.now()
        req.save(update_fields=["status", "submitted_at"])
        _audit_req(request=request, actor=actor, req=req,
                   event_type="PROCUREMENT_REQ_SUBMITTED", before=before)
        return {"requisition_id": req.id, "status": req.status}


def approve_requisition(*, request, actor, requisition_id: int) -> dict:
    with transaction.atomic():
        req = _req_for_update(request=request, requisition_id=requisition_id)
        if req.status != PurchaseRequisitionStatus.SUBMITTED:
            raise ProcurementError("PROCUREMENT_REQ_NOT_SUBMITTED")
        if req.requested_by_id is not None and actor is not None and actor.id == req.requested_by_id:
            raise ProcurementSoDError("PROCUREMENT_SOD_SELF_APPROVAL")
        before = req.status
        req.status = PurchaseRequisitionStatus.APPROVED
        req.decided_by = actor
        req.decided_at = timezone.now()
        req.save(update_fields=["status", "decided_by", "decided_at"])
        _audit_req(request=request, actor=actor, req=req,
                   event_type="PROCUREMENT_REQ_APPROVED", before=before)
        return {"requisition_id": req.id, "status": req.status}


def reject_requisition(*, request, actor, requisition_id: int, reason: str) -> dict:
    if not (reason or "").strip():
        raise ProcurementError("PROCUREMENT_REASON_REQUIRED")
    with transaction.atomic():
        req = _req_for_update(request=request, requisition_id=requisition_id)
        if req.status != PurchaseRequisitionStatus.SUBMITTED:
            raise ProcurementError("PROCUREMENT_REQ_NOT_SUBMITTED")
        if req.requested_by_id is not None and actor is not None and actor.id == req.requested_by_id:
            raise ProcurementSoDError("PROCUREMENT_SOD_SELF_APPROVAL")
        before = req.status
        req.status = PurchaseRequisitionStatus.REJECTED
        req.decided_by = actor
        req.decided_at = timezone.now()
        req.rejection_reason = reason.strip()[:255]
        req.save(update_fields=["status", "decided_by", "decided_at", "rejection_reason"])
        _audit_req(request=request, actor=actor, req=req,
                   event_type="PROCUREMENT_REQ_REJECTED", before=before,
                   metadata={"reason": req.rejection_reason})
        return {"requisition_id": req.id, "status": req.status}


def convert_requisition_to_order(
    *, request, actor, requisition_id: int, supplier_party_id: int
) -> dict:
    """APPROVED → CONVERTED: crea la OC en borrador con el proveedor elegido."""
    with transaction.atomic():
        req = _req_for_update(request=request, requisition_id=requisition_id)
        if req.status != PurchaseRequisitionStatus.APPROVED:
            raise ProcurementError("PROCUREMENT_REQ_NOT_APPROVED")

        lines = [
            {"item_id": ln.item_id, "qty": str(ln.qty), "description": ln.note or None}
            for ln in req.lines.all()
        ]
        res = create_purchase_order(
            request=request,
            actor=actor,
            supplier_party_id=supplier_party_id,
            lines=lines,
            notes=f"De requisición #{req.id}",
        )
        before = req.status
        req.status = PurchaseRequisitionStatus.CONVERTED
        req.converted_order_id = res["order_id"]
        req.converted_at = timezone.now()
        req.save(update_fields=["status", "converted_order", "converted_at"])
        _audit_req(request=request, actor=actor, req=req,
                   event_type="PROCUREMENT_REQ_CONVERTED", before=before,
                   metadata={"order_id": res["order_id"], "supplier_party_id": supplier_party_id})
        return {"requisition_id": req.id, "status": req.status, "order_id": res["order_id"]}
