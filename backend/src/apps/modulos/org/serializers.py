from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .branding import parse_logo_data_url


class CompanyCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    code = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    legal_name = serializers.CharField(required=False, allow_blank=True, default="")
    tax_id = serializers.CharField(required=False, allow_blank=True, default="")
    address = serializers.CharField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")


class BranchCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    code = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    address = serializers.CharField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")


class BranchUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200, required=False)
    code = serializers.CharField(max_length=64, required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    address = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)


class CompanyProfileUpdateSerializer(serializers.Serializer):
    legal_name = serializers.CharField(required=False, allow_blank=True)
    tax_id = serializers.CharField(required=False, allow_blank=True)
    address = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)


class OrgBrandingUpdateIn(serializers.Serializer):
    """Actualización del branding de un nivel (holding o empresa)."""

    level = serializers.ChoiceField(choices=["holding", "company"])
    display_name = serializers.CharField(required=False, allow_blank=True, max_length=120)
    tagline = serializers.CharField(required=False, allow_blank=True, max_length=160)
    logo_data_url = serializers.CharField(required=False, allow_blank=True)

    def validate_logo_data_url(self, value: str) -> str:
        try:
            parse_logo_data_url(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)
        return value


class ModuleStateOut(serializers.Serializer):
    code = serializers.CharField()
    category = serializers.CharField()
    core = serializers.BooleanField()
    is_enabled = serializers.BooleanField()

    def to_representation(self, instance: Any) -> dict[str, Any]:
        data = super().to_representation(instance)
        data["label"] = instance.get("label", "") if isinstance(instance, dict) else getattr(instance, "label", "")
        return data


class _ModuleChangeIn(serializers.Serializer):
    code = serializers.CharField()
    is_enabled = serializers.BooleanField()


class ModulesUpdateIn(serializers.Serializer):
    modules = _ModuleChangeIn(many=True)


_RELATIONSHIP_TYPES = ["ACCOUNTING", "INVENTORY", "CXC", "CXP", "OTHER"]


class IntercompanyRelationshipIn(serializers.Serializer):
    """Declarar una relación intercompañía SIMPLE (sin montos ni cuentas)."""

    company_a_id = serializers.IntegerField()
    company_b_id = serializers.IntegerField()
    relationship_type = serializers.ChoiceField(choices=_RELATIONSHIP_TYPES, default="OTHER")
    note = serializers.CharField(required=False, allow_blank=True, default="")
    is_active = serializers.BooleanField(required=False, default=True)


class IntercompanyRelationshipUpdateIn(serializers.Serializer):
    relationship_type = serializers.ChoiceField(choices=_RELATIONSHIP_TYPES, required=False)
    note = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
