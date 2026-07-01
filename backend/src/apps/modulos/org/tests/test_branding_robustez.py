"""ROBUSTEZ del branding holding/empresa (`GET/PUT /api/org/branding/`).

Complementa `test_branding.py` (camino feliz + validación pura). Aquí se ATACA la superficie:

- LOGO BASE64 ≤256KB: logo sobre el tope, base64 inválido, data-URL malformado, MIME prohibido →
  4xx tipado, NUNCA 500. El logo se guarda como data-URL en JSON (no media).
- FUGAS POR EMPRESA: el branding de la empresa A NO se ve ni se edita desde la empresa B. El
  endpoint amarra el target a `request.company` (gateado por membresía), no a un id del cuerpo.
  El override por empresa hereda del holding, pero una empresa no lee/escribe el branding de otra.
- PERMISOS: GET reusa `org.company.read`, PUT reusa `org.company.update`; sin permiso → 403.
- ENTRADA BASURA: `level` inválido/ausente, tipos erróneos → 400.
"""
from __future__ import annotations

import base64
import uuid

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.org.branding import MAX_LOGO_BYTES
from apps.modulos.org.models import OrgBranding
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

pytestmark = pytest.mark.django_db

User = get_user_model()
UT = OrgUnit.UnitType
BRANDING_URL = "/api/org/branding/"

SMALL_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


# --------------------------------------------------------------------------- #
# Helpers (mismo estilo que test_branding.py)
# --------------------------------------------------------------------------- #

def _mk_org(holding=None):
    """Crea (holding, company, branch). Si se pasa holding, cuelga la company de él."""
    s = uuid.uuid4().hex[:6]
    if holding is None:
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
# LOGO BASE64 ≤256KB — entrada basura → 4xx tipado, NUNCA 500
# --------------------------------------------------------------------------- #

def test_logo_sobre_el_tope_es_400_no_500():
    _h, company, branch = _mk_org()
    client = _client_with_perms(company=company, branch=branch, perm_codes=["org.company.read", "org.company.update"])
    big = "data:image/png;base64," + base64.b64encode(b"\x00" * (MAX_LOGO_BYTES + 1)).decode()
    res = client.put(BRANDING_URL, {"level": "company", "logo_data_url": big}, format="json")
    assert res.status_code == 400
    # No debe haberse persistido nada del logo gigante.
    assert not OrgBranding.objects.filter(org_unit=company, logo_data_url=big).exists()


def test_logo_base64_invalido_es_400():
    _h, company, branch = _mk_org()
    client = _client_with_perms(company=company, branch=branch, perm_codes=["org.company.read", "org.company.update"])
    bad = "data:image/png;base64,@@@no-es-base64@@@"
    res = client.put(BRANDING_URL, {"level": "company", "logo_data_url": bad}, format="json")
    assert res.status_code == 400


def test_logo_data_url_malformado_es_400():
    _h, company, branch = _mk_org()
    client = _client_with_perms(company=company, branch=branch, perm_codes=["org.company.read", "org.company.update"])
    res = client.put(BRANDING_URL, {"level": "company", "logo_data_url": "esto-no-es-data-url"}, format="json")
    assert res.status_code == 400


def test_logo_mime_prohibido_es_400():
    _h, company, branch = _mk_org()
    client = _client_with_perms(company=company, branch=branch, perm_codes=["org.company.read", "org.company.update"])
    bad = "data:application/x-msdownload;base64," + base64.b64encode(b"MZ").decode()
    res = client.put(BRANDING_URL, {"level": "company", "logo_data_url": bad}, format="json")
    assert res.status_code == 400


