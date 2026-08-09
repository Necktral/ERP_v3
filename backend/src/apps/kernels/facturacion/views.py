from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone as dj_timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modulos.common.pagination import get_limit_offset, paginate_queryset
from apps.modulos.common.permissions import rbac_permission
from apps.modulos.iam.models import OrgUnit

from .credit_notes import issue_credit_note
from .models import BillingDocument, CreditApprovalRequest, CreditStatus, SalesOrder
from .serializers import (
    BranchFiscalConfigOut,
    BranchFiscalConfigUpdateIn,
    CreditNoteIssueIn,
    DocContingencyResolveSerializer,
    DocContingencySerializer,
    DocCreateSerializer,
    DocIssueSerializer,
    DocListQuerySerializer,
    DocPrintSerializer,
    DocVoidSerializer,
    InvoiceCreateIn,
    InvoiceOut,
    OrderCreateIn,
    OrderResolveIn,
    OrderSubmitCreditIn,
    PaymentCreateIn,
    PaymentReverseIn,
)
from .services import (
    BillingError,
    BillingConflictError,
    BillingNotFoundError,
    BillingSoDError,
    convert_quote_to_invoice,
    create_draft,
    create_invoice,
    create_order,
    create_payment,
    get_or_update_branch_fiscal_config,
    issue_doc,
    mark_doc_contingency,
    queue_fiscal_print,
    resolve_credit_approval,
    resolve_doc_contingency,
    reverse_payment,
    reconcile_issued_credit_documents_receivables,
    submit_order_for_credit,
    void_doc,
)


def _customer_party_payload(doc: BillingDocument) -> dict[str, Any]:
    customer_party = doc.customer_party
    return {
        "customer_party_id": doc.customer_party_id,
        "customer_party_display_name": customer_party.display_name if customer_party is not None else "",
    }


class HealthView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response({"ok": True, "module": "billing"}, status=status.HTTP_200_OK)


