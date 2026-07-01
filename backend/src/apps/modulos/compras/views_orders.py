"""Vistas de órdenes de compra, recepciones, 3-way match, reorden y precios (Ola B)."""
from __future__ import annotations

from decimal import Decimal
from typing import Callable

from django.db.models import Q
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modulos.common.pagination import get_limit_offset, paginate_queryset
from apps.modulos.common.permissions import rbac_permission
from apps.modulos.rbac.selectors import get_effective_permissions_for_scope

from .models import PurchaseOrder
from .serializers import (
    CancelSerializer,
    OrderInvoiceSerializer,
    PurchaseOrderCreateSerializer,
    PurchaseOrderUpdateSerializer,
    ReceiveSerializer,
    SuggestionOrderSerializer,
    SupplierPriceUpsertSerializer,
)
from .services import ProcurementError, ProcurementNotFoundError
from .services_orders import (
    ProcurementMatchError,
    ProcurementSoDError,
    SupplierItemPrice,
    approve_purchase_order,
    cancel_purchase_order,
    close_purchase_order,
    create_draft_orders_from_suggestions,
    create_invoice_for_order,
    create_purchase_order,
    get_purchase_order_detail,
    mark_purchase_order_sent,
    receive_purchase_order,
    reorder_suggestions,
    submit_purchase_order,
    update_purchase_order,
    upsert_supplier_item_price,
)


def _proc_error_response(exc: ProcurementError) -> Response:
    code = str(exc)
    if isinstance(exc, ProcurementSoDError):
        http: int = status.HTTP_409_CONFLICT
    elif isinstance(exc, ProcurementMatchError):
        http = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif isinstance(exc, ProcurementNotFoundError):
        http = status.HTTP_404_NOT_FOUND
    elif code.startswith("PROCUREMENT_"):
        # Códigos de negocio: culpa del pedido, no del sistema.
        http = status.HTTP_422_UNPROCESSABLE_ENTITY
    else:
        http = status.HTTP_400_BAD_REQUEST
    return Response({"detail": code}, status=http)


def _require_branch(request) -> Response | None:
    if not getattr(request, "branch", None):
        return Response({"detail": "X-Branch-Id requerido"}, status=status.HTTP_400_BAD_REQUEST)
    return None