def test_logo_html_svg_con_truco_de_mime_distinto_es_400():
    """Un payload con MIME no permitido (text/html) no debe colarse aunque sea base64 válido."""
    _h, company, branch = _mk_org()
    client = _client_with_perms(company=company, branch=branch, perm_codes=["org.company.read", "org.company.update"])
    bad = "data:text/html;base64," + base64.b64encode(b"<script>alert(1)</script>").decode()
    res = client.put(BRANDING_URL, {"level": "company", "logo_data_url": bad}, format="json")
    assert res.status_code == 400


def test_logo_en_el_tope_justo_es_aceptado():
    """Exactamente MAX_LOGO_BYTES (no +1) debe aceptarse: el borde inclusivo no rechaza de más."""
    _h, company, branch = _mk_org()
    client = _client_with_perms(company=company, branch=branch, perm_codes=["org.company.read", "org.company.update"])
    edge = "data:image/png;base64," + base64.b64encode(b"\x00" * MAX_LOGO_BYTES).decode()
    res = client.put(BRANDING_URL, {"level": "company", "logo_data_url": edge}, format="json")
    assert res.status_code == 200, res.data


# --------------------------------------------------------------------------- #
# ENTRADA BASURA en campos no-logo
# --------------------------------------------------------------------------- #

def test_level_invalido_es_400():
    _h, company, branch = _mk_org()
    client = _client_with_perms(company=company, branch=branch, perm_codes=["org.company.read", "org.company.update"])
    res = client.put(BRANDING_URL, {"level": "branch", "display_name": "X"}, format="json")
    assert res.status_code == 400


def test_level_ausente_es_400():
    _h, company, branch = _mk_org()
    client = _client_with_perms(company=company, branch=branch, perm_codes=["org.company.read", "org.company.update"])
    res = client.put(BRANDING_URL, {"display_name": "X"}, format="json")
    assert res.status_code == 400


def test_display_name_excede_max_length_es_400():
    _h, company, branch = _mk_org()
    client = _client_with_perms(company=company, branch=branch, perm_codes=["org.company.read", "org.company.update"])
    res = client.put(
        BRANDING_URL, {"level": "company", "display_name": "x" * 500}, format="json"
    )
    assert res.status_code == 400


def test_put_body_no_dict_no_revienta():
    _h, company, branch = _mk_org()
    client = _client_with_perms(company=company, branch=branch, perm_codes=["org.company.read", "org.company.update"])
    res = client.put(BRANDING_URL, [1, 2, 3], format="json")
    assert res.status_code in (400, 415)  # nunca 500


# --------------------------------------------------------------------------- #
# PERMISOS
# --------------------------------------------------------------------------- #

def test_get_sin_permiso_es_403():
    _h, company, branch = _mk_org()
    client = _client_with_perms(company=company, branch=branch, perm_codes=[])
    assert client.get(BRANDING_URL).status_code == 403


def test_put_sin_update_es_403():
    _h, company, branch = _mk_org()
    client = _client_with_perms(company=company, branch=branch, perm_codes=["org.company.read"])
    res = client.put(BRANDING_URL, {"level": "company", "display_name": "X"}, format="json")
    assert res.status_code == 403


def test_get_solo_con_read_es_200():
    _h, company, branch = _mk_org()
    client = _client_with_perms(company=company, branch=branch, perm_codes=["org.company.read"])
    assert client.get(BRANDING_URL).status_code == 200


# --------------------------------------------------------------------------- #
# FUGAS POR EMPRESA — aislamiento cross-company
# --------------------------------------------------------------------------- #

def test_empresa_b_no_lee_branding_de_empresa_a():
    """El branding propio de A no aparece en el GET de B (mismo holding)."""
    holding, company_a, branch_a = _mk_org()
    _h2, company_b, branch_b = _mk_org(holding=holding)  # misma cúpula

    # A pone su branding propio.
    client_a = _client_with_perms(
        company=company_a, branch=branch_a, perm_codes=["org.company.read", "org.company.update"]
    )
    client_a.put(
        BRANDING_URL, {"level": "company", "display_name": "MARCA-SECRETA-A", "logo_data_url": SMALL_PNG},
        format="json",
    )

    # B mira su propio branding: NO debe ver el de A.
    client_b = _client_with_perms(
        company=company_b, branch=branch_b, perm_codes=["org.company.read", "org.company.update"]
    )
    res = client_b.get(BRANDING_URL)
    assert res.status_code == 200, res.data
    assert res.data["company"] is None  # B no tiene branding propio
    # Y por supuesto no se filtra el de A en ningún campo.
    body = str(res.data)
    assert "MARCA-SECRETA-A" not in body