class BillingReceivableReconcileView(APIView):
    permission_classes = [rbac_permission("portfolio.receivable.reconcile")]

    def post(self, request):
        if getattr(request, "branch", None) is None:
            return Response({"detail": "X-Branch-Id requerido."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            limit = int(request.data.get("limit", 200))
        except (TypeError, ValueError):
            return Response({"detail": "limit debe ser entero."}, status=status.HTTP_400_BAD_REQUEST)
        summary = reconcile_issued_credit_documents_receivables(
            company=request.company,
            branch=getattr(request, "branch", None),
            actor_user=request.user,
            request=request,
            limit=limit,
        )
        return Response({"ok": True, **summary}, status=status.HTTP_200_OK)


class BranchFiscalConfigView(APIView):
    def get_permissions(self):
        if self.request.method == "GET":
            return [rbac_permission("billing.fiscal.config.read")()]
        return [rbac_permission("billing.fiscal.config.update")()]

    def get(self, request):
        company = request.company
        branch = request.branch
        cfg = get_or_update_branch_fiscal_config(company=company, branch=branch)
        return Response(BranchFiscalConfigOut(cfg).data, status=status.HTTP_200_OK)

    def put(self, request):
        company = request.company
        branch = request.branch
        s = BranchFiscalConfigUpdateIn(data=request.data)
        s.is_valid(raise_exception=True)
        cfg = get_or_update_branch_fiscal_config(
            company=company,
            branch=branch,
            actor=request.user,
            data=s.validated_data,
        )
        return Response(BranchFiscalConfigOut(cfg).data, status=status.HTTP_200_OK)


class DocListCreateView(APIView):
    def get_permissions(self):
        if self.request.method == "GET":
            return [rbac_permission("billing.doc.read")()]
        return [rbac_permission("billing.doc.create")()]

    def get(self, request):
        if not getattr(request, "branch", None):
            return Response({"detail": "X-Branch-Id requerido"}, status=status.HTTP_400_BAD_REQUEST)

        s = DocListQuerySerializer(data=request.query_params)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        v = s.validated_data

        company: OrgUnit = request.company
        branch: OrgUnit = request.branch
        qs = BillingDocument.objects.select_related("customer_party").filter(company=company, branch=branch)

        if v.get("status"):
            qs = qs.filter(status=v["status"])
        if v.get("doc_type"):
            qs = qs.filter(doc_type=v["doc_type"])

        q = str(v.get("q") or "").strip()
        if q:
            predicate = Q(customer_name__icontains=q) | Q(customer_ref__icontains=q) | Q(series__icontains=q)
            if q.isdigit():
                predicate |= Q(number=int(q))
            qs = qs.filter(predicate)

        # Rango de timestamps sargable (created_at__date=DATE(col) impide usar el
        # índice btree). Semántica idéntica: días completos en el huso activo.
        if v.get("date_from"):
            start = dj_timezone.make_aware(datetime.combine(v["date_from"], time.min))
            qs = qs.filter(created_at__gte=start)
        if v.get("date_to"):
            end = dj_timezone.make_aware(datetime.combine(v["date_to"] + timedelta(days=1), time.min))
            qs = qs.filter(created_at__lt=end)

        ordering = str(v.get("ordering") or "-created_at")
        if ordering in {"id", "-id"}:
            qs = qs.order_by(ordering)
        else:
            qs = qs.order_by(ordering, "-id")

        limit, offset = get_limit_offset(request)
        total, rows = paginate_queryset(qs, limit=limit, offset=offset)
        results = [
            {
                "id": int(doc.id),
                "doc_type": doc.doc_type,
                "status": doc.status,
                "series": doc.series,
                "number": int(doc.number),
                "currency": doc.currency,
                "customer_name": doc.customer_name,
                "customer_ref": doc.customer_ref,
                **_customer_party_payload(doc),
                "subtotal": str(doc.subtotal),
                "tax_total": str(doc.tax_total),
                "total": str(doc.total),
                "payment_method": doc.payment_method,
                "payment_status": doc.payment_status,
                "amount_paid": str(doc.amount_paid),
                "credited_total": str(doc.credited_total or "0.00"),
                "is_fiscal": bool(doc.is_fiscal),
                "fiscal_status": doc.fiscal_status,
                "created_at": doc.created_at,
                "issued_at": doc.issued_at,
                "voided_at": doc.voided_at,
            }
            for doc in rows
        ]
        return Response({"count": total, "limit": limit, "offset": offset, "results": results}, status=status.HTTP_200_OK)

    def post(self, request):
        if not getattr(request, "branch", None):
            return Response({"detail": "X-Branch-Id requerido"}, status=status.HTTP_400_BAD_REQUEST)
        s = DocCreateSerializer(data=request.data)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        v = s.validated_data
        try:
            out = create_draft(
                request=request,
                actor=request.user,
                doc_type=v["doc_type"],
                series=v.get("series") or "A",
                currency=v.get("currency") or "NIO",
                customer_name=v.get("customer_name") or "",
                customer_ref=v.get("customer_ref") or "",
                customer_party_id=v.get("customer_party_id"),
                is_fiscal=bool(v.get("is_fiscal", False)),
                lines=v["lines"],
                idempotency_key=v.get("idempotency_key") or "",
                payment_method=v.get("payment_method") or "",
            )
        except BillingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"id": out.doc_id}, status=status.HTTP_201_CREATED)


class DocDetailView(APIView):
    permission_classes = [rbac_permission("billing.doc.read")]

    def get(self, request, doc_id: int):
        company: OrgUnit = request.company
        branch: OrgUnit = request.branch

        doc = get_object_or_404(
            BillingDocument.objects.select_related("customer_party"),
            id=doc_id,
            company=company,
            branch=branch,
        )
        lines = []
        for ln in doc.lines.all().order_by("id"):
            lines.append(
                {
                    "id": ln.id,
                    "description": ln.description,
                    "quantity": str(ln.quantity),
                    "unit_price": str(ln.unit_price),
                    "tax_rate": str(ln.tax_rate),
                    "discount_pct": str(ln.discount_pct),
                    "line_subtotal": str(ln.line_subtotal),
                    "line_tax": str(ln.line_tax),
                    "line_total": str(ln.line_total),
                    "inventory_item_id": ln.inventory_item_id,
                    "warehouse_id": ln.warehouse_id,
                }
            )
        return Response(
            {
                "id": doc.id,
                "doc_type": doc.doc_type,
                "status": doc.status,
                "series": doc.series,
                "number": doc.number,
                "currency": doc.currency,
                "customer_name": doc.customer_name,
                "customer_ref": doc.customer_ref,
                **_customer_party_payload(doc),
                "subtotal": str(doc.subtotal),
                "tax_total": str(doc.tax_total),
                "total": str(doc.total),
                "payment_method": doc.payment_method,
                "payment_status": doc.payment_status,
                "amount_paid": str(doc.amount_paid),
                "credited_total": str(doc.credited_total or "0.00"),
                "is_fiscal": bool(doc.is_fiscal),
                "issued_at": doc.issued_at,
                "voided_at": doc.voided_at,
                "void_reason": doc.void_reason,
                "fiscal": {
                    "mode": doc.fiscal_mode_resolved,
                    "status": doc.fiscal_status,
                    "reference": doc.fiscal_reference,
                    "evidence_id": doc.fiscal_evidence_id,
                    "printed_at": doc.printed_at,
                    "attempts": doc.print_attempt_count,
                    "last_error": doc.last_print_error,
                    "contingency_reason": doc.contingency_reason,
                    "contingency_at": doc.contingency_at,
                    "metadata": doc.fiscal_metadata_json or {},
                },
                "accounting": {
                    "status": doc.accounting_status,
                    "error": doc.accounting_error,
                    "economic_event_id": doc.accounting_economic_event_id,
                    "journal_draft_id": doc.accounting_journal_draft_id,
                    "journal_entry_id": doc.accounting_journal_entry_id,
                },
                "lines": lines,
            },
            status=status.HTTP_200_OK,
        )


