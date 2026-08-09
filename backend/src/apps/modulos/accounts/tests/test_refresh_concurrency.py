from __future__ import annotations

import threading

import pytest
from django.contrib.auth import get_user_model
from django.db import connection as db_conn
from rest_framework.test import APIClient

from apps.modulos.accounts.models import RefreshTokenSession

User = get_user_model()


@pytest.mark.django_db(transaction=True)
def test_refresh_rotation_concurrent_has_single_child():
    """BUG-028: un refresh padre sólo puede producir un descendiente válido."""
    password = "Aa!9_refresh_Zx7"
    User.objects.create_user(username="refresh_user", password=password)
    login = APIClient().post(
        "/api/auth/login/",
        {"username": "refresh_user", "password": password},
        format="json",
    )
    assert login.status_code == 200
    raw_refresh = login.data["refresh"]
    parent = RefreshTokenSession.objects.get(revoked_at__isnull=True)

    barrier = threading.Barrier(2, timeout=10)
    statuses: list[int] = []
    statuses_lock = threading.Lock()

    def attempt() -> None:
        try:
            barrier.wait()
            response = APIClient().post(
                "/api/auth/refresh/",
                {"refresh": raw_refresh},
                format="json",
            )
            with statuses_lock:
                statuses.append(response.status_code)
        finally:
            db_conn.close()

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    parent.refresh_from_db()
    assert sorted(statuses) == [200, 401]
    assert parent.revoked_at is not None
    assert parent.replaced_by_jti
    assert RefreshTokenSession.objects.filter(
        user=parent.user,
        revoked_at__isnull=True,
    ).count() == 1
