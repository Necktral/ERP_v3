from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pyotp
import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connections
from rest_framework.test import APIClient

from apps.modulos.accounts.models import RefreshTokenSession
from apps.modulos.audit.models import AuditEvent


User = get_user_model()


@pytest.mark.django_db(transaction=True)
def test_two_factor_challenge_is_single_use_under_concurrency():
    """U1: un challenge TOTP concurrente emite una sola sesion autenticada."""
    secret = pyotp.random_base32()
    password = "Aa!9_two_factor_Zx7"
    user = User.objects.create_user(
        username="u1_2fa_concurrent",
        password=password,
        is_staff=True,
        totp_secret=secret,
        totp_enabled=True,
    )
    login = APIClient().post(
        "/api/auth/login/",
        {"username": user.username, "password": password},
        format="json",
        HTTP_USER_AGENT="u1-concurrent-agent",
        REMOTE_ADDR="127.0.0.8",
    )
    assert login.status_code == 202, login.data
    challenge = login.data["challenge"]
    code = pyotp.TOTP(secret).now()
    barrier = Barrier(2)

    def verify():
        close_old_connections()
        client = APIClient()
        barrier.wait(timeout=10)
        response = client.post(
            "/api/auth/2fa/verify/",
            {"challenge": challenge, "code": code},
            format="json",
            HTTP_USER_AGENT="u1-concurrent-agent",
            REMOTE_ADDR="127.0.0.8",
        )
        close_old_connections()
        return response.status_code, response.data

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: verify(), range(2)))
    finally:
        connections.close_all()

    assert sorted(status_code for status_code, _ in results) == [200, 400]
    assert RefreshTokenSession.objects.filter(user=user, revoked_at__isnull=True).count() == 1
    assert AuditEvent.objects.filter(event_type="AUTH_2FA_VERIFIED", actor_user=user).count() == 1

