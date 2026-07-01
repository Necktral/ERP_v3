"""Tests del módulo alertas: dedupe/reapertura, escáneres deterministas y notificación
solo-al-abrir. Patrón de la casa: _scope() + SimpleNamespace request, sin HTTP."""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.kernels.inventarios.models import InventoryItem, UoM
from apps.kernels.inventarios.services import create_warehouse, post_receive
from apps.kernels.portfolio.services import create_receivable
from apps.modulos.alertas import services as al
from apps.modulos.alertas.models import Alert, AlertSeverity, AlertStatus
from apps.modulos.alertas.services import AlertDraft
from apps.modulos.fleet.models import FleetAsset, FleetDocument
from apps.modulos.iam.models import OrgUnit
from apps.modulos.notifications.models import NotificationRecord
from apps.modulos.parties.models import Party
from apps.modulos.rbac.models import Role, RoleAssignment

User = get_user_model()
UT = OrgUnit.UnitType


def _scope():
    t = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=UT.HOLDING, name=f"H{t}", code=f"H-{t}")
    company = OrgUnit.objects.create(unit_type=UT.COMPANY, parent=holding, name=f"C{t}", code=f"C-{t}")
    branch = OrgUnit.objects.create(unit_type=UT.BRANCH, parent=company, name=f"B{t}", code=f"B-{t}")
    return holding, company, branch


def _user():
    t = uuid.uuid4().hex[:8]
    return User.objects.create_user(username=f"u_{t}", email=f"u_{t}@t.local", password="pass12345")


def _req(company, branch, user):
    return SimpleNamespace(
        company=company, branch=branch, user=user, META={}, headers={},
        path="/test/alertas/", method="POST", request_id=f"req-{uuid.uuid4().hex[:8]}",
    )


def _party(company, name="Cliente X"):
    return Party.objects.create(
        company=company, party_type=Party.PartyType.NATURAL, display_name=name,
    )


def _draft(subject_id="1", severity=AlertSeverity.WARNING, title="t"):
    return AlertDraft(subject_type="X", subject_id=subject_id, severity=severity, title=title)


# ===========================================================================
# Dedupe / reapertura / resolución por reconciliación
# ===========================================================================

@pytest.mark.django_db
def test_upsert_dedupe_reapertura_y_resolve():
    _h, company, _b = _scope()
    a1, opened1 = al.upsert_alert(company=company, alert_type="T1", draft=_draft(), notify=False)
    a2, opened2 = al.upsert_alert(company=company, alert_type="T1", draft=_draft(), notify=False)
    assert opened1 is True and opened2 is False
    assert a1.pk == a2.pk and Alert.objects.count() == 1

    # La condición desaparece → el sync la resuelve.
    out = al._sync_alert_type(company=company, alert_type="T1", drafts=[])
    assert out["resolved"] == 1
    a1.refresh_from_db()
    assert a1.status == AlertStatus.RESOLVED

    # Reaparece → se reabre (cuenta como abierta).
    _a3, opened3 = al.upsert_alert(company=company, alert_type="T1", draft=_draft(), notify=False)
    assert opened3 is True
    a1.refresh_from_db()
    assert a1.status == AlertStatus.OPEN


@pytest.mark.django_db
def test_ack_y_resolve_manual():
    _h, company, _b = _scope()
    actor = _user()
    alert, _ = al.upsert_alert(company=company, alert_type="T1", draft=_draft(), notify=False)
    al.acknowledge_alert(alert=alert, actor=actor)
    alert.refresh_from_db()
    assert alert.status == AlertStatus.ACKNOWLEDGED
    assert alert.acknowledged_by_id == actor.pk
    al.resolve_alert(alert=alert)
    alert.refresh_from_db()
    assert alert.status == AlertStatus.RESOLVED


# ===========================================================================
# Escáner: CxC vencidas y por vencer
# ===========================================================================

@pytest.mark.django_db
def test_scan_receivables_vencida_y_por_vencer():
    _h, company, _b = _scope()
    party = _party(company)
    today = timezone.localdate()
    create_receivable(
        company=company, party=party, reference_type="TEST", reference_id=1,
        principal_amount=Decimal("1000.00"), currency="NIO",
        issue_date=today - timedelta(days=40), due_date=today - timedelta(days=10),
    )
    create_receivable(
        company=company, party=party, reference_type="TEST", reference_id=2,
        principal_amount=Decimal("500.00"), currency="NIO",
        issue_date=today, due_date=today + timedelta(days=3),
    )
    out = al.scan_overdue_receivables(company)
    assert out["RECEIVABLE_OVERDUE"]["active"] == 1
    assert out["RECEIVABLE_DUE_SOON"]["active"] == 1
    vencida = Alert.objects.get(company=company, alert_type="RECEIVABLE_OVERDUE")
    assert vencida.severity == AlertSeverity.WARNING  # 10 días (≤30)
    assert "1000.00" in vencida.payload_json["outstanding"]


