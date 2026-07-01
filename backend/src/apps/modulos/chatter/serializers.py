from __future__ import annotations

from rest_framework import serializers

from .models import RecordNote


class NoteCreateSerializer(serializers.Serializer):
    subject_type = serializers.CharField(max_length=64)
    subject_id = serializers.CharField(max_length=64)
    body = serializers.CharField(max_length=2000, allow_blank=False, trim_whitespace=True)


class NoteSerializer(serializers.ModelSerializer):
    author = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = RecordNote
        fields = ["id", "subject_type", "subject_id", "body", "author", "created_at"]
