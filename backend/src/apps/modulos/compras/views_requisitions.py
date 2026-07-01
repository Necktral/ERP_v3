"""Vistas de requisiciones de compra (Ola B): crear → enviar → aprobar/rechazar → convertir."""
from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modulos.common.pagination import get_limit_offset, paginate_queryset
from apps.modulos.common.permissions import rbac_permission

from .models import PurchaseRequisition
from .serializers import ConvertSerializer, RejectSerializer, RequisitionCreateSerializer
from .services import ProcurementError
from .services_requisitions import (
    approve_requisition,
    convert_requisition_to_order,
    create_requisition,
    reject_requisition,
    requisition_payload,
    submit_requisition,
)
from .views_orders import _proc_error_response, _require_branch


class RequisitionListCreateView(APIView):
    """GET lista (requisition.read) + POST crea borrador (requisition.create)."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [rbac_permission("procurement.requisition.create")()]
        return [rbac_permission("procurement.requisition.read")()]

    def get(self, request):
        bad = _require_branch(request)
        if bad:
            return bad
        qs = (
            PurchaseRequisition.objects.filter(company=request.company, branch=request.branch)
            .select_related("requested_by", "decided_by")
            .prefetch_related("lines__item")
            .order_by("-created_at")
        )
        status_filter = (request.query_params.get("status") or "").strip().upper()
        if status_filter:
            qs = qs.filter(status=status_filter)
        limit, offset = get_limit_offset(request)
        total, rows = paginate_queryset(qs, limit=limit, offset=offset)
        return Response(
            {
                "count": total,
                "limit": limit,
                "offset": offset,
                "results": [requisition_payload(r) for r in rows],
            }
        )

    def post(self, request):
        bad = _require_branch(request)
        if bad:
            return bad
        s = RequisitionCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        try:
            out = create_requisition(
                request=request, actor=request.user,
                lines=[dict(ln) for ln in v["lines"]], notes=v.get("notes") or "",
            )
        except ProcurementError as exc:
            return _proc_error_response(exc)
        return Response(out, status=status.HTTP_201_CREATED)


class RequisitionDetailView(APIView):
    permission_classes = [rbac_permission("procurement.requisition.read")]

    def get(self, request, req_id: int):
        bad = _require_branch(request)
        if bad:
            return bad
        req = (
            PurchaseRequisition.objects.filter(
                id=int(req_id), company=request.company, branch=request.branch
            )
            .select_related("requested_by", "decided_by")
            .first()
        )
        if req is None:
            return Response({"detail": "requisición no encontrada"}, status=status.HTTP_404_NOT_FOUND)
        return Response(requisition_payload(req))


class RequisitionSubmitView(APIView):
    permission_classes = [rbac_permission("procurement.requisition.create")]

    def post(self, request, req_id: int):
        bad = _require_branch(request)
        if bad:
            return bad
        try:
            out = submit_requisition(request=request, actor=request.user, requisition_id=int(req_id))
        except ProcurementError as exc:
            return _proc_error_response(exc)
        return Response(out)


class RequisitionApproveView(APIView):
    permission_classes = [rbac_permission("procurement.requisition.approve")]

    def post(self, request, req_id: int):
        bad = _require_branch(request)
        if bad:
            return bad
        try:
            out = approve_requisition(request=request, actor=request.user, requisition_id=int(req_id))
        except ProcurementError as exc:
            return _proc_error_response(exc)
        return Response(out)


class RequisitionRejectView(APIView):
    permission_classes = [rbac_permission("procurement.requisition.approve")]

    def post(self, request, req_id: int):
        bad = _require_branch(request)
        if bad:
            return bad
        s = RejectSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            out = reject_requisition(
                request=request, actor=request.user, requisition_id=int(req_id),
                reason=s.validated_data["reason"],
            )
        except ProcurementError as exc:
            return _proc_error_response(exc)
        return Response(out)


class RequisitionConvertView(APIView):
    permission_classes = [rbac_permission("procurement.order.create")]

    def post(self, request, req_id: int):
        bad = _require_branch(request)
        if bad:
            return bad
        s = ConvertSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            out = convert_requisition_to_order(
                request=request, actor=request.user, requisition_id=int(req_id),
                supplier_party_id=s.validated_data["supplier_party_id"],
            )
        except ProcurementError as exc:
            return _proc_error_response(exc)
        return Response(out, status=status.HTTP_201_CREATED)
