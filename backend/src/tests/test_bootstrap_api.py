import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient

from apps.modulos.iam.models import OrgUnit

User = get_user_model()


def _demo_pwd(label: str) -> str:
    return f"Aa!9_{label}_Zx7"


@pytest.mark.django_db
def test_bootstrap_status_fresh_when_no_users():
    client = APIClient()
    r = client.get("/api/auth/bootstrap/status/")
    assert r.status_code == 200
    assert r.data["is_fresh"] is True


@pytest.mark.django_db
def test_bootstrap_init_creates_first_admin():
    client = APIClient()
    root_pwd = _demo_pwd("root")
    r = client.post(
        "/api/auth/bootstrap/init/",
        {
            "username": "root",
            "email": "root@test.com",
            "password": root_pwd,
            "password_confirm": root_pwd,
        },
        format="json",
    )
    assert r.status_code == 201
    u = User.objects.get(username="root")
    assert u.is_superuser is True
    assert u.is_staff is True
    assert u.must_change_password is False

    r2 = client.get("/api/auth/bootstrap/status/")
    assert r2.status_code == 200
    assert r2.data["is_fresh"] is False


@pytest.mark.django_db
def test_bootstrap_init_rejects_password_mismatch():
    client = APIClient()
    r = client.post(
        "/api/auth/bootstrap/init/",
        {
            "username": "root",
            "email": "root@test.com",
            "password": _demo_pwd("ok"),
            "password_confirm": _demo_pwd("different"),
        },
        format="json",
    )
    assert r.status_code == 400
    # La API envuelve los errores de validación en {"error": {"details": {...}}}.
    assert "password_confirm" in r.data["error"]["details"]
    assert not User.objects.filter(username="root").exists()


