"""Tests del branding del holding/empresa (logo data-URL base64 + nombre).

Cubre: helper de validación (formato/mime/tamaño), endpoints GET/PUT con RBAC,
herencia empresa→holding y la exposición en `bootstrap/session`.
"""
from __future__ import annotations

import base64
import uuid

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.org.branding import MAX_LOGO_BYTES, parse_logo_data_url
from apps.modulos.org.models import OrgBranding
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

pytestmark = pytest.mark.django_db

User = get_user_model()
UT = OrgUnit.UnitType
BRANDING_URL = "/api/org/branding/"
SESSION_URL = "/api/auth/bootstrap/session/"

# PNG 1x1 transparente (válido, pequeño).
SMALL_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
SMALL_SVG = "data:image/svg+xml;base64," + base64.b64encode(
    b'<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"></svg>'
).decode()


def _mk_org():
    s = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=UT.HOLDING, name=f"H_{s}")
    company = OrgUnit.objects.create(unit_type=UT.COMPANY, name=f"C_{s}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=UT.BRANCH, name=f"B_{s}", parent=company)
    return holding, company, branch


def _client_with_perms(*, company, branch, perm_codes):
    username = f"brand_{uuid.uuid4().hex[:8]}"
    user = User.objects.create_user(username=username, email=f"{username}@test.local", password="pass12345")
    UserMembership.objects.create(user=user, org_unit=company, is_active=True)
    UserMembership.objects.create(user=user, org_unit=branch, is_active=True)
    role = Role.objects.create(name=f"role_{uuid.uuid4().hex[:8]}", is_active=True)
    for code in perm_codes:
        perm, _ = Permission.objects.get_or_create(code=code, defaults={"description": code, "is_active": True})
        RolePermission.objects.get_or_create(role=role, permission=perm)
    RoleAssignment.objects.create(user=user, role=role, org_unit=company, is_active=True)
    RoleAssignment.objects.create(user=user, role=role, org_unit=branch, is_active=True)

    client = APIClient()
    login = client.post("/api/auth/login/", {"username": user.username, "password": "pass12345"}, format="json")
    assert login.status_code == 200, login.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data.get('access')}")
    client.defaults["HTTP_X_COMPANY_ID"] = str(company.id)
    client.defaults["HTTP_X_BRANCH_ID"] = str(branch.id)
    return client


# --------------------------------------------------------------------------- #
# Helper de validación (puro)
# --------------------------------------------------------------------------- #

def test_parse_logo_empty_ok():
    assert parse_logo_data_url("") == ("", 0)
    assert parse_logo_data_url("   ") == ("", 0)


def test_parse_logo_valid_png_and_svg():
    mime, n = parse_logo_data_url(SMALL_PNG)
    assert mime == "image/png" and n > 0
    mime, n = parse_logo_data_url(SMALL_SVG)
    assert mime == "image/svg+xml" and n > 0


def test_parse_logo_bad_format_rejected():
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        parse_logo_data_url("no-soy-un-data-url")


def test_parse_logo_bad_mime_rejected():
    from django.core.exceptions import ValidationError

    bad = "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4").decode()
    with pytest.raises(ValidationError):
        parse_logo_data_url(bad)


def test_parse_logo_oversize_rejected():
    from django.core.exceptions import ValidationError

    big = "data:image/png;base64," + base64.b64encode(b"\x00" * (MAX_LOGO_BYTES + 1)).decode()
    with pytest.raises(ValidationError):
        parse_logo_data_url(big)


# --------------------------------------------------------------------------- #
# Modelo
# --------------------------------------------------------------------------- #

def test_model_rejects_non_holding_company_unit():
    from django.core.exceptions import ValidationError

    _holding, _company, branch = _mk_org()
    b = OrgBranding(org_unit=branch, display_name="X")
    with pytest.raises(ValidationError):
        b.full_clean()


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #

def test_put_company_branding_then_get():
    _holding, company, branch = _mk_org()
    client = _client_with_perms(
        company=company, branch=branch, perm_codes=["org.company.read", "org.company.update"]
    )
    res = client.put(
        BRANDING_URL,
        {"level": "company", "display_name": "Finca La Esperanza", "logo_data_url": SMALL_PNG},
        format="json",
    )
    assert res.status_code == 200, res.data

    stored = OrgBranding.objects.get(org_unit=company)
    assert stored.display_name == "Finca La Esperanza"
    assert stored.logo_mime == "image/png"  # derivado del data-URL

    res = client.get(BRANDING_URL)
    assert res.status_code == 200
    assert res.data["company"]["display_name"] == "Finca La Esperanza"
    assert res.data["holding"] is None


def test_put_holding_branding():
    holding, company, branch = _mk_org()
    client = _client_with_perms(
        company=company, branch=branch, perm_codes=["org.company.read", "org.company.update"]
    )
    res = client.put(
        BRANDING_URL, {"level": "holding", "display_name": "Grupo Santa Isabel"}, format="json"
    )
    assert res.status_code == 200, res.data
    assert OrgBranding.objects.filter(org_unit=holding).exists()
    res = client.get(BRANDING_URL)
    assert res.data["holding"]["display_name"] == "Grupo Santa Isabel"


def test_oversize_logo_rejected_by_api():
    _holding, company, branch = _mk_org()
    client = _client_with_perms(
        company=company, branch=branch, perm_codes=["org.company.read", "org.company.update"]
    )
    big = "data:image/png;base64," + base64.b64encode(b"\x00" * (MAX_LOGO_BYTES + 1)).decode()
    res = client.put(BRANDING_URL, {"level": "company", "logo_data_url": big}, format="json")
    assert res.status_code == 400


def test_bad_mime_rejected_by_api():
    _holding, company, branch = _mk_org()
    client = _client_with_perms(
        company=company, branch=branch, perm_codes=["org.company.read", "org.company.update"]
    )
    bad = "data:application/pdf;base64," + base64.b64encode(b"%PDF").decode()
    res = client.put(BRANDING_URL, {"level": "company", "logo_data_url": bad}, format="json")
    assert res.status_code == 400


def test_put_requires_update_permission():
    _holding, company, branch = _mk_org()
    client = _client_with_perms(company=company, branch=branch, perm_codes=["org.company.read"])
    res = client.put(BRANDING_URL, {"level": "company", "display_name": "X"}, format="json")
    assert res.status_code == 403


def test_session_branding_company_overrides_holding():
    holding, company, branch = _mk_org()
    client = _client_with_perms(
        company=company, branch=branch, perm_codes=["org.company.read", "org.company.update"]
    )
    # Solo holding → la sesión hereda el del holding.
    client.put(BRANDING_URL, {"level": "holding", "display_name": "Holding HQ"}, format="json")
    res = client.get(SESSION_URL)
    assert res.status_code == 200, res.data
    assert res.data["branding"]["display_name"] == "Holding HQ"

    # Branding propio de la empresa → pisa al del holding.
    client.put(BRANDING_URL, {"level": "company", "display_name": "Empresa Propia"}, format="json")
    res = client.get(SESSION_URL)
    assert res.data["branding"]["display_name"] == "Empresa Propia"
