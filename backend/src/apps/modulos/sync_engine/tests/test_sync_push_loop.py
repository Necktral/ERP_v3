"""F1 E2E — lazo de SUBIDA por el RIEL firmado real (`POST /api/sync/batch/`, v2 Ed25519).

A diferencia de `common/tests/test_sync_replication.py` (que aplica con el central SIMULADO en
proceso), aquí el nodo **firma el lote** y lo manda por el `/api/sync/batch/` REAL: verificación de
firma + `process_batch` + handler `sync.replicate.v1` + `_apply_payload` (traducción de FKs por
`SyncIdentity`). El central se simula en la misma DB "vaciando" las filas de origen antes de empujar.
"""
from __future__ import annotations

import base64
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.kernels.nomina.models import (
    PayrollEntry,
    PayrollPayment,
    PayrollPeriod,
    PayrollSheet,
    PeriodStatus,
    PeriodType,
    SalaryType,
)
from apps.kernels.nomina.services import compute_entry, create_default_nicaragua_config
from apps.modulos.common.models import SyncIdentity
from apps.modulos.common.sync_replication import SYNC_SOURCE_MODULE, publish_syncable_event
from apps.modulos.hr.models import Employee
from apps.modulos.iam.models import OrgUnit
from apps.modulos.integration.models import OutboxEvent
from apps.modulos.sync_engine.models import Device
from apps.modulos.sync_engine.node_signing import (
    build_replication_command,
    build_signed_batch,
    generate_keypair,
    load_private_key,
)

User = get_user_model()
BATCH_URL = "/api/sync/batch/"


def _scope():
    t = uuid.uuid4().hex[:8]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H{t}", code=f"H-{t}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, parent=holding, name=f"C{t}", code=f"C-{t}")
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, parent=company, name=f"B{t}", code=f"B-{t}")
    return company, branch


def _entry_and_payment(company, branch):
    actor = User.objects.create_user(
        username=f"u_{uuid.uuid4().hex[:8]}", email=f"e_{uuid.uuid4().hex[:8]}@t.com", password="x"
    )
    req = SimpleNamespace(user=actor, META={}, company=company, branch=None, _request=None,
                          ctx=None, request_id="", path="", method="POST")
    create_default_nicaragua_config(request=req, actor=actor, company=company, fiscal_year=2026)
    period = PayrollPeriod.objects.create(
        company=company, year=2026, month=6, period_type=PeriodType.SECOND_HALF,
        start_date=date(2026, 6, 16), end_date=date(2026, 6, 30), working_days=15,
        status=PeriodStatus.APPROVED,
    )
    sheet = PayrollSheet.objects.create(period=period, branch=branch, sheet_name="FINCA", has_inss=True)
    emp = Employee.objects.create(company=company, employee_code="E-1", first_name="Ana", last_name="Lopez", is_active=True)
    entry = PayrollEntry.objects.create(
        sheet=sheet, employee=emp, full_name="Ana Lopez", has_inss=True,
        salary_type=SalaryType.MONTHLY, base_salary_nio=Decimal("12000.00"),
        days_in_period=15, days_worked=Decimal("15.00"),
    )
    compute_entry(entry=entry)
    payment = PayrollPayment.objects.create(
        entry=entry, company=company, payment_method="CASH",
        amount=Decimal("100.00"), payment_date=date(2026, 6, 30),
    )
    return entry, payment


def _enroll_node(company, branch=None):
    """Crea el Device firmante del nodo (a nivel empresa) con un par Ed25519 conocido."""
    priv_b64, pub_b64 = generate_keypair()
    device = Device.objects.create(
        company=company, branch=branch, label="node-A",
        public_key=base64.b64decode(pub_b64.encode("utf-8"), validate=True),
        status=Device.Status.ACTIVE,
    )
    return device, load_private_key(priv_b64)


def _pending():
    return list(
        OutboxEvent.objects.filter(status=OutboxEvent.Status.PENDING, source_module=SYNC_SOURCE_MODULE)
        .order_by("occurred_at", "id")
    )


