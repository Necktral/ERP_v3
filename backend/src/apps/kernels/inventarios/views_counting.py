"""Vistas del conteo físico (Ola C) + valorización de inventario."""
from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modulos.common.pagination import coerce_int_param, get_limit_offset, paginate_queryset
from apps.modulos.common.permissions import rbac_permission

from .counting import (
    InventoryCountError,
    InventoryCountSoDError,
    approve_physical_count,
    cancel_physical_count,
    capture_physical_count,
    count_payload,
    create_physical_count,
    inventory_valuation,
)
from .models import PhysicalCount

# Códigos que significan "no existe" (404); el resto de negocio va a 422.
_NOT_FOUND = {"INVENTORY_COUNT_NOT_FOUND", "INVENTORY_COUNT_WAREHOUSE_NOT_FOUND"}


def _count_error_response(exc: InventoryCountError) -> Response:
    code = str(exc)
    if isinstance(exc, InventoryCountSoDError):
        http: int = status.HTTP_409_CONFLICT
    elif code in _NOT_FOUND:
        http = status.HTTP_404_NOT_FOUND
    else:
        http = status.HTTP_422_UNPROCESSABLE_ENTITY
    return Response({"detail": code}, status=http)


def _require_branch(request) -> Response | None:
    if not getattr(request, "branch", None):
        return Response({"detail": "X-Branch-Id requerido"}, status=status.HTTP_400_BAD_REQUEST)
    return None


class CountCreateSerializer(serializers.Serializer):
    warehouse_id = serializers.IntegerField(min_value=1)
    category = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class CountCaptureLineSerializer(serializers.Serializer):
    line_id = serializers.IntegerField(min_value=1)
    qty_counted = serializers.DecimalField(
        max_digits=18, decimal_places=4, min_value=Decimal("0")
    )


class CountCaptureSerializer(serializers.Serializer):
    lines = CountCaptureLineSerializer(many=True, allow_empty=False)


class PhysicalCountListCreateView(APIView):
    """GET lista hojas de conteo (count.read) + POST genera hoja (count.create)."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [rbac_permission("inventory.count.create")()]
        return [rbac_permission("inventory.count.read")()]

    def get(self, request):
        bad = _require_branch(request)
        if bad:
            return bad
        qs = (
            PhysicalCount.objects.filter(company=request.company, branch=request.branch)
            .select_related("warehouse", "created_by", "counted_by", "approved_by")
            .order_by("-created_at")
        )
        status_filter = (request.query_params.get("status") or "").strip().upper()
        if status_filter:
            qs = qs.filter(status=status_filter)
        limit, offset = get_limit_offset(request)
        total, rows = paginate_queryset(qs, limit=limit, offset=offset)
        results = [
            {
                "id": c.id,
                "status": c.status,
                "warehouse_id": c.warehouse_id,
                "warehouse_name": c.warehouse.name,
                "category": c.category,
                "notes": c.notes,
                "lines": c.lines.count(),
                "created_by": getattr(c.created_by, "username", None),
                "counted_by": getattr(c.counted_by, "username", None),
                "approved_by": getattr(c.approved_by, "username", None),
                "created_at": c.created_at,
            }
            for c in rows
        ]
        return Response({"count": total, "limit": limit, "offset": offset, "results": results})

    def post(self, request):
        bad = _require_branch(request)
        if bad:
            return bad
        s = CountCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        try:
            out = create_physical_count(
                request=request,
                actor=request.user,
                warehouse_id=v["warehouse_id"],
                category=v.get("category") or "",
                notes=v.get("notes") or "",
            )
        except InventoryCountError as exc:
            return _count_error_response(exc)
        return Response(out, status=status.HTTP_201_CREATED)


class PhysicalCountDetailView(APIView):
    permission_classes = [rbac_permission("inventory.count.read")]

    def get(self, request, count_id: int):
        bad = _require_branch(request)
        if bad:
            return bad
        count = (
            PhysicalCount.objects.filter(
                id=int(count_id), company=request.company, branch=request.branch
            )
            .select_related("warehouse", "created_by", "counted_by", "approved_by")
            .first()
        )
        if count is None:
            return Response(
                {"detail": "INVENTORY_COUNT_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(count_payload(count))


class PhysicalCountCaptureView(APIView):
    permission_classes = [rbac_permission("inventory.count.capture")]

    def post(self, request, count_id: int):
        bad = _require_branch(request)
        if bad:
            return bad
        s = CountCaptureSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            out = capture_physical_count(
                request=request,
                actor=request.user,
                count_id=int(count_id),
                lines=[dict(ln) for ln in s.validated_data["lines"]],
            )
        except InventoryCountError as exc:
            return _count_error_response(exc)
        return Response(out)


class PhysicalCountApproveView(APIView):
    permission_classes = [rbac_permission("inventory.count.approve")]

    def post(self, request, count_id: int):
        bad = _require_branch(request)
        if bad:
            return bad
        try:
            out = approve_physical_count(
                request=request, actor=request.user, count_id=int(count_id)
            )
        except InventoryCountError as exc:
            return _count_error_response(exc)
        return Response(out)


class PhysicalCountCancelView(APIView):
    permission_classes = [rbac_permission("inventory.count.create")]

    def post(self, request, count_id: int):
        bad = _require_branch(request)
        if bad:
            return bad
        try:
            out = cancel_physical_count(
                request=request, actor=request.user, count_id=int(count_id)
            )
        except InventoryCountError as exc:
            return _count_error_response(exc)
        return Response(out)


class InventoryValuationView(APIView):
    """Valorización del inventario (solo lectura): Σ existencia × costo promedio."""

    permission_classes = [rbac_permission("inventory.balance.read")]

    def get(self, request):
        bad = _require_branch(request)
        if bad:
            return bad
        warehouse_id = coerce_int_param(request.query_params.get("warehouse_id"), field="warehouse_id")
        return Response(
            inventory_valuation(
                company=request.company,
                branch=request.branch,
                warehouse_id=warehouse_id,
            )
        )
