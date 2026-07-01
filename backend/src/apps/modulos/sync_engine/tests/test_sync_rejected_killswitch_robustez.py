"""Robustez del riel de SUBIDA firmado (`POST /api/sync/batch/`).

Cubre dos invariantes pedidos por el catálogo de ataque offline-sync:

1. **REJECTED no es reintentable** (BUG-SYNC-1, fix c660c7e1): un comando que el
   central RECHAZA por negocio/contrato queda persistido como `AppliedCommand`
   REJECTED; reenviarlo (mismo command_id + mismo payload) devuelve DUPLICATE
   ESTABLE, NO lo re-procesa ni cambia su efecto. Esto blinda la regla
   "padre-antes-de-hijo": si el hijo se rechazó, re-pushearlo no lo aplica solo.

2. **Kill-switch** (`DeviceRevocationGuardMiddleware`): un lote firmado por un
   Device REVOKED queda bloqueado con 403 DEVICE_REVOKED antes de tocar la
   lógica de sync — el aparato revocado no puede empujar nada.

Reusa los helpers de `test_sync_push_loop.py`.
"""
from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.kernels.nomina.models import PayrollPayment
from apps.modulos.common.sync_replication import publish_syncable_event
from apps.modulos.sync_engine.models import AppliedCommand, Device
from apps.modulos.sync_engine.node_signing import build_replication_command, build_signed_batch

from .test_sync_push_loop import (
    BATCH_URL,
    _enroll_node,
    _entry_and_payment,
    _pending,
    _scope,
)


@pytest.mark.django_db
def test_comando_rejected_repush_es_duplicate_estable(settings):
    """BUG-SYNC-1 (regresión): un comando REJECTED no es reintentable.

    El PAGO (hijo) se publica SIN su ENTRY (padre) → el central lo rechaza con
    SYNC_REF_UNRESOLVED y deja una fila AppliedCommand REJECTED. Reenviar el
    MISMO lote (mismo command_id + payload) debe responder DUPLICATE (no REJECTED
    de nuevo, no APPLIED), sin crear el PayrollPayment ni mutar la fila.
    """
    settings.SYNC_NODE_CODE = "FINCA-A"
    company, branch = _scope()
    entry, payment = _entry_and_payment(company, branch)
    payment_uid = payment.sync_uid
    device, priv = _enroll_node(company)

    # Sólo el pago (hijo) — su FK al entry NO se podrá resolver en el central.
    publish_syncable_event(payment, company=company)
    payment.delete()
    entry.delete()

    commands = [build_replication_command(ev) for ev in _pending()]
    client = APIClient()

    r1 = client.post(
        BATCH_URL,
        build_signed_batch(device_id=str(device.id), private_key=priv, commands=commands),
        format="json", HTTP_X_DEVICE_ID=str(device.id),
    )
    assert r1.status_code == 200, r1.data
    assert r1.data["summary"]["rejected"] == 1
    assert r1.data["results"][0]["reason"] == "SYNC_REF_UNRESOLVED"

    rejected_rows = AppliedCommand.objects.filter(
        result_status=AppliedCommand.ResultStatus.REJECTED
    ).count()
    assert rejected_rows == 1, "el rechazo debe persistir exactamente una fila REJECTED"

    # Re-push idéntico → DUPLICATE estable, jamás re-procesar ni aplicar.
    r2 = client.post(
        BATCH_URL,
        build_signed_batch(device_id=str(device.id), private_key=priv, commands=commands),
        format="json", HTTP_X_DEVICE_ID=str(device.id),
    )
    assert r2.status_code == 200, r2.data
    assert r2.data["summary"]["duplicate"] == 1, r2.data
    assert r2.data["summary"]["applied"] == 0, r2.data
    assert r2.data["summary"]["rejected"] == 0, r2.data
    assert r2.data["results"][0]["status"] == "DUPLICATE"

    # El efecto NO ocurrió: el pago hijo nunca se creó; la fila REJECTED no se duplicó.
    assert not PayrollPayment.objects.filter(sync_uid=payment_uid).exists()
    assert AppliedCommand.objects.count() == 1


@pytest.mark.django_db
def test_device_revoked_no_aplica_nada_por_el_batch(settings):
    """KILL-SWITCH (defensa en profundidad): un lote firmado por un Device REVOKED
    no debe aplicar NADA.

    Nota de diseño verificada en device_guard.py:17-23: `/api/sync/batch/` está
    INTENCIONALMENTE exento del DeviceRevocationGuardMiddleware ("el propio motor de
    sync ya valida el estado del device"). En vez de un 403 opaco, el motor de sync
    (services.py:293) rechaza CADA comando con reason SYNC_DEVICE_REVOKED y applied=0.
    El efecto neto es el mismo que un kill-switch: el aparato revocado no escribe nada.
    """
    settings.SYNC_NODE_CODE = "FINCA-A"
    company, branch = _scope()
    entry, payment = _entry_and_payment(company, branch)
    payment_uid = payment.sync_uid
    device, priv = _enroll_node(company)

    publish_syncable_event(entry, company=company)
    publish_syncable_event(payment, company=company)
    payment.delete()
    entry.delete()
    commands = [build_replication_command(ev) for ev in _pending()]

    # Revocar el aparato firmante.
    device.status = Device.Status.REVOKED
    device.save(update_fields=["status"])

    resp = APIClient().post(
        BATCH_URL,
        build_signed_batch(device_id=str(device.id), private_key=priv, commands=commands),
        format="json", HTTP_X_DEVICE_ID=str(device.id),
    )
    assert resp.status_code == 200, resp.content
    assert resp.data["summary"]["applied"] == 0, resp.data
    assert resp.data["summary"]["rejected"] == 2, resp.data
    for r in resp.data["results"]:
        assert r["status"] == "REJECTED"
        assert r["reason"] == "SYNC_DEVICE_REVOKED", r
    # Invariante kill-switch: ningún dato del aparato revocado tocó la BD.
    assert not PayrollPayment.objects.filter(sync_uid=payment_uid).exists()
    assert AppliedCommand.objects.count() == 0


@pytest.mark.django_db
def test_killswitch_no_bloquea_batch_de_device_active(settings):
    """POSITIVO: un Device ACTIVE empuja normalmente (el kill-switch no es un
    falso positivo)."""
    settings.SYNC_NODE_CODE = "FINCA-A"
    company, branch = _scope()
    entry, payment = _entry_and_payment(company, branch)
    device, priv = _enroll_node(company)

    publish_syncable_event(entry, company=company)
    publish_syncable_event(payment, company=company)
    payment.delete()
    entry.delete()
    commands = [build_replication_command(ev) for ev in _pending()]

    resp = APIClient().post(
        BATCH_URL,
        build_signed_batch(device_id=str(device.id), private_key=priv, commands=commands),
        format="json", HTTP_X_DEVICE_ID=str(device.id),
    )
    assert resp.status_code == 200, resp.content
    assert resp.data["summary"]["applied"] == 2
