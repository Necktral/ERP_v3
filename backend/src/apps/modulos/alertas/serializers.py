from __future__ import annotations

from rest_framework import serializers

from .models import Alert


class AlertSerializer(serializers.ModelSerializer):
    acknowledged_by_username = serializers.CharField(
        source="acknowledged_by.username", read_only=True, default=""
    )

    class Meta:
        model = Alert
        fields = [
            "id", "alert_type", "severity", "subject_type", "subject_id",
            "title", "detail", "payload_json", "status",
            "first_seen_at", "last_seen_at", "resolved_at",
            "acknowledged_at", "acknowledged_by_username",
        ]
