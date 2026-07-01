"""API de notas por registro (company-scoped, append-only)."""
from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modulos.common.permissions import rbac_permission

from .models import RecordNote
from .serializers import NoteCreateSerializer, NoteSerializer


class HealthView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response({"ok": True, "module": "chatter"})


class NotesView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [rbac_permission("chatter.note.write")()]
        return [rbac_permission("chatter.note.read")()]

    def get(self, request):
        company = getattr(request, "company", None)
        if company is None:
            return Response({"detail": "X-Company-Id requerido"}, status=status.HTTP_400_BAD_REQUEST)
        subject_type = request.query_params.get("subject_type", "")
        subject_id = request.query_params.get("subject_id", "")
        if not subject_type or not subject_id:
            return Response(
                {"detail": "subject_type y subject_id son requeridos"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        qs = (
            RecordNote.objects.filter(
                company=company, subject_type=subject_type, subject_id=subject_id
            )
            .select_related("created_by")
            .order_by("-created_at")
        )
        return Response({"results": NoteSerializer(qs[:200], many=True).data})

    def post(self, request):
        company = getattr(request, "company", None)
        if company is None:
            return Response({"detail": "X-Company-Id requerido"}, status=status.HTTP_400_BAD_REQUEST)
        s = NoteCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        note = RecordNote.objects.create(
            company=company,
            subject_type=s.validated_data["subject_type"],
            subject_id=s.validated_data["subject_id"],
            body=s.validated_data["body"],
            created_by=request.user,
        )
        return Response(NoteSerializer(note).data, status=status.HTTP_201_CREATED)
