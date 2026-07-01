"""Lado NODO: firmar y empaquetar el lote de replicación para el riel `/api/sync/batch/` (v2).

El nodo es un firmante Ed25519 (reusa la identidad `Device`). Con el protocolo v2 la firma es a
nivel de REQUEST (un solo `auth.signature` sobre el cuerpo canónico con `auth.signature=""`), así
que los comandos no necesitan firma individual. Este módulo arma EXACTAMENTE el mensaje que valida
`SyncBatchView._validate_v2_request_auth` (mismo `canon_json` + `build_request_signing_message`).
"""
from __future__ import annotations

import base64
import time
import uuid
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.utils import timezone

from .signing import build_request_signing_message, canon_json

REPLICATION_COMMAND_TYPE = "sync.replicate.v1"


# --- llaves ---------------------------------------------------------------------
def generate_keypair() -> tuple[str, str]:
    """Genera un par Ed25519. Devuelve `(private_b64, public_b64)` (32 bytes crudos cada uno)."""
    priv = Ed25519PrivateKey.generate()
    priv_raw = priv.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    pub_raw = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return base64.b64encode(priv_raw).decode(), base64.b64encode(pub_raw).decode()


def load_private_key(private_b64: str) -> Ed25519PrivateKey:
    raw = base64.b64decode(private_b64.encode("utf-8"), validate=True)
    return Ed25519PrivateKey.from_private_bytes(raw)


def sign_message(private_key: Ed25519PrivateKey, message: bytes) -> str:
    return base64.b64encode(private_key.sign(message)).decode()


# --- empaquetado ----------------------------------------------------------------
def build_replication_command(outbox_event) -> dict[str, Any]:
    """Un `OutboxEvent` de `sync_replication` → comando v2 `sync.replicate.v1`.

    El scope (company/branch) sale del evento (debe coincidir con el del Device del nodo). El
    `occurred_at` se sella AHORA (la verdad de orden la da el central; sólo se controla el desfase).
    """
    env = outbox_event.payload or {}
    data = env.get("data") or {}
    scope = env.get("scope") or {}
    company_id = outbox_event.company_id or scope.get("company_id")
    branch_id = outbox_event.branch_id if outbox_event.branch_id is not None else scope.get("branch_id")
    return {
        "command_id": str(outbox_event.event_id),
        "type": REPLICATION_COMMAND_TYPE,
        "scope": {"company_id": company_id, "branch_id": branch_id},
        "occurred_at": timezone.now().isoformat(),
        "payload": {"data": data},
        "payload_hash": "",
        "sequence": None,
        "prev_hash": "",
        "command_sig": "",
    }


def build_signed_batch(
    *,
    device_id: str,
    private_key: Ed25519PrivateKey,
    commands: list[dict[str, Any]],
    ts: int | None = None,
    nonce: str | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    """Arma el cuerpo v2 firmado a nivel request, listo para `POST /api/sync/batch/`."""
    ts = int(ts if ts is not None else time.time())
    nonce = nonce or uuid.uuid4().hex
    body: dict[str, Any] = {
        "protocol_version": "2",
        "device_id": str(device_id),
        "ts": ts,
        "nonce": nonce,
        "auth": {"scheme": "ed25519", "signature": "", "key_id": ""},
        "batch_id": str(batch_id or uuid.uuid4()),
        "batch": commands,
    }
    # Firma sobre el cuerpo canónico con auth.signature="" (idéntico a lo que recalcula el central).
    signing_body = canon_json(body).encode("utf-8")
    message = build_request_signing_message(ts=ts, nonce=nonce, canonical_body_bytes=signing_body)
    body["auth"]["signature"] = sign_message(private_key, message)
    return body