@pytest.mark.django_db
def test_scan_receivables_critica_a_30_dias_y_resuelve_pagada():
    _h, company, _b = _scope()
    party = _party(company)
    today = timezone.localdate()
    rx = create_receivable(
        company=company, party=party, reference_type="TEST", reference_id=3,
        principal_amount=Decimal("800.00"), currency="NIO",
        issue_date=today - timedelta(days=90), due_date=today - timedelta(days=45),
    )
    out = al.scan_overdue_receivables(company)
    assert out["RECEIVABLE_OVERDUE"]["active"] == 1
    assert Alert.objects.get(company=company, alert_type="RECEIVABLE_OVERDUE").severity == AlertSeverity.CRITICAL

    # Se paga (allocated = principal) → siguiente escaneo la resuelve.
    rx.allocated_amount = rx.principal_amount
    rx.save(update_fields=["allocated_amount"])
    out2 = al.scan_overdue_receivables(company)
    assert out2["RECEIVABLE_OVERDUE"]["active"] == 0
    assert out2["RECEIVABLE_OVERDUE"]["resolved"] == 1


# ===========================================================================
# Escáner: stock bajo mínimo / punto de reorden
# ===========================================================================

@pytest.mark.django_db
def test_scan_low_stock_warning_critical_y_resolucion():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh = create_warehouse(request=req, company=company, branch=branch, actor_user=actor, name="B", code="W1")
    item = InventoryItem.objects.create(
        company=company, sku=f"S{uuid.uuid4().hex[:6]}", name="Urea", uom=UoM.UNIT,
        reorder_point=Decimal("20"), min_stock_qty=Decimal("10"),
    )
    post_receive(request=req, actor=actor, warehouse_id=wh.id, item_id=item.id,
                 qty=Decimal("5"), unit_cost=Decimal("1"), idempotency_key=f"r-{uuid.uuid4().hex}")
    out = al.scan_low_stock(company)
    assert out["LOW_STOCK"]["active"] == 1
    alert = Alert.objects.get(company=company, alert_type="LOW_STOCK")
    assert alert.severity == AlertSeverity.CRITICAL  # 5 < min 10

    post_receive(request=req, actor=actor, warehouse_id=wh.id, item_id=item.id,
                 qty=Decimal("10"), unit_cost=Decimal("1"), idempotency_key=f"r-{uuid.uuid4().hex}")
    out2 = al.scan_low_stock(company)  # 15: sobre el mínimo, bajo reorden 20
    alert.refresh_from_db()
    assert alert.severity == AlertSeverity.WARNING and out2["LOW_STOCK"]["active"] == 1

    post_receive(request=req, actor=actor, warehouse_id=wh.id, item_id=item.id,
                 qty=Decimal("50"), unit_cost=Decimal("1"), idempotency_key=f"r-{uuid.uuid4().hex}")
    out3 = al.scan_low_stock(company)  # 65 ≥ 20 → se resuelve
    assert out3["LOW_STOCK"]["active"] == 0 and out3["LOW_STOCK"]["resolved"] == 1


# ===========================================================================
# Escáner: documentos de flota
# ===========================================================================

@pytest.mark.django_db
def test_scan_fleet_documents_vencido_y_por_vencer():
    _h, company, _b = _scope()
    today = timezone.localdate()
    asset = FleetAsset.objects.create(
        company=company, asset_type="VEHICLE", code="CAM-01", name="Camión 01",
    )
    FleetDocument.objects.create(
        company=company, asset=asset, doc_type="INSURANCE", number="POL-1",
        expiry_date=today - timedelta(days=2),
    )
    FleetDocument.objects.create(
        company=company, asset=asset, doc_type="CIRCULATION", number="CIR-9",
        expiry_date=today + timedelta(days=15),
    )
    out = al.scan_expiring_fleet_documents(company)
    assert out["FLEET_DOC_EXPIRING"]["active"] == 2
    sevs = set(Alert.objects.filter(company=company, alert_type="FLEET_DOC_EXPIRING")
               .values_list("severity", flat=True))
    assert sevs == {AlertSeverity.CRITICAL, AlertSeverity.WARNING}


# ===========================================================================
# Notificación: SOLO al abrir/reabrir, a los roles del tema
# ===========================================================================

@pytest.mark.django_db
def test_notifica_solo_al_abrir_no_en_cada_escaneo():
    _h, company, _b = _scope()
    user = _user()
    role, _ = Role.objects.get_or_create(name="company_admin")
    RoleAssignment.objects.create(user=user, role=role, org_unit=company, is_active=True)

    al.upsert_alert(company=company, alert_type="T9", draft=_draft(title="aviso"))
    assert NotificationRecord.objects.filter(company=company).count() == 1
    # Mismo sujeto, mismo día: refresca pero NO re-notifica.
    al.upsert_alert(company=company, alert_type="T9", draft=_draft(title="aviso"))
    assert NotificationRecord.objects.filter(company=company).count() == 1