def test_empresa_b_no_sobrescribe_branding_de_empresa_a():
    """B haciendo PUT level=company escribe el SUYO, jamás el de A."""
    holding, company_a, branch_a = _mk_org()
    _h2, company_b, branch_b = _mk_org(holding=holding)

    client_a = _client_with_perms(
        company=company_a, branch=branch_a, perm_codes=["org.company.read", "org.company.update"]
    )
    client_a.put(BRANDING_URL, {"level": "company", "display_name": "A-ORIGINAL"}, format="json")

    client_b = _client_with_perms(
        company=company_b, branch=branch_b, perm_codes=["org.company.read", "org.company.update"]
    )
    res = client_b.put(BRANDING_URL, {"level": "company", "display_name": "B-INTRUSO"}, format="json")
    assert res.status_code == 200, res.data

    # El branding de A queda intacto; el de B es independiente.
    a = OrgBranding.objects.get(org_unit=company_a)
    b = OrgBranding.objects.get(org_unit=company_b)
    assert a.display_name == "A-ORIGINAL"
    assert b.display_name == "B-INTRUSO"


def test_usuario_de_b_no_puede_actuar_como_empresa_a_via_header():
    """Setear X-Company-Id de A sin membresía → 403 (no se puede editar branding ajeno)."""
    holding, company_a, branch_a = _mk_org()
    _h2, company_b, branch_b = _mk_org(holding=holding)

    # Usuario con membresía SOLO en B.
    client_b = _client_with_perms(
        company=company_b, branch=branch_b, perm_codes=["org.company.read", "org.company.update"]
    )
    # Intenta operar como empresa A cambiando los headers.
    client_b.defaults["HTTP_X_COMPANY_ID"] = str(company_a.id)
    client_b.defaults["HTTP_X_BRANCH_ID"] = str(branch_a.id)

    res_get = client_b.get(BRANDING_URL)
    assert res_get.status_code == 403  # sin acceso a esa empresa
    res_put = client_b.put(BRANDING_URL, {"level": "company", "display_name": "INTRUSO"}, format="json")
    assert res_put.status_code == 403
    # Nada se creó para A.
    assert not OrgBranding.objects.filter(org_unit=company_a).exists()


def test_empresa_b_hereda_holding_pero_no_branding_propio_de_a():
    """La herencia es del HOLDING, no de la empresa A: B ve el del holding, no el de A."""
    holding, company_a, branch_a = _mk_org()
    _h2, company_b, branch_b = _mk_org(holding=holding)

    # Holding tiene branding; A tiene el suyo propio.
    client_a = _client_with_perms(
        company=company_a, branch=branch_a, perm_codes=["org.company.read", "org.company.update"]
    )
    client_a.put(BRANDING_URL, {"level": "holding", "display_name": "HOLDING-COMUN"}, format="json")
    client_a.put(BRANDING_URL, {"level": "company", "display_name": "SOLO-A"}, format="json")

    client_b = _client_with_perms(
        company=company_b, branch=branch_b, perm_codes=["org.company.read", "org.company.update"]
    )
    res = client_b.get(BRANDING_URL)
    assert res.status_code == 200, res.data
    assert res.data["holding"]["display_name"] == "HOLDING-COMUN"  # heredado del holding
    assert res.data["company"] is None  # B no ve el branding propio de A
    assert "SOLO-A" not in str(res.data)
