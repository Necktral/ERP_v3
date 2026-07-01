"""API de alertas: listado con filtros + acciones humanas (ack/resolve) + escaneo manual."""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modulos.common.permissions import rbac_permission

from . import services
from .models import Alert
from .serializers import AlertSerializer


def _company_or_400(request):
    company = getattr(request, "company", None)
    if company is None:
        return None, Response(
            {"detail": "X-Company-Id requerido"}, status=status.HTTP_400_BAD_REQUEST
        )
    return company, None


class HealthView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response({"ok": True, "module": "alertas"})


class AlertListView(APIView):
    permission_classes = [rbac_permission("alerts.read")]

    def get(self, request):
        company, err = _company_or_400(request)
        if err:
            return err
        qs = Alert.objects.filter(company=company).select_related("acknowledged_by")
        for f in ("alert_type", "severity", "status", "subject_type"):
            val = request.query_params.get(f)
            if val:
                qs = qs.filter(**{f: val})
        qs = qs.order_by("status", "-severity", "-last_seen_at")
        return Response({"results": AlertSerializer(qs[:500], many=True).data})


class AlertAckView(APIView):
    permission_classes = [rbac_permission("alerts.ack")]

    def post(self, request, alert_id: int):
        company, err = _company_or_400(request)
        if err:
            return err
        alert = get_object_or_404(Alert, pk=alert_id, company=company)
        alert = services.acknowledge_alert(alert=alert, actor=request.user)
        return Response(AlertSerializer(alert).data)


class AlertResolveView(APIView):
    permission_classes = [rbac_permission("alerts.ack")]

    def post(self, request, alert_id: int):
        company, err = _company_or_400(request)
        if err:
            return err
        alert = get_object_or_404(Alert, pk=alert_id, company=company)
        alert = services.resolve_alert(alert=alert)
        return Response(AlertSerializer(alert).data)


class AlertScanView(APIView):
    """Disparo manual del escaneo de la empresa activa (además del comando periódico)."""

    permission_classes = [rbac_permission("alerts.scan")]

    def post(self, request):
        company, err = _company_or_400(request)
        if err:
            return err
        result = services.run_all_scanners(company=company)
        return Response({"scanned": result})
