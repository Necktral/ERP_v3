"""Tests de F1 — lazo de subida de eventos operativos (replicación entre nodos).

Demuestra el ciclo completo con nómina (`PayrollPayment` → FK a `PayrollEntry`, ambos
`Syncable`): publicar el evento en un nodo y aplicarlo en el central de forma idempotente,
traduciendo la FK por el mapa `SyncIdentity`. El central se simula en la misma DB
"vaciando" las filas de origen antes de aplicar (representa un central que aún no las tiene).
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

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
from apps.modulos.common.sync_replication import (
    CENTRAL_CONSUMER,
    SYNC_EVENT_TYPE,
    apply_syncable_event,
    build_event_payload,
    publish_syncable_event,
)
from apps.modulos.hr.models import Employee
from apps.modulos.iam.models import OrgUnit
from apps.modulos.integration.models import InboxEvent

User = get_user_model()


def _scope():
    t = uuid.uuid4().hex[:8]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H{t}", code=f"H-{t}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, parent=holding, name=f"C{t}", code=f"C-{t}")
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, parent=company, name=f"B{t}", code=f"B-{t}")
    return company, branch


def _entry_and_payment(company, branch):
    actor = User.objects.create_user(username=f"u_{uuid.uuid4().hex[:8]}", email=f"e_{uuid.uuid4().hex[:8]}@t.com", password="x")
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


@pytest.mark.django_db
def test_build_event_payload_lleva_identidad_y_refs(settings):
    settings.SYNC_NODE_CODE = "FINCA-A"
    company, branch = _scope()
    entry, payment = _entry_and_payment(company, branch)

    payload = build_event_payload(payment)
    assert payload["model_label"] == "nomina.payrollpayment"
    assert payload["sync_uid"] == payment.sync_uid
    assert payload["origin_node"] == "FINCA-A"
    # Decimal serializado a str; FK a maestro (company) viaja por id.
    assert payload["fields"]["amount"] == "100.00"
    assert payload["fields"]["company_id"] == company.id
    # FK a otra fila Syncable (entry) viaja por sync_uid, NO por id local.
    assert payload["refs"]["entry_id"] == {
        "model_label": "nomina.payrollentry",
        "sync_uid": entry.sync_uid,
    }


@pytest.mark.django_db
def test_apply_traduce_fk_por_el_mapa_y_es_idempotente(settings):
    settings.SYNC_NODE_CODE = "FINCA-A"
    company, branch = _scope()
    entry, payment = _entry_and_payment(company, branch)

    entry_uid, payment_uid = entry.sync_uid, payment.sync_uid
    entry_event = publish_syncable_event(entry, company=company)
    payment_event = publish_syncable_event(payment, company=company)
    assert entry_event.event_type == SYNC_EVENT_TYPE

    # Simula un central que aún no tiene estas filas: se vacían las de origen.
    payment.delete()
    entry.delete()

    # 1) El central aplica el evento del entry → lo recrea con nuevo id local + mapea.
    central_entry, created_e = apply_syncable_event(entry_event)
    assert created_e is True
    assert central_entry.sync_uid == entry_uid
    assert central_entry.pk != 0

    # 2) Aplica el pago → traduce la FK entry por el sync_uid (id local NUEVO del central).
    central_payment, created_p = apply_syncable_event(payment_event)
    assert created_p is True
    assert central_payment.entry_id == central_entry.pk  # FK traducida por el mapa
    assert central_payment.sync_uid == payment_uid
    assert central_payment.amount == Decimal("100.00")
    assert central_payment.origin_node == "FINCA-A"

    # 3) Reaplicar el mismo evento NO duplica (idempotente por mapa + inbox).
    again, created_again = apply_syncable_event(payment_event)
    assert created_again is False
    assert again.pk == central_payment.pk
    assert PayrollPayment.objects.filter(sync_uid=payment_uid).count() == 1

    # El mapa de identidad y el inbox quedaron registrados.
    assert SyncIdentity.objects.filter(model_label="nomina.payrollpayment", sync_uid=payment_uid).count() == 1
    assert InboxEvent.objects.filter(event_id=payment_event.event_id, consumer=CENTRAL_CONSUMER,
                                     status=InboxEvent.Status.PROCESSED).exists()