@pytest.mark.django_db
def test_lazo_de_subida_aplica_por_el_riel_firmado(settings):
    settings.SYNC_NODE_CODE = "FINCA-A"
    company, branch = _scope()
    entry, payment = _entry_and_payment(company, branch)
    entry_uid, payment_uid = entry.sync_uid, payment.sync_uid
    device, priv = _enroll_node(company)

    publish_syncable_event(entry, company=company)
    publish_syncable_event(payment, company=company)
    # El central (misma DB) aún no tiene estas filas:
    payment.delete()
    entry.delete()

    commands = [build_replication_command(ev) for ev in _pending()]  # FIFO: entry, luego payment
    body = build_signed_batch(device_id=str(device.id), private_key=priv, commands=commands)

    resp = APIClient().post(BATCH_URL, body, format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert resp.status_code == 200, resp.data
    assert resp.data["summary"]["applied"] == 2
    assert {r["status"] for r in resp.data["results"]} == {"APPLIED"}

    central_entry = PayrollEntry.objects.get(sync_uid=entry_uid)
    central_payment = PayrollPayment.objects.get(sync_uid=payment_uid)
    assert central_payment.entry_id == central_entry.pk  # FK traducida por SyncIdentity
    assert central_payment.amount == Decimal("100.00")
    assert central_payment.origin_node == "FINCA-A"
    assert SyncIdentity.objects.filter(model_label="nomina.payrollentry", sync_uid=entry_uid).exists()
    assert SyncIdentity.objects.filter(model_label="nomina.payrollpayment", sync_uid=payment_uid).exists()


@pytest.mark.django_db
def test_reenvio_del_mismo_lote_es_duplicate_y_no_duplica(settings):
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
    client = APIClient()

    r1 = client.post(BATCH_URL, build_signed_batch(device_id=str(device.id), private_key=priv, commands=commands),
                     format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r1.status_code == 200 and r1.data["summary"]["applied"] == 2

    # Mismo command_id + mismo payload → DUPLICATE (no re-crea). Re-firmamos el request (ts/nonce nuevos).
    r2 = client.post(BATCH_URL, build_signed_batch(device_id=str(device.id), private_key=priv, commands=commands),
                     format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert r2.status_code == 200
    assert r2.data["summary"]["duplicate"] == 2
    assert r2.data["summary"]["applied"] == 0
    assert PayrollPayment.objects.filter(sync_uid=payment_uid).count() == 1


@pytest.mark.django_db
def test_firma_de_request_invalida_es_rechazada(settings):
    settings.SYNC_NODE_CODE = "FINCA-A"
    company, branch = _scope()
    entry, payment = _entry_and_payment(company, branch)
    entry_uid = entry.sync_uid
    device, priv = _enroll_node(company)
    publish_syncable_event(entry, company=company)
    payment.delete()
    entry.delete()

    commands = [build_replication_command(ev) for ev in _pending()]
    body = build_signed_batch(device_id=str(device.id), private_key=priv, commands=commands)
    body["auth"]["signature"] = base64.b64encode(b"\x00" * 64).decode()  # firma corrupta

    resp = APIClient().post(BATCH_URL, body, format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert resp.status_code == 401
    assert not PayrollEntry.objects.filter(sync_uid=entry_uid).exists()  # nada se aplicó


@pytest.mark.django_db
def test_hijo_sin_padre_es_rechazado_por_fk_no_resuelta(settings):
    settings.SYNC_NODE_CODE = "FINCA-A"
    company, branch = _scope()
    entry, payment = _entry_and_payment(company, branch)
    payment_uid = payment.sync_uid
    device, priv = _enroll_node(company)
    # Sólo se publica el PAGO (su FK refiere al entry por sync_uid), no el entry.
    publish_syncable_event(payment, company=company)
    payment.delete()
    entry.delete()

    commands = [build_replication_command(ev) for ev in _pending()]
    body = build_signed_batch(device_id=str(device.id), private_key=priv, commands=commands)

    resp = APIClient().post(BATCH_URL, body, format="json", HTTP_X_DEVICE_ID=str(device.id))
    assert resp.status_code == 200
    assert resp.data["summary"]["rejected"] == 1
    assert resp.data["results"][0]["reason"] == "SYNC_REF_UNRESOLVED"
    assert not PayrollPayment.objects.filter(sync_uid=payment_uid).exists()