class DocIssueView(APIView):
    permission_classes = [rbac_permission("billing.doc.issue")]

    def post(self, request, doc_id: int):
        if not getattr(request, "branch", None):
            return Response({"detail": "X-Branch-Id requerido"}, status=status.HTTP_400_BAD_REQUEST)
        s = DocIssueSerializer(data=request.data)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        v = s.validated_data
        try:
            out = issue_doc(
                request=request,
                actor=request.user,
                doc_id=doc_id,
                apply_inventory=bool(v.get("apply_inventory", False)),
                print_after_issue=bool(v.get("print_after_issue", False)),
                idempotency_key=v.get("idempotency_key") or "",
            )
        except BillingNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except BillingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(out, status=status.HTTP_200_OK)


class DocPrintView(APIView):
    permission_classes = [rbac_permission("billing.doc.print")]

    def post(self, request, doc_id: int):
        s = DocPrintSerializer(data=request.data)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            out = queue_fiscal_print(
                request=request,
                actor=request.user,
                doc_id=doc_id,
                idempotency_key=s.validated_data.get("idempotency_key") or "",
            )
        except BillingNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except BillingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "doc_id": out.doc_id,
                "job_id": out.job_id,
                "status": out.status,
                "created": out.created,
                "fiscal_status": out.fiscal_status,
            },
            status=status.HTTP_200_OK,
        )


class DocContingencyView(APIView):
    permission_classes = [rbac_permission("billing.doc.contingency")]

    def post(self, request, doc_id: int):
        s = DocContingencySerializer(data=request.data)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            out = mark_doc_contingency(
                request=request,
                actor=request.user,
                doc_id=doc_id,
                reason=s.validated_data["reason"],
            )
        except BillingNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except BillingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(out, status=status.HTTP_200_OK)


class DocContingencyResolveView(APIView):
    permission_classes = [rbac_permission("billing.doc.contingency.resolve")]

    def post(self, request, doc_id: int):
        s = DocContingencyResolveSerializer(data=request.data)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            out = resolve_doc_contingency(
                request=request,
                actor=request.user,
                doc_id=doc_id,
                action=s.validated_data["action"],
                idempotency_key=s.validated_data.get("idempotency_key") or "",
                reason=s.validated_data.get("reason") or "",
            )
        except BillingNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except BillingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(out, status=status.HTTP_200_OK)


class DocVoidView(APIView):
    permission_classes = [rbac_permission("billing.doc.void")]

    def post(self, request, doc_id: int):
        if not getattr(request, "branch", None):
            return Response({"detail": "X-Branch-Id requerido"}, status=status.HTTP_400_BAD_REQUEST)
        s = DocVoidSerializer(data=request.data)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        v = s.validated_data
        try:
            out = void_doc(
                request=request,
                actor=request.user,
                doc_id=doc_id,
                reason=v.get("reason") or "VOID",
            )
        except BillingNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except BillingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(out, status=status.HTTP_200_OK)


class BillingHealthView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        resp = Response({"ok": True, "module": "billing"})
        resp["X-Deprecated"] = "true"
        resp["X-Deprecation-Notice"] = "Use /api/billing/health/ (legacy será retirado en v1.1)"
        return resp