class PurchaseOrderListCreateView(APIView):
    """GET lista OCs (order.read) + POST crea borrador con líneas (order.create)."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [rbac_permission("procurement.order.create")()]
        return [rbac_permission("procurement.order.read")()]

    def get(self, request):
        bad = _require_branch(request)
        if bad:
            return bad
        qs = (
            PurchaseOrder.objects.filter(company=request.company, branch=request.branch)
            .select_related("supplier_party")
            .order_by("-created_at")
        )
        status_filter = (request.query_params.get("status") or "").strip().upper()
        if status_filter:
            qs = qs.filter(status=status_filter)
        supplier = request.query_params.get("supplier_party_id")
        if supplier:
            qs = qs.filter(supplier_party_id=int(supplier))
        q = (request.query_params.get("q") or "").strip()
        if q:
            filtro = Q(supplier_party__display_name__icontains=q) | Q(notes__icontains=q)
            if q.isdigit():
                filtro |= Q(number=int(q))
            qs = qs.filter(filtro)

        limit, offset = get_limit_offset(request)
        total, rows = paginate_queryset(qs, limit=limit, offset=offset)
        results = [
            {
                "id": o.id,
                "status": o.status,
                "series": o.series,
                "number": o.number,
                "currency": o.currency,
                "supplier_party_id": o.supplier_party_id,
                "supplier_display_name": o.supplier_party.display_name,
                "expected_date": o.expected_date,
                "subtotal": str(o.subtotal),
                "tax_total": str(o.tax_total),
                "total": str(o.total),
                "created_at": o.created_at,
            }
            for o in rows
        ]
        return Response({"count": total, "limit": limit, "offset": offset, "results": results})

    def post(self, request):
        bad = _require_branch(request)
        if bad:
            return bad
        s = PurchaseOrderCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        try:
            out = create_purchase_order(
                request=request,
                actor=request.user,
                supplier_party_id=v["supplier_party_id"],
                lines=[dict(ln) for ln in v["lines"]],
                currency=v.get("currency") or "NIO",
                series=v.get("series") or "OC",
                expected_date=v.get("expected_date"),
                notes=v.get("notes") or "",
                idempotency_key=v.get("idempotency_key") or "",
            )
        except ProcurementError as exc:
            return _proc_error_response(exc)
        return Response(out, status=status.HTTP_201_CREATED)


class PurchaseOrderDetailView(APIView):
    """GET detalle con líneas/recepciones/facturas (order.read) + PATCH solo DRAFT (order.create)."""

    def get_permissions(self):
        if self.request.method == "PATCH":
            return [rbac_permission("procurement.order.create")()]
        return [rbac_permission("procurement.order.read")()]

    def get(self, request, order_id: int):
        bad = _require_branch(request)
        if bad:
            return bad
        try:
            return Response(get_purchase_order_detail(request=request, order_id=order_id))
        except ProcurementError as exc:
            return _proc_error_response(exc)

    def patch(self, request, order_id: int):
        bad = _require_branch(request)
        if bad:
            return bad
        s = PurchaseOrderUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        try:
            out = update_purchase_order(
                request=request,
                actor=request.user,
                order_id=order_id,
                lines=[dict(ln) for ln in v["lines"]] if "lines" in v else None,
                expected_date=v.get("expected_date"),
                notes=v.get("notes"),
            )
        except ProcurementError as exc:
            return _proc_error_response(exc)
        return Response(out)


class _OrderActionView(APIView):
    """Acción simple sobre la OC (sin cuerpo)."""

    permission_code = ""
    action: Callable[..., dict] | None = None

    def get_permissions(self):
        return [rbac_permission(self.permission_code)()]

    def post(self, request, order_id: int):
        bad = _require_branch(request)
        if bad:
            return bad
        action = type(self).action
        if action is None:
            return Response({"detail": "PROCUREMENT_ACTION_NOT_CONFIGURED"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        try:
            out = action(request=request, actor=request.user, order_id=int(order_id))
        except ProcurementError as exc:
            return _proc_error_response(exc)
        return Response(out)


class PurchaseOrderSubmitView(_OrderActionView):
    permission_code = "procurement.order.submit"
    action = staticmethod(submit_purchase_order)


class PurchaseOrderApproveView(_OrderActionView):
    permission_code = "procurement.order.approve"
    action = staticmethod(approve_purchase_order)


class PurchaseOrderSendView(_OrderActionView):
    permission_code = "procurement.order.send"
    action = staticmethod(mark_purchase_order_sent)


class PurchaseOrderCloseView(_OrderActionView):
    permission_code = "procurement.order.close"
    action = staticmethod(close_purchase_order)


class PurchaseOrderCancelView(APIView):
    permission_classes = [rbac_permission("procurement.order.close")]

    def post(self, request, order_id: int):
        bad = _require_branch(request)
        if bad:
            return bad
        s = CancelSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            out = cancel_purchase_order(
                request=request, actor=request.user, order_id=int(order_id),
                reason=s.validated_data.get("reason") or "",
            )
        except ProcurementError as exc:
            return _proc_error_response(exc)
        return Response(out)


class PurchaseOrderReceiveView(APIView):
    permission_classes = [rbac_permission("procurement.order.receive")]

    def post(self, request, order_id: int):
        bad = _require_branch(request)
        if bad:
            return bad
        s = ReceiveSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        try:
            out = receive_purchase_order(
                request=request,
                actor=request.user,
                order_id=int(order_id),
                warehouse_id=v["warehouse_id"],
                lines=[dict(ln) for ln in v["lines"]],
                idempotency_key=v["idempotency_key"],
                notes=v.get("notes") or "",
            )
        except ProcurementError as exc:
            return _proc_error_response(exc)
        return Response(out, status=status.HTTP_201_CREATED)


class PurchaseOrderInvoiceView(APIView):
    """Factura del proveedor ligada a la OC con 3-way match (crea el draft)."""

    permission_classes = [rbac_permission("procurement.doc.create")]

    def post(self, request, order_id: int):
        bad = _require_branch(request)
        if bad:
            return bad
        s = OrderInvoiceSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data

        effective = get_effective_permissions_for_scope(
            request.user, company=request.company, branch=request.branch
        )
        allow_override = "*" in effective or "procurement.invoice.match_override" in effective
        if v["match_override"] and not allow_override:
            return Response(
                {"detail": "PROCUREMENT_MATCH_OVERRIDE_FORBIDDEN"}, status=status.HTTP_403_FORBIDDEN
            )

        try:
            out = create_invoice_for_order(
                request=request,
                actor=request.user,
                order_id=int(order_id),
                subtotal=v["subtotal"],
                tax_total=v.get("tax_total") or Decimal("0"),
                total=v["total"],
                supplier_ref=v.get("supplier_ref") or "",
                external_ref=v.get("external_ref") or "",
                notes=v.get("notes") or "",
                match_override=v["match_override"],
                allow_match_override=allow_override,
                idempotency_key=v.get("idempotency_key") or "",
            )
        except ProcurementError as exc:
            return _proc_error_response(exc)
        return Response(out, status=status.HTTP_201_CREATED)


class ReorderSuggestionsView(APIView):
    permission_classes = [rbac_permission("procurement.reorder.read")]

    def get(self, request):
        bad = _require_branch(request)
        if bad:
            return bad
        return Response(
            {"results": reorder_suggestions(company=request.company, branch=request.branch)}
        )


class ReorderCreateOrdersView(APIView):
    permission_classes = [rbac_permission("procurement.order.create")]

    def post(self, request):
        bad = _require_branch(request)
        if bad:
            return bad
        s = SuggestionOrderSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            out = create_draft_orders_from_suggestions(
                request=request, actor=request.user,
                items=[dict(it) for it in s.validated_data["items"]],
            )
        except ProcurementError as exc:
            return _proc_error_response(exc)
        return Response(out, status=status.HTTP_201_CREATED)


class SupplierPricesView(APIView):
    """GET lista precios por proveedor (price.read) + PUT upsert acordado (price.manage)."""

    def get_permissions(self):
        if self.request.method == "PUT":
            return [rbac_permission("procurement.price.manage")()]
        return [rbac_permission("procurement.price.read")()]

    def get(self, request):
        qs = (
            SupplierItemPrice.objects.filter(company=request.company)
            .select_related("supplier_party", "item")
            .order_by("supplier_party__display_name", "item__sku")
        )
        supplier = request.query_params.get("supplier_party_id")
        if supplier:
            qs = qs.filter(supplier_party_id=int(supplier))
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(item__sku__icontains=q)
                | Q(item__name__icontains=q)
                | Q(supplier_party__display_name__icontains=q)
            )
        limit, offset = get_limit_offset(request)
        total, rows = paginate_queryset(qs, limit=limit, offset=offset)
        results = [
            {
                "id": p.id,
                "supplier_party_id": p.supplier_party_id,
                "supplier_display_name": p.supplier_party.display_name,
                "item_id": p.item_id,
                "item_sku": p.item.sku,
                "item_name": p.item.name,
                "last_cost": str(p.last_cost) if p.last_cost is not None else None,
                "agreed_price": str(p.agreed_price) if p.agreed_price is not None else None,
                "currency": p.currency,
                "last_receipt_at": p.last_receipt_at,
            }
            for p in rows
        ]
        return Response({"count": total, "limit": limit, "offset": offset, "results": results})

    def put(self, request):
        s = SupplierPriceUpsertSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        try:
            out = upsert_supplier_item_price(
                request=request,
                actor=request.user,
                supplier_party_id=v["supplier_party_id"],
                item_id=v["item_id"],
                agreed_price=v.get("agreed_price"),
                currency=v.get("currency") or "NIO",
            )
        except ProcurementError as exc:
            return _proc_error_response(exc)
        return Response(out)