@pytest.mark.django_db
@override_settings(
    AUTH_PASSWORD_VALIDATORS=[
        {
            "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
            "OPTIONS": {"min_length": 10},
        },
        {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
        {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
        {
            "NAME": "apps.modulos.accounts.password_validators.PasswordComplexityValidator",
            "OPTIONS": {"min_length": 10, "min_classes": 3},
        },
    ]
)
def test_bootstrap_status_exposes_password_policy():
    # El settings de test vacía los validadores; forzamos los reales (como en base/prod)
    # para verificar que _password_policy() los deriva correctamente (fuente única).
    r = APIClient().get("/api/auth/bootstrap/status/")
    assert r.status_code == 200
    policy = r.data["password_policy"]
    assert policy["min_length"] == 10
    assert policy["min_classes"] == 3
    assert policy["disallow_common"] is True
    assert policy["disallow_numeric_only"] is True
    assert "minúsculas" in policy["classes"]


@pytest.mark.django_db
def test_bootstrap_org_requires_auth_but_no_company_context_header():
    # 1) bootstrap init
    c = APIClient()
    root_pwd = _demo_pwd("root2")
    c.post(
        "/api/auth/bootstrap/init/",
        {
            "username": "root",
            "email": "root2@test.com",
            "password": root_pwd,
            "password_confirm": root_pwd,
        },
        format="json",
    )

    # 2) login
    login = c.post("/api/auth/login/", {"username": "root", "password": root_pwd}, format="json")
    assert login.status_code == 200
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    # 3) bootstrap org (sin X-Company-Id)
    r = c.post(
        "/api/auth/bootstrap/org/",
        {
            "holding_name": "HOLDING",
            "company_name": "ACME",
            "company_tax_id": "J-123",
            "branch_name": "ACME-1",
            "branch_address": "Main street",
        },
        format="json",
    )
    assert r.status_code == 200
    assert OrgUnit.objects.filter(unit_type=OrgUnit.UnitType.HOLDING).exists()
    assert OrgUnit.objects.filter(unit_type=OrgUnit.UnitType.COMPANY).exists()
    assert OrgUnit.objects.filter(unit_type=OrgUnit.UnitType.BRANCH).exists()

    # 4) /me refleja setup complete
    me = c.get("/api/auth/me/")
    assert me.status_code == 200
    assert me.data["is_setup_complete"] is True


@pytest.mark.django_db
def test_password_change_clears_must_change_password():
    temp_pwd = _demo_pwd("temp")
    new_pwd = _demo_pwd("new")
    u = User.objects.create_user(username="emp", password=temp_pwd, email="emp@test.com")
    u.must_change_password = True
    u.save(update_fields=["must_change_password"])

    c = APIClient()
    login = c.post("/api/auth/login/", {"username": "emp", "password": temp_pwd}, format="json")
    assert login.status_code == 200
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    r = c.post(
        "/api/auth/password/",
        {
            "old_password": temp_pwd,
            "new_password": new_pwd,
            "confirm_password": new_pwd,
        },
        format="json",
    )
    assert r.status_code == 200
    u.refresh_from_db()
    assert u.must_change_password is False

    # login with new password works
    c2 = APIClient()
    login2 = c2.post("/api/auth/login/", {"username": "emp", "password": new_pwd}, format="json")
    assert login2.status_code == 200


@pytest.mark.django_db
def test_bootstrap_init_establishes_session_and_returns_user():
    """Fix bootstrap: init deja la sesión INICIADA y devuelve el usuario, así el wizard avanza
    al paso 2 (org) SIN un /auth/login/ aparte (que, si fallaba, varaba el wizard en el paso 1)."""
    c = APIClient()
    pwd = _demo_pwd("solo")
    r = c.post(
        "/api/auth/bootstrap/init/",
        {"username": "root", "email": "r@test.com", "password": pwd, "password_confirm": pwd},
        format="json",
    )
    assert r.status_code == 201
    # 1) Devuelve el usuario (contrato que consume applyBootstrapUser en el frontend).
    assert r.data["user"]["username"] == "root"
    assert r.data["user"]["id"]
    assert "must_change_password" in r.data["user"]
    assert "is_setup_complete" in r.data["user"]

    # 2) La sesión quedó establecida por init → el paso siguiente (org, IsAuthenticated)
    #    funciona SIN login explícito. Soporta ambos transportes (cookie o header).
    if "access" in r.data:
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
    org = c.post(
        "/api/auth/bootstrap/org/",
        {
            "holding_name": "H",
            "company_name": "ACME",
            "company_tax_id": "J-1",
            "branch_name": "B1",
            "branch_address": "x",
        },
        format="json",
    )
    assert org.status_code == 200, org.data
    assert OrgUnit.objects.filter(unit_type=OrgUnit.UnitType.COMPANY).exists()


@pytest.mark.django_db(transaction=True)
def test_bootstrap_init_concurrent_creates_single_admin():
    """BUG-004: dos POST /bootstrap/init/ concurrentes en DB vacía deben crear UN solo admin.

    Sin el advisory lock + re-chequeo dentro de la txn, ambos POST pasaban el `User.objects.exists()`
    (los dos ven cero usuarios) y creaban dos superadmins. Con el fix, uno gana (201) y el otro es
    rechazado con 'Sistema ya inicializado' (400).
    """
    import threading
    from django.db import connection as db_conn

    barrier = threading.Barrier(2, timeout=10)
    results: list[int] = []
    results_lock = threading.Lock()

    def attempt(username: str) -> None:
        pwd = _demo_pwd(username)
        try:
            barrier.wait()  # sincroniza los dos hilos para maximizar el solape
            r = APIClient().post(
                "/api/auth/bootstrap/init/",
                {
                    "username": username,
                    "email": f"{username}@t.com",
                    "password": pwd,
                    "password_confirm": pwd,
                },
                format="json",
            )
            with results_lock:
                results.append(r.status_code)
        finally:
            db_conn.close()  # cada hilo cierra SU conexión (connection es thread-local)

    threads = [threading.Thread(target=attempt, args=(u,)) for u in ("adminA", "adminB")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert User.objects.count() == 1, f"esperaba 1 admin, hay {User.objects.count()}"
    assert sorted(results) == [201, 400], f"esperaba un 201 y un 400, obtuve {results}"


@pytest.mark.django_db(transaction=True)
def test_bootstrap_org_concurrent_creates_single_tree():
    """BUG-029: dos bootstrap org simultáneos producen un solo árbol."""
    import threading
    from django.db import connection as db_conn

    user = User.objects.create_superuser(username="org_admin", password=_demo_pwd("org"))
    barrier = threading.Barrier(2, timeout=10)
    results: list[int] = []
    results_lock = threading.Lock()
    payload = {
        "holding_name": "H",
        "company_name": "C",
        "company_tax_id": "J-1",
        "branch_name": "B",
        "branch_address": "x",
    }

    def attempt() -> None:
        try:
            client = APIClient()
            client.force_authenticate(user=user)
            barrier.wait()
            response = client.post("/api/auth/bootstrap/org/", payload, format="json")
            with results_lock:
                results.append(response.status_code)
        finally:
            db_conn.close()

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert sorted(results) == [200, 409]
    assert OrgUnit.objects.filter(unit_type=OrgUnit.UnitType.HOLDING).count() == 1
    assert OrgUnit.objects.filter(unit_type=OrgUnit.UnitType.COMPANY).count() == 1
    assert OrgUnit.objects.filter(unit_type=OrgUnit.UnitType.BRANCH).count() == 1