class InvoiceCreateView(APIView):
    permission_classes = [rbac_permission("billing.invoice.create")]

    def post(self, request):
        if not getattr(request, "branch", None):
            return Response({"detail": "X-Branch-Id requerido"}, status=status.HTTP_400_BAD_REQUEST)
        ser = InvoiceCreateIn(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            inv = create_invoice(
                request=request,
                company=request.company,
                branch=request.branch,
                actor_user=request.user,
                customer_name=ser.validated_data["customer_name"],
                total_amount=ser.validated_data["total_amount"],
            )
        except BillingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        resp = Response(InvoiceOut(inv).data, status=status.HTTP_201_CREATED)
        resp["X-Deprecated"] = "true"
        resp["X-Deprecation-Notice"] = "Use /api/billing/docs/ (legacy será retirado en v1.1)"
        return resp


# ---------------------------------------------------------------------------
# Abonos (pagos múltiples por documento)
# ---------------------------------------------------------------------------

def _payment_payload(p) -> dict[str, Any]:
    return {
        "id": p.id,
        "doc_id": p.doc_id,
        "payment_method": p.payment_method,
        "amount": str(p.amount),
        "currency": p.currency,
        "reference": p.reference,
        "notes": p.notes,
        "payment_date": p.payment_date,
        "status": p.status,
        "reversal_reason": p.reversal_reason,
        "reversed_at": p.reversed_at,
        "created_at": p.created_at,
    }


class DocPaymentsView(APIView):
    """GET → abonos del documento   POST → registrar abono."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [rbac_permission("billing.payment.create")()]
        return [rbac_permission("billing.payment.read")()]

    def get(self, request, doc_id: int):
        company: OrgUnit = request.company
        branch: OrgUnit = request.branch
        doc = get_object_or_404(BillingDocument, id=doc_id, company=company, branch=branch)
        payments = doc.payments.order_by("-created_at")
        return Response(
            {
                "doc_id": doc.id,
                "total": str(doc.total),
                "amount_paid": str(doc.amount_paid),
                "payment_status": doc.payment_status,
                "results": [_payment_payload(p) for p in payments],
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, doc_id: int):
        s = PaymentCreateIn(data=request.data)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        v = s.validated_data
        try:
            out = create_payment(
                request=request,
                actor=request.user,
                doc_id=doc_id,
                payment_method=v["payment_method"],
                amount=v["amount"],
                currency=v.get("currency") or "NIO",
                reference=v.get("reference") or "",
                notes=v.get("notes") or "",
                payment_date=v.get("payment_date"),
                idempotency_key=v["idempotency_key"],
            )
        except BillingNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except BillingConflictError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except BillingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(
            {
                "payment_id": out.payment_id,
                "doc_id": out.doc_id,
                "amount_paid": str(out.amount_paid),
                "payment_status": out.payment_status,
                "idempotent": out.idempotent,
            },
            status=status.HTTP_200_OK if out.idempotent else status.HTTP_201_CREATED,
        )


class PaymentReverseView(APIView):
    permission_classes = [rbac_permission("billing.payment.reverse")]

    def post(self, request, doc_id: int, payment_id: int):
        s = PaymentReverseIn(data=request.data)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            out = reverse_payment(
                request=request,
                actor=request.user,
                doc_id=doc_id,
                payment_id=payment_id,
                reason=s.validated_data["reason"],
            )
        except BillingNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except BillingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(out, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Nota de crédito vinculada (devoluciones)
# ---------------------------------------------------------------------------

class DocCreditNoteView(APIView):
    permission_classes = [rbac_permission("billing.credit_note.issue")]

    def post(self, request, doc_id: int):
        s = CreditNoteIssueIn(data=request.data)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        v = s.validated_data
        try:
            cn = issue_credit_note(
                request=request,
                actor=request.user,
                original_doc_id=doc_id,
                reason=v["reason"],
                lines=v.get("lines") or None,
                idempotency_key=v.get("idempotency_key") or "",
                restock=bool(v.get("restock", False)),
            )
        except BillingNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except BillingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(
            {
                "credit_note_id": cn.id,
                "number": cn.number,
                "total": str(cn.total),
                "original_doc_id": doc_id,
                "fiscal_status": cn.fiscal_status,
            },
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Cotización → Factura
# ---------------------------------------------------------------------------

class DocConvertView(APIView):
    permission_classes = [rbac_permission("billing.doc.create")]

    def post(self, request, doc_id: int):
        try:
            out = convert_quote_to_invoice(
                request=request,
                actor=request.user,
                doc_id=doc_id,
                idempotency_key=str(request.data.get("idempotency_key") or ""),
            )
        except BillingNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except BillingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response({"doc_id": out.doc_id, "converted_from": doc_id}, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Pedidos (SalesOrder) con aprobación de crédito SoD
# ---------------------------------------------------------------------------

def _order_payload(o) -> dict[str, Any]:
    # pending_approval_id: la solicitud de crédito PENDING del pedido (para que
    # el checker pueda resolver sin buscarla en la bitácora). En listados viene
    # anotada por subquery (_annotate_pending_approval); en payloads de una sola
    # fila se resuelve aquí con una query.
    pending_approval_id = getattr(o, "pending_approval_id", None)
    # Estados con solicitud de crédito viva (enum CreditStatus del pedido, NO el
    # ApprovalStatus de la solicitud — son enums distintos).
    credit_vivo = {CreditStatus.PENDING_REVIEW, CreditStatus.IN_REVIEW, CreditStatus.ESCALATED}
    if pending_approval_id is None and o.credit_status in credit_vivo:
        pending_approval_id = (
            CreditApprovalRequest.objects.filter(
                sales_order=o, status=CreditApprovalRequest.ApprovalStatus.PENDING
            )
            .order_by("-id")
            .values_list("id", flat=True)
            .first()
        )
    return {
        "id": o.id,
        "status": o.status,
        "credit_status": o.credit_status,
        "customer_name": o.customer_name,
        "customer_ref": o.customer_ref,
        "customer_party_id": o.customer_party_id,
        "currency": o.currency,
        "subtotal": str(o.subtotal),
        "tax_total": str(o.tax_total),
        "total": str(o.total),
        "expected_delivery_date": o.expected_delivery_date,
        "notes": o.notes,
        "billing_doc_id": o.billing_doc_id,
        "created_at": o.created_at,
        "pending_approval_id": pending_approval_id,
    }


def _annotate_pending_approval(qs):
    from django.db.models import OuterRef, Subquery

    pending = (
        CreditApprovalRequest.objects.filter(
            sales_order=OuterRef("pk"), status=CreditApprovalRequest.ApprovalStatus.PENDING
        )
        .order_by("-id")
        .values("id")[:1]
    )
    return qs.annotate(pending_approval_id=Subquery(pending))


class OrdersView(APIView):
    """GET → pedidos de la empresa   POST → crear pedido (encargo)."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [rbac_permission("billing.order.create")()]
        return [rbac_permission("billing.order.read")()]

    def get(self, request):
        company: OrgUnit = request.company
        qs = _annotate_pending_approval(SalesOrder.objects.filter(company=company).order_by("-created_at"))
        order_status = request.query_params.get("status")
        if order_status:
            qs = qs.filter(status=order_status)
        limit, offset = get_limit_offset(request)
        total, rows = paginate_queryset(qs, limit=limit, offset=offset)
        return Response(
            {"count": total, "limit": limit, "offset": offset, "results": [_order_payload(o) for o in rows]},
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        if not getattr(request, "branch", None):
            return Response({"detail": "X-Branch-Id requerido"}, status=status.HTTP_400_BAD_REQUEST)
        s = OrderCreateIn(data=request.data)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        v = s.validated_data
        try:
            out = create_order(
                request=request,
                actor=request.user,
                customer_name=v["customer_name"],
                customer_ref=v.get("customer_ref") or "",
                customer_party_id=v.get("customer_party_id"),
                currency=v.get("currency") or "NIO",
                lines=v["lines"],
                expected_delivery_date=v.get("expected_delivery_date"),
                notes=v.get("notes") or "",
            )
        except BillingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response({"order_id": out.order_id, "status": out.status}, status=status.HTTP_201_CREATED)


class OrderSubmitCreditView(APIView):
    permission_classes = [rbac_permission("billing.order.submit")]

    def post(self, request, order_id: int):
        s = OrderSubmitCreditIn(data=request.data)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            out = submit_order_for_credit(
                request=request,
                actor=request.user,
                order_id=order_id,
                request_notes=s.validated_data.get("request_notes") or "",
            )
        except BillingNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except BillingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(out, status=status.HTTP_200_OK)


class CreditApprovalResolveView(APIView):
    permission_classes = [rbac_permission("billing.order.approve")]

    def post(self, request, approval_id: int):
        s = OrderResolveIn(data=request.data)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        v = s.validated_data
        try:
            out = resolve_credit_approval(
                request=request,
                actor=request.user,
                approval_id=approval_id,
                approved=bool(v["approved"]),
                resolution_notes=v.get("resolution_notes") or "",
                approved_amount=v.get("approved_amount"),
                approved_terms_days=v.get("approved_terms_days"),
            )
        except BillingSoDError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except BillingNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except BillingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(out, status=status.HTTP_200_OK)
