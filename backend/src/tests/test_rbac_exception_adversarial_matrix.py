"""L1: las excepciones al guard RBAC deben estar cerradas por otra credencial.

La matriz negativa impide que una entrada del allowlist se convierta en un POST
anónimo efectivo por accidente. Las pruebas de dominio ejercitan por separado
las credenciales válidas y el aislamiento A/B de dispositivo, grant y usuario.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


User = get_user_model()
ROOT = Path(__file__).resolve().parents[3]


EXCEPTION_NEGATIVE_MATRIX = {
    "backend/src/apps/kernels/nomina/biometric/views_biometric.py::BiometricPushView": (
        "/api/nomina/biometric/push/", {"checks": []}
    ),
    "backend/src/apps/modulos/accounts/views.py::BootstrapInitView": (
        "/api/auth/bootstrap/init/", {}
    ),
    "backend/src/apps/modulos/accounts/views.py::BootstrapOrgView": (
        "/api/auth/bootstrap/org/", {}
    ),
    "backend/src/apps/modulos/accounts/views.py::LoginView": (
        "/api/auth/login/", {"username": "missing", "password": "invalid"}
    ),
    "backend/src/apps/modulos/accounts/views.py::LogoutView": (
        "/api/auth/logout/", {}
    ),
    "backend/src/apps/modulos/accounts/views.py::PasswordChangeView": (
        "/api/auth/password/", {}
    ),
    "backend/src/apps/modulos/accounts/views.py::RefreshView": (
        "/api/auth/refresh/", {"refresh": "invalid"}
    ),
    "backend/src/apps/modulos/accounts/views.py::TwoFactorSetupView": (
        "/api/auth/2fa/enable/", {}
    ),
    "backend/src/apps/modulos/accounts/views.py::TwoFactorConfirmView": (
        "/api/auth/2fa/confirm/", {"code": "000000"}
    ),
    "backend/src/apps/modulos/accounts/views.py::TwoFactorVerifyView": (
        "/api/auth/2fa/verify/", {"challenge": "invalid", "code": "000000"}
    ),
    "backend/src/apps/modulos/accounts/views.py::TwoFactorDisableView": (
        "/api/auth/2fa/disable/", {"code": "000000"}
    ),
    "backend/src/apps/modulos/dashboard/views.py::EmbedTokenRedeemView": (
        "/api/backend/dashboard/embed-token/redeem/", {"token": "invalid"}
    ),
    "backend/src/apps/modulos/sync_engine/views.py::DeviceEnrollView": (
        "/api/sync/enroll/", {"enrollment_code": "invalid", "public_key_b64": "invalid"}
    ),
    "backend/src/apps/modulos/sync_engine/views.py::SyncBatchView": (
        "/api/sync/batch/", {"events": []}
    ),
}


def test_exception_matrix_matches_rbac_allowlist_exactly():
    baseline = json.loads((ROOT / "qa/contracts/route_authz_baseline.json").read_text(encoding="utf-8"))
    assert set(EXCEPTION_NEGATIVE_MATRIX) == set(baseline["allow"])
    assert len(EXCEPTION_NEGATIVE_MATRIX) == 14


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("exception_id", "endpoint_payload"),
    EXCEPTION_NEGATIVE_MATRIX.items(),
    ids=[key.rsplit("::", 1)[-1] for key in EXCEPTION_NEGATIVE_MATRIX],
)
def test_every_rbac_exception_fails_closed_without_its_credential(exception_id, endpoint_payload):
    del exception_id
    # BootstrapInit usa el estado global como credencial: una instalación con
    # cualquier usuario ya debe estar cerrada antes de validar el payload.
    User.objects.get_or_create(username="l1-system-initialized", defaults={"is_active": True})
    endpoint, payload = endpoint_payload
    response = APIClient().post(endpoint, payload, format="json")
    assert response.status_code >= 400, (endpoint, response.status_code, response.data)


@pytest.mark.django_db
def test_self_service_exceptions_do_not_accept_another_users_refresh_token():
    user_a = User.objects.create_user(
        username="l1-user-a", email="l1-user-a@test.local", password="Aa!9_user_a_Zx7"
    )
    User.objects.create_user(
        username="l1-user-b", email="l1-user-b@test.local", password="Aa!9_user_b_Zx7"
    )
    client_a = APIClient()
    login_a = client_a.post(
        "/api/auth/login/", {"username": user_a.username, "password": "Aa!9_user_a_Zx7"}, format="json"
    )
    login_b = APIClient().post(
        "/api/auth/login/", {"username": "l1-user-b", "password": "Aa!9_user_b_Zx7"}, format="json"
    )
    client_a.credentials(HTTP_AUTHORIZATION=f"Bearer {login_a.data['access']}")

    denied = client_a.post("/api/auth/logout/", {"refresh": login_b.data["refresh"]}, format="json")
    assert denied.status_code == 403

    # La credencial de B no fue revocada por A.
    still_valid = APIClient().post("/api/auth/refresh/", {"refresh": login_b.data["refresh"]}, format="json")
    assert still_valid.status_code == 200
