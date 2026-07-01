"""API de la planilla de complemento de salario (convenio personal, bruto en recibo).

Bajo `/api/nomina/periods/<period_id>/complement-sheets/...`. Patrón del kernel: APIView +
`rbac_permission` + `request.company`. El precio/monto lo arma el servidor desde el perfil
(ajustable por línea en DRAFT); net = gross siempre.
"""
from __future__ import annotations

from decimal import Decimal

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modulos.common.pagination import get_limit_offset, paginate_queryset
from apps.modulos.common.permissions import rbac_permission

from .models import PayrollPeriod, SalaryComplementLine, SalaryComplementSheet
from .services_complement import (
    approve_complement_sheet,
    complement_sheet_payload,
    create_complement_sheet,
    mark_complement_received,
    set_complement_line_amount,
    submit_complement_sheet,
)

_READ = "nomina.complement.read"
_MANAGE = "nomina.complement.manage"
_APPROVE = "nomina.complement.approve"


class _ComplementSheetCreateIn(serializers.Serializer):
    branch_id = serializers.IntegerField(required=False, allow_null=True)
    name = serializers.CharField(max_length=160, required=False, allow_blank=True, default="")


class _ComplementLineAmountIn(serializers.Serializer):
    amount_nio = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0"))


class _ComplementReceivedIn(serializers.Serializer):
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


def _period(request, period_id):
    return get_object_or_404(PayrollPeriod, id=period_id, company=request.company)


def _sheet(request, period_id, sheet_id):
    period = _period(request, period_id)
    return get_object_or_404(SalaryComplementSheet, id=sheet_id, period=period)


class ComplementSheetView(APIView):
    """GET lista hojas de complemento del período + POST crea (siembra desde el perfil)."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [rbac_permission(_MANAGE)()]
        return [rbac_permission(_READ)()]

    def get(self, request, period_id):
        period = _period(request, period_id)
        qs = period.complement_sheets.order_by("-created_at")
        st = (request.query_params.get("status") or "").strip().upper()
        if st:
            qs = qs.filter(status=st)
        limit, offset = get_limit_offset(request)
        total, rows = paginate_queryset(qs, limit=limit, offset=offset)
        results = [
            {"id": s.id, "name": s.name, "status": s.status, "branch_id": s.branch_id,
             "lines": s.lines.count(), "created_at": s.created_at}
            for s in rows
        ]
        return Response({"count": total, "limit": limit, "offset": offset, "results": results})

    def post(self, request, period_id):
        period = _period(request, period_id)
        s = _ComplementSheetCreateIn(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        branch = None
        if v.get("branch_id"):
            from apps.modulos.iam.models import OrgUnit
            branch = get_object_or_404(OrgUnit, id=v["branch_id"], parent=request.company)
        sheet = create_complement_sheet(
            request=request, actor=request.user, period=period, branch=branch, name=v.get("name", ""),
        )
        return Response(complement_sheet_payload(sheet), status=status.HTTP_201_CREATED)


class ComplementSheetDetailView(APIView):
    permission_classes = [rbac_permission(_READ)]

    def get(self, request, period_id, sheet_id):
        sheet = _sheet(request, period_id, sheet_id)
        return Response(complement_sheet_payload(sheet))


class ComplementSheetActionView(APIView):
    """POST submit | approve."""

    def get_permissions(self):
        # approve exige permiso propio (checker); submit usa manage (maker).
        action = (self.kwargs.get("action") or "").lower()
        if action == "approve":
            return [rbac_permission(_APPROVE)()]
        return [rbac_permission(_MANAGE)()]

    def post(self, request, period_id, sheet_id, action):
        sheet = _sheet(request, period_id, sheet_id)
        try:
            if action == "submit":
                sheet = submit_complement_sheet(request=request, actor=request.user, sheet=sheet)
            elif action == "approve":
                sheet = approve_complement_sheet(request=request, actor=request.user, sheet=sheet)
            else:
                return Response({"detail": f"Acción desconocida: {action}"}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(complement_sheet_payload(sheet))


class ComplementLineView(APIView):
    """PATCH monto de la línea (override en DRAFT) + POST marca recibido (firma)."""

    permission_classes = [rbac_permission(_MANAGE)]

    def _line(self, request, period_id, sheet_id, line_id):
        sheet = _sheet(request, period_id, sheet_id)
        return get_object_or_404(SalaryComplementLine, id=line_id, sheet=sheet)

    def patch(self, request, period_id, sheet_id, line_id):
        line = self._line(request, period_id, sheet_id, line_id)
        s = _ComplementLineAmountIn(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            line = set_complement_line_amount(
                request=request, actor=request.user, line=line, amount=s.validated_data["amount_nio"],
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"id": line.id, "amount_nio": str(line.amount_nio)})

    def post(self, request, period_id, sheet_id, line_id):
        line = self._line(request, period_id, sheet_id, line_id)
        s = _ComplementReceivedIn(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            line = mark_complement_received(
                request=request, actor=request.user, line=line, note=s.validated_data.get("note", ""),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"id": line.id, "received_at": line.received_at})


class ComplementReciboPdfView(APIView):
    """Recibo imprimible 'COMPLEMENTO DE SALARIO' (PDF) de una hoja aprobada/borrador."""

    permission_classes = [rbac_permission(_READ)]

    def get(self, request, period_id, sheet_id):
        from django.http import HttpResponse

        from .complement_recibo import render_complement_recibo_pdf

        sheet = _sheet(request, period_id, sheet_id)
        try:
            pdf = render_complement_recibo_pdf(sheet)
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="complemento_{sheet.id}.pdf"'
        return resp
