"""Endpoints de cobranza (dunning) del kernel portfolio — Ola D."""
from __future__ import annotations

from rest_framework import status
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modulos.common.permissions import rbac_permission

from .collections import (
    collections_workbench,
    create_collection_reminder,
    list_collection_reminders,
)
from .services import PortfolioDomainError


class CollectionReminderCreateSerializer(serializers.Serializer):
    party_id = serializers.IntegerField(min_value=1)
    currency = serializers.CharField(max_length=8, required=False, default="NIO")
    level = serializers.IntegerField(min_value=1, max_value=3, required=False, allow_null=True)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


def _require_company(request) -> Response | None:
    if getattr(request, "company", None) is None:
        return Response({"detail": "X-Company-Id requerido"}, status=status.HTTP_400_BAD_REQUEST)
    return None


class CollectionsWorkbenchView(APIView):
    """Mesa de cobranza: clientes con saldo vencido y nivel de recordatorio sugerido."""

    permission_classes = [rbac_permission("portfolio.collections.read")]

    def get(self, request):
        err = _require_company(request)
        if err is not None:
            return err
        return Response({"results": collections_workbench(company=request.company)})


class CollectionRemindersView(APIView):
    """GET historial de recordatorios (read) + POST generar recordatorio (remind)."""

    def get_permissions(self):
        perm = (
            "portfolio.collections.remind"
            if self.request.method == "POST"
            else "portfolio.collections.read"
        )
        return [rbac_permission(perm)()]

    def get(self, request):
        err = _require_company(request)
        if err is not None:
            return err
        party_id = request.query_params.get("party_id")
        return Response({
            "results": list_collection_reminders(
                company=request.company,
                party_id=int(party_id) if party_id else None,
            )
        })

    def post(self, request):
        err = _require_company(request)
        if err is not None:
            return err
        s = CollectionReminderCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        try:
            result = create_collection_reminder(
                company=request.company,
                branch=getattr(request, "branch", None),
                actor=request.user,
                party_id=v["party_id"],
                currency=v["currency"],
                level=v.get("level"),
                notes=v["notes"],
            )
        except PortfolioDomainError as exc:
            return Response({"detail": exc.code}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(result, status=status.HTTP_201_CREATED)
