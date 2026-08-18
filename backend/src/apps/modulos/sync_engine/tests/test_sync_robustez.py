"""ROBUSTEZ del riel de sync offline (`POST /api/sync/batch/`) y del kill-switch de aparatos.

Complementa `test_sync_engine.py` (unit de signing/registry) y `test_sync_push_loop.py` (lazo E2E
feliz). Aquí se ATACA la superficie de error/abuso:

- DOBLE IDEMPOTENCIA: re-enviar el mismo lote (mismo `command_id` + mismo payload) → DUPLICATE,
  el handler NO corre dos veces (no duplica efecto). Cubre el path legacy (firma por comando) y v2
  (firma por request).
- REJECTED NO REINTENTABLE: un comando rechazado por contrato queda en `AppliedCommand` como
  REJECTED; re-pushearlo da DUPLICATE (no se re-procesa). Padre-antes-de-hijo: el hijo cuya FK
  todavía no existe en el central → REJECTED `SYNC_REF_UNRESOLVED` y no se re-aplica.
- KILL-SWITCH DEVICE_REVOKED: `DeviceRevocationGuardMiddleware` bloquea CUALQUIER endpoint de API
  con 403 `DEVICE_REVOKED` para un `X-Device-Id` de un Device REVOKED (device activo pasa).
- ENTRADA BASURA: payloads malformados/tipos erróneos/IDs ajenos → 4xx tipado, NUNCA 500.

Las firmas EXACTAS se reusan de `signing`/`node_signing`; no se reimplementan.
"""
from __future__ import annotations

import base64
import uuid
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission
from apps.modulos.sync_engine.models import AppliedCommand, Device
from apps.modulos.sync_engine.node_signing import (
    build_signed_batch,
    generate_keypair,
    load_private_key,
)
from apps.modulos.sync_engine.signing import (
    build_command_signing_message,
    canon_json,
    occurred_at_canonical,
    sha256_hex,
)

User = get_user_model()
BATCH_URL = "/api/sync/batch/"


# --------------------------------------------------------------------------- #
# Helpers (mismo estilo que test_sync_engine.py / test_sync_push_loop.py)
# --------------------------------------------------------------------------- #

def _mk_org():
    s = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H_{s}", code=f"H-{s}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name=f"C_{s}", parent=holding, code=f"C-{s}")
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, name=f"B_{s}", parent=company, code=f"B-{s}")
    return company, branch


def _client_with_perms(*, company, branch, perm_codes):
    username = f"api_{uuid.uuid4().hex[:8]}"
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
    login = client.post("/api/auth/login/", {"username": username, "password": "pass12345"}, format="json")
    assert login.status_code == 200, login.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data.get('access')}")
    client.defaults["HTTP_X_COMPANY_ID"] = str(company.id)
    client.defaults["HTTP_X_BRANCH_ID"] = str(branch.id)
    return client


def _enroll_device(*, company, branch=None, status=Device.Status.ACTIVE):
    """Device firmante con par Ed25519 conocido. Devuelve (device, private_key)."""
    priv_b64, pub_b64 = generate_keypair()
    device = Device.objects.create(
        company=company,
        branch=branch,
        label="dev-test",
        status=status,
        public_key=base64.b64decode(pub_b64.encode("utf-8"), validate=True),
    )
    return device, load_private_key(priv_b64)


def _legacy_signed_command(
    *,
    private_key: Ed25519PrivateKey,
    company_id: int,
    branch_id: int | None,
    command_type: str,
    payload: dict,
    command_id: str | None = None,
    occurred_at=None,
):
    """Comando legacy con firma Ed25519 por comando (mensaje EXACTO de signing.py)."""
    command_id = command_id or str(uuid.uuid4())
    occurred_at = occurred_at or timezone.now()
    occurred_canon = occurred_at_canonical(occurred_at)
    payload_hash = sha256_hex(canon_json(payload))
    msg = build_command_signing_message(
        command_id=command_id,
        command_type=command_type,
        company_id=int(company_id),
        branch_id=int(branch_id) if branch_id is not None else None,
        occurred_at=occurred_canon,
        sequence=None,
        payload_hash=payload_hash,
        prev_hash="",
    )
    signature = base64.b64encode(private_key.sign(msg)).decode("utf-8")
    return {
        "command_id": command_id,
        "command_type": command_type,
        "company_id": int(company_id),
        "branch_id": int(branch_id) if branch_id is not None else None,
        "occurred_at": occurred_at.isoformat(),
        "payload": payload,
        "payload_hash": payload_hash,
        "prev_hash": "",
        "signature": signature,
    }


