"""Tests del comando seed_dev_environment (seed-data-steward).

Invariante: tras sembrar, el dev-admin queda como superuser con el rol
company_admin asignado, y ese rol incluye knowledge.dev.read (el permiso que le
faltaba a `san` para /feedback-codigo). Y el comando es idempotente.
"""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.modulos.rbac.models import Permission, RoleAssignment, RolePermission

UserModel = get_user_model()

_USERNAME = "dev_admin_seedtest"
_KW = {
    "admin_username": _USERNAME,
    "company_name": "Empresa SeedTest",
    "branch_name": "Sucursal SeedTest",
    "allow_non_debug": True,  # DEBUG=False bajo settings.test
}


@pytest.mark.django_db
def test_seed_dev_environment_grants_company_admin_with_dev_read():
    call_command("seed_dev_environment", **_KW)

    user = UserModel.objects.get(username=_USERNAME)
    assert user.is_superuser and user.is_staff and user.is_active

    ra = RoleAssignment.objects.filter(
        user=user, role__name="company_admin", is_active=True
    ).first()
    assert ra is not None, "el dev-admin debe tener company_admin asignado"

    dev_read = Permission.objects.filter(code="knowledge.dev.read").first()
    assert dev_read is not None, "el seed RBAC debe definir knowledge.dev.read"
    assert RolePermission.objects.filter(role=ra.role, permission=dev_read).exists(), (
        "company_admin debe incluir knowledge.dev.read (acceso a /feedback-codigo)"
    )


@pytest.mark.django_db
def test_seed_dev_environment_is_idempotent():
    call_command("seed_dev_environment", **_KW)
    call_command("seed_dev_environment", **_KW)

    assert UserModel.objects.filter(username=_USERNAME).count() == 1
    assert (
        RoleAssignment.objects.filter(
            user__username=_USERNAME, role__name="company_admin", is_active=True
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_seed_dev_environment_refuses_outside_debug_without_flag():
    with pytest.raises(Exception):
        call_command(
            "seed_dev_environment",
            admin_username="should_not_exist",
            company_name="X",
            branch_name="Y",
            # sin allow_non_debug y DEBUG=False → debe abortar
        )
    assert not UserModel.objects.filter(username="should_not_exist").exists()