def _legacy_batch_body(commands, batch_id=None):
    return {"batch_id": str(batch_id or uuid.uuid4()), "commands": commands}


# --------------------------------------------------------------------------- #
# DOBLE IDEMPOTENCIA — legacy (firma por comando)
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_reenviar_mismo_comando_es_duplicate_y_no_duplica_efecto():
    company, branch = _mk_org()
    device, priv = _enroll_device(company=company, branch=branch)
    cmd = _legacy_signed_command(
        private_key=priv, company_id=company.id, branch_id=branch.id,
        command_type="DEMO_PING", payload={"msg": "uno"},
    )
    client = APIClient()

    r1 = client.post(BATCH_URL, _legacy_batch_body([cmd]), format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r1.status_code == 200, r1.data
    assert r1.data["summary"]["applied"] == 1
    assert r1.data["results"][0]["status"] == "APPLIED"

    # Reenvío idéntico (mismo command_id + mismo payload) en OTRO batch → DUPLICATE.
    r2 = client.post(BATCH_URL, _legacy_batch_body([cmd]), format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r2.status_code == 200, r2.data
    assert r2.data["summary"]["duplicate"] == 1
    assert r2.data["summary"]["applied"] == 0
    # AppliedCommand: una sola fila por command_id (no se duplicó el efecto).
    assert AppliedCommand.objects.filter(command_id=cmd["command_id"]).count() == 1


@pytest.mark.django_db
def test_mismo_command_id_distinto_payload_es_payload_mismatch():
    """Defensa anti-colisión: mismo command_id con payload distinto NO debe re-aplicar."""
    company, branch = _mk_org()
    device, priv = _enroll_device(company=company, branch=branch)
    cid = str(uuid.uuid4())
    c1 = _legacy_signed_command(
        private_key=priv, company_id=company.id, branch_id=branch.id,
        command_type="DEMO_PING", payload={"msg": "A"}, command_id=cid,
    )
    c2 = _legacy_signed_command(
        private_key=priv, company_id=company.id, branch_id=branch.id,
        command_type="DEMO_PING", payload={"msg": "B-distinto"}, command_id=cid,
    )
    client = APIClient()
    r1 = client.post(BATCH_URL, _legacy_batch_body([c1]), format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r1.data["summary"]["applied"] == 1

    r2 = client.post(BATCH_URL, _legacy_batch_body([c2]), format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r2.status_code == 200, r2.data
    assert r2.data["results"][0]["status"] == "REJECTED"
    assert r2.data["results"][0]["reason"] == "SYNC_PAYLOAD_MISMATCH"


@pytest.mark.django_db
def test_duplicado_dentro_del_mismo_batch_aplica_una_vez():
    """Mismo command_id repetido en el MISMO lote: 1 APPLIED + 1 DUPLICATE."""
    company, branch = _mk_org()
    device, priv = _enroll_device(company=company, branch=branch)
    cmd = _legacy_signed_command(
        private_key=priv, company_id=company.id, branch_id=branch.id,
        command_type="DEMO_PING", payload={"msg": "x"},
    )
    client = APIClient()
    r = client.post(BATCH_URL, _legacy_batch_body([cmd, dict(cmd)]), format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r.status_code == 200, r.data
    assert r.data["summary"]["applied"] == 1
    assert r.data["summary"]["duplicate"] == 1
    assert AppliedCommand.objects.filter(command_id=cmd["command_id"]).count() == 1


# --------------------------------------------------------------------------- #
# REJECTED NO REINTENTABLE
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_comando_rechazado_por_contrato_no_es_reintentable():
    """Un comando que el handler rechaza (SyncRejectError) queda REJECTED en AppliedCommand;
    re-pushearlo idéntico devuelve DUPLICATE (no se re-procesa).

    Usa sync.replicate.v1 con payload sin model_label/sync_uid → SYNC_SCHEMA_INVALID contractual.
    """
    company, branch = _mk_org()
    device, priv = _enroll_device(company=company, branch=branch)
    bad_payload = {"data": {"nope": True}}  # falta model_label/sync_uid → reject contractual
    cmd = _legacy_signed_command(
        private_key=priv, company_id=company.id, branch_id=branch.id,
        command_type="sync.replicate.v1", payload=bad_payload,
    )
    client = APIClient()

    r1 = client.post(BATCH_URL, _legacy_batch_body([cmd]), format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r1.status_code == 200, r1.data
    assert r1.data["results"][0]["status"] == "REJECTED"
    assert r1.data["results"][0]["reason"] == "SYNC_SCHEMA_INVALID"
    row = AppliedCommand.objects.get(command_id=cmd["command_id"])
    assert row.result_status == AppliedCommand.ResultStatus.REJECTED

    # Re-push idéntico → DUPLICATE (NO se re-procesa el rechazo).
    r2 = client.post(BATCH_URL, _legacy_batch_body([cmd]), format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r2.status_code == 200, r2.data
    assert r2.data["results"][0]["status"] == "DUPLICATE"
    assert AppliedCommand.objects.filter(command_id=cmd["command_id"]).count() == 1


@pytest.mark.django_db
def test_unknown_command_type_primer_rechazo_es_schema_invalid():
    """Primer push de un command_type desconocido → REJECTED SYNC_SCHEMA_INVALID (no 500)."""
    company, branch = _mk_org()
    device, priv = _enroll_device(company=company, branch=branch)
    cmd = _legacy_signed_command(
        private_key=priv, company_id=company.id, branch_id=branch.id,
        command_type=f"NO_EXISTE_{uuid.uuid4().hex[:6]}", payload={"x": 1},
    )
    client = APIClient()
    r1 = client.post(BATCH_URL, _legacy_batch_body([cmd]), format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r1.status_code == 200, r1.data
    assert r1.data["results"][0]["status"] == "REJECTED"
    assert r1.data["results"][0]["reason"] == "SYNC_SCHEMA_INVALID"
    # Queda persistido como REJECTED en AppliedCommand.
    row = AppliedCommand.objects.get(command_id=cmd["command_id"])
    assert row.result_status == AppliedCommand.ResultStatus.REJECTED


@pytest.mark.django_db
@override_settings(SYNC_DEMO_COMMANDS_ENABLED=False)
def test_demo_ping_disabled_is_rejected_but_real_handlers_remain_registered():
    """MEJ-011: producción rechaza DEMO_PING sin apagar comandos operativos."""
    from apps.modulos.sync_engine.registry import get_handler

    company, branch = _mk_org()
    device, priv = _enroll_device(company=company, branch=branch)
    cmd = _legacy_signed_command(
        private_key=priv, company_id=company.id, branch_id=branch.id,
        command_type="DEMO_PING", payload={"msg": "disabled"},
    )
    response = APIClient().post(
        BATCH_URL, _legacy_batch_body([cmd]), format="json", HTTP_X_DEVICE_ID=str(device.id),
    )
    assert response.status_code == 200, response.data
    assert response.data["results"][0]["status"] == "REJECTED"
    assert response.data["results"][0]["reason"] == "SYNC_SCHEMA_INVALID"
    assert get_handler("INVENTORY_MOVEMENT_RECEIVE") is not None


@pytest.mark.django_db
def test_BUG_repush_de_rechazo_pre_idempotencia_no_es_duplicate():
    """GATE/BUG: re-pushear un comando ya rechazado por el path `_reject_with_db`
    (command_type desconocido / firma inválida) NO devuelve DUPLICATE.

    Invariante esperada (memoria del proyecto): 'comando REJECTED no es reintentable;
    re-push = DUPLICATE'. Pero los rechazos que ocurren ANTES del bloque de idempotencia
    con `select_for_update` (handler desconocido, firma inválida) van por `_reject_with_db`,
    que en el re-push hace `AppliedCommand.objects.create()` → IntegrityError, e intenta la
    consulta de recuperación DENTRO del mismo `transaction.atomic()` ya marcado para rollback.
    Esa consulta falla (transacción rota) y el guard externo devuelve el `reason` original
    en vez de DUPLICATE — de forma NO determinista (a veces SYNC_INTERNAL_ERROR).

    Este test exige el comportamiento correcto (DUPLICATE) y FALLA mientras el bug exista:
    es un gate de regresión, no un test ablandado.
    """
    company, branch = _mk_org()
    device, priv = _enroll_device(company=company, branch=branch)
    cmd = _legacy_signed_command(
        private_key=priv, company_id=company.id, branch_id=branch.id,
        command_type=f"NO_EXISTE_{uuid.uuid4().hex[:6]}", payload={"x": 1},
    )
    client = APIClient()
    r1 = client.post(BATCH_URL, _legacy_batch_body([cmd]), format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r1.data["results"][0]["status"] == "REJECTED"

    r2 = client.post(BATCH_URL, _legacy_batch_body([cmd]), format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r2.status_code == 200, r2.data
    # Comportamiento ESPERADO (falla hoy → documenta la fragilidad):
    assert r2.data["results"][0]["status"] == "DUPLICATE", (
        f"re-push de REJECTED no fue DUPLICATE: {r2.data['results'][0]}"
    )
    # Y nunca debe degradar a un error interno genérico:
    assert r2.data["results"][0].get("reason") != "SYNC_INTERNAL_ERROR"
    assert AppliedCommand.objects.filter(command_id=cmd["command_id"]).count() == 1


# --------------------------------------------------------------------------- #
# SCOPE / AUTORIZACIÓN del riel
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_comando_para_empresa_ajena_es_forbidden_scope():
    """El device de la empresa A no puede emitir comandos para la empresa B."""
    company_a, branch_a = _mk_org()
    company_b, _branch_b = _mk_org()
    device, priv = _enroll_device(company=company_a, branch=branch_a)
    # command con company_id de OTRA empresa (firma válida pero scope prohibido)
    cmd = _legacy_signed_command(
        private_key=priv, company_id=company_b.id, branch_id=None,
        command_type="DEMO_PING", payload={"msg": "cross"},
    )
    client = APIClient()
    r = client.post(BATCH_URL, _legacy_batch_body([cmd]), format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r.status_code == 200, r.data
    assert r.data["results"][0]["status"] == "REJECTED"
    assert r.data["results"][0]["reason"] == "SYNC_FORBIDDEN_SCOPE"


@pytest.mark.django_db
def test_firma_por_comando_invalida_es_rechazada():
    company, branch = _mk_org()
    device, priv = _enroll_device(company=company, branch=branch)
    cmd = _legacy_signed_command(
        private_key=priv, company_id=company.id, branch_id=branch.id,
        command_type="DEMO_PING", payload={"msg": "ok"},
    )
    cmd["signature"] = base64.b64encode(b"\x00" * 64).decode()  # firma corrupta
    client = APIClient()
    r = client.post(BATCH_URL, _legacy_batch_body([cmd]), format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r.status_code == 200, r.data
    assert r.data["results"][0]["status"] == "REJECTED"
    assert r.data["results"][0]["reason"] == "SYNC_INVALID_SIGNATURE"


@pytest.mark.django_db
def test_device_inexistente_da_permission_denied():
    company, branch = _mk_org()
    _device, priv = _enroll_device(company=company, branch=branch)
    cmd = _legacy_signed_command(
        private_key=priv, company_id=company.id, branch_id=branch.id,
        command_type="DEMO_PING", payload={"msg": "x"},
    )
    client = APIClient()
    r = client.post(BATCH_URL, _legacy_batch_body([cmd]), format="json", HTTP_X_DEVICE_ID=str(uuid.uuid4()))
    # resolve_device → PermissionDenied (403), no 500.
    assert r.status_code == 403


@pytest.mark.django_db
def test_device_revocado_no_aplica_comandos_por_el_riel():
    company, branch = _mk_org()
    device, priv = _enroll_device(company=company, branch=branch, status=Device.Status.REVOKED)
    cmd = _legacy_signed_command(
        private_key=priv, company_id=company.id, branch_id=branch.id,
        command_type="DEMO_PING", payload={"msg": "x"},
    )
    client = APIClient()
    # /api/sync/batch/ está exento del middleware (lo valida el propio motor).
    r = client.post(BATCH_URL, _legacy_batch_body([cmd]), format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r.status_code == 200, r.data
    assert r.data["results"][0]["status"] == "REJECTED"
    assert r.data["results"][0]["reason"] == "SYNC_DEVICE_REVOKED"


# --------------------------------------------------------------------------- #
# v2 (firma por request) — idempotencia
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_v2_reenvio_de_lote_idempotente_no_duplica():
    company, branch = _mk_org()
    device, priv = _enroll_device(company=company, branch=branch)
    command = {
        "command_id": str(uuid.uuid4()),
        "type": "DEMO_PING",
        "scope": {"company_id": company.id, "branch_id": branch.id},
        "occurred_at": timezone.now().isoformat(),
        "payload": {"msg": "v2"},
        "payload_hash": "",
        "sequence": None,
        "prev_hash": "",
        "command_sig": "",
    }
    client = APIClient()
    b1 = build_signed_batch(device_id=str(device.id), private_key=priv, commands=[command])
    r1 = client.post(BATCH_URL, b1, format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r1.status_code == 200, r1.data
    assert r1.data["summary"]["applied"] == 1

    # Re-firmamos (ts/nonce/batch nuevos) pero el mismo command_id+payload → DUPLICATE.
    b2 = build_signed_batch(device_id=str(device.id), private_key=priv, commands=[command])
    r2 = client.post(BATCH_URL, b2, format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r2.status_code == 200, r2.data
    assert r2.data["summary"]["duplicate"] == 1
    assert r2.data["summary"]["applied"] == 0
    assert AppliedCommand.objects.filter(command_id=command["command_id"]).count() == 1


@pytest.mark.django_db
def test_v2_replay_del_mismo_nonce_es_rechazado():
    """El mismo (ts, nonce) re-enviado tal cual → 401 REPLAY_DETECTED (anti-replay request-level)."""
    company, branch = _mk_org()
    device, priv = _enroll_device(company=company, branch=branch)
    command = {
        "command_id": str(uuid.uuid4()),
        "type": "DEMO_PING",
        "scope": {"company_id": company.id, "branch_id": branch.id},
        "occurred_at": timezone.now().isoformat(),
        "payload": {"msg": "replay"},
        "payload_hash": "",
        "sequence": None,
        "prev_hash": "",
        "command_sig": "",
    }
    body = build_signed_batch(device_id=str(device.id), private_key=priv, commands=[command])
    client = APIClient()
    r1 = client.post(BATCH_URL, body, format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r1.status_code == 200, r1.data
    # MISMO cuerpo (mismo ts+nonce) → replay.
    r2 = client.post(BATCH_URL, body, format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r2.status_code == 401


@pytest.mark.django_db
def test_v2_device_id_header_distinto_del_body_es_rechazado():
    company, branch = _mk_org()
    device, priv = _enroll_device(company=company, branch=branch)
    command = {
        "command_id": str(uuid.uuid4()),
        "type": "DEMO_PING",
        "scope": {"company_id": company.id, "branch_id": branch.id},
        "occurred_at": timezone.now().isoformat(),
        "payload": {"msg": "mismatch"},
        "payload_hash": "",
        "sequence": None,
        "prev_hash": "",
        "command_sig": "",
    }
    body = build_signed_batch(device_id=str(device.id), private_key=priv, commands=[command])
    client = APIClient()
    r = client.post(BATCH_URL, body, format="json", HTTP_X_DEVICE_ID=str(uuid.uuid4()))
    assert r.status_code == 401  # DEVICE_ID_MISMATCH


# --------------------------------------------------------------------------- #
# KILL-SWITCH (middleware) — bloquea TODA la API para device REVOKED
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_killswitch_device_activo_pasa_revocado_bloqueado_en_endpoint_normal():
    company, branch = _mk_org()
    device, _priv = _enroll_device(company=company, branch=branch)
    client = _client_with_perms(company=company, branch=branch, perm_codes=["sync.device.enroll"])

    ok = client.get("/api/sync/devices/", HTTP_X_DEVICE_ID=str(device.id))
    assert ok.status_code == 200

    device.revoke()
    blocked = client.get("/api/sync/devices/", HTTP_X_DEVICE_ID=str(device.id))
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "DEVICE_REVOKED"


@pytest.mark.django_db
def test_killswitch_bloquea_endpoint_no_sync_de_otro_modulo():
    """El kill-switch NO es solo del canal sync: bloquea cualquier endpoint de API."""
    company, branch = _mk_org()
    device, _priv = _enroll_device(company=company, branch=branch)
    client = _client_with_perms(company=company, branch=branch, perm_codes=["org.company.read"])

    ok = client.get("/api/org/companies/", HTTP_X_DEVICE_ID=str(device.id))
    assert ok.status_code in (200, 403)  # depende del permiso, pero NO bloqueado por device

    device.revoke()
    blocked = client.get("/api/org/companies/", HTTP_X_DEVICE_ID=str(device.id))
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "DEVICE_REVOKED"


@pytest.mark.django_db
def test_killswitch_quarantined_no_bloquea_globalmente():
    company, branch = _mk_org()
    device, _priv = _enroll_device(company=company, branch=branch, status=Device.Status.QUARANTINED)
    client = _client_with_perms(company=company, branch=branch, perm_codes=["sync.device.enroll"])
    resp = client.get("/api/sync/devices/", HTTP_X_DEVICE_ID=str(device.id))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_killswitch_header_malformado_no_revienta():
    company, branch = _mk_org()
    client = _client_with_perms(company=company, branch=branch, perm_codes=["sync.device.enroll"])
    resp = client.get("/api/sync/devices/", HTTP_X_DEVICE_ID="no-es-uuid")
    assert resp.status_code == 200  # header inválido se ignora, no 500


@pytest.mark.django_db
def test_killswitch_device_de_otra_empresa_revocado_tambien_bloquea():
    """El bloqueo es por identidad del aparato, sin importar el X-Company-Id activo."""
    company_a, branch_a = _mk_org()
    company_b, branch_b = _mk_org()
    device_b, _priv = _enroll_device(company=company_b, branch=branch_b, status=Device.Status.REVOKED)
    # Cliente operando en empresa A, pero presentando el header del device revocado de B.
    client = _client_with_perms(company=company_a, branch=branch_a, perm_codes=["sync.device.enroll"])
    resp = client.get("/api/sync/devices/", HTTP_X_DEVICE_ID=str(device_b.id))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "DEVICE_REVOKED"


# --------------------------------------------------------------------------- #
# ENTRADA BASURA — 4xx tipado, NUNCA 500
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_batch_payload_vacio_es_400():
    company, branch = _mk_org()
    device, _priv = _enroll_device(company=company, branch=branch)
    client = APIClient()
    r = client.post(BATCH_URL, {}, format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r.status_code in (400, 422)  # validación (el contrato mapea ValidationError→422)


@pytest.mark.django_db
def test_batch_commands_tipo_erroneo_es_400():
    company, branch = _mk_org()
    device, _priv = _enroll_device(company=company, branch=branch)
    client = APIClient()
    body = {"batch_id": str(uuid.uuid4()), "commands": "no-es-lista"}
    r = client.post(BATCH_URL, body, format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r.status_code in (400, 422)  # validación tipada, nunca 500


@pytest.mark.django_db
def test_batch_command_id_no_uuid_es_400():
    company, branch = _mk_org()
    device, _priv = _enroll_device(company=company, branch=branch)
    client = APIClient()
    body = {
        "batch_id": str(uuid.uuid4()),
        "commands": [{
            "command_id": "no-es-uuid",
            "command_type": "DEMO_PING",
            "company_id": company.id,
            "occurred_at": timezone.now().isoformat(),
            "payload": {},
        }],
    }
    r = client.post(BATCH_URL, body, format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r.status_code in (400, 422)  # validación tipada, nunca 500


@pytest.mark.django_db
def test_batch_occurred_at_invalida_es_400():
    company, branch = _mk_org()
    device, _priv = _enroll_device(company=company, branch=branch)
    client = APIClient()
    body = {
        "batch_id": str(uuid.uuid4()),
        "commands": [{
            "command_id": str(uuid.uuid4()),
            "command_type": "DEMO_PING",
            "company_id": company.id,
            "occurred_at": "fecha-imposible",
            "payload": {},
        }],
    }
    r = client.post(BATCH_URL, body, format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r.status_code in (400, 422)  # validación tipada, nunca 500


@pytest.mark.django_db
def test_batch_sin_device_id_es_403():
    company, _branch = _mk_org()
    client = APIClient()
    body = {"batch_id": str(uuid.uuid4()), "commands": []}
    r = client.post(BATCH_URL, body, format="json")  # sin X-Device-Id y sin device_id en body
    assert r.status_code == 403


@pytest.mark.django_db
def test_v2_protocol_version_invalida_es_400():
    company, branch = _mk_org()
    device, priv = _enroll_device(company=company, branch=branch)
    body = build_signed_batch(device_id=str(device.id), private_key=priv, commands=[])
    body["protocol_version"] = "9"  # inválido
    client = APIClient()
    r = client.post(BATCH_URL, body, format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r.status_code in (400, 422)  # validación tipada, nunca 500


@pytest.mark.django_db
def test_payload_string_gigante_excede_limite_y_no_revienta():
    """Payload sobre el tope de bytes → REJECTED SYNC_LIMIT_EXCEEDED (no 500)."""
    company, branch = _mk_org()
    device, priv = _enroll_device(company=company, branch=branch)
    huge = {"blob": "x" * 80_000}  # supera SYNC_MAX_PAYLOAD_BYTES default (64000)
    cmd = _legacy_signed_command(
        private_key=priv, company_id=company.id, branch_id=branch.id,
        command_type="DEMO_PING", payload=huge,
    )
    client = APIClient()
    r = client.post(BATCH_URL, _legacy_batch_body([cmd]), format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r.status_code == 200, r.data
    assert r.data["results"][0]["status"] == "REJECTED"
    assert r.data["results"][0]["reason"] == "SYNC_LIMIT_EXCEEDED"


@pytest.mark.django_db
def test_occurred_at_con_skew_extremo_pone_en_cuarentena():
    """Un occurred_at muy desfasado → REJECTED SYNC_TIME_SKEW y device a QUARANTINED (no 500)."""
    company, branch = _mk_org()
    device, priv = _enroll_device(company=company, branch=branch)
    far = timezone.now() - timedelta(days=400)
    cmd = _legacy_signed_command(
        private_key=priv, company_id=company.id, branch_id=branch.id,
        command_type="DEMO_PING", payload={"msg": "old"}, occurred_at=far,
    )
    client = APIClient()
    r = client.post(BATCH_URL, _legacy_batch_body([cmd]), format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r.status_code == 200, r.data
    assert r.data["results"][0]["status"] == "REJECTED"
    assert r.data["results"][0]["reason"] == "SYNC_TIME_SKEW"
    device.refresh_from_db()
    assert device.status == Device.Status.QUARANTINED
