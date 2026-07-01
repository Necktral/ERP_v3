"""Tests de cobranza (dunning) — Ola D: mesa por cliente, niveles 1→3 y recordatorios.

El nivel base sale de los días de mora (≥60→3, ≥30→2, resto→1) y nunca retrocede
respecto del último recordatorio emitido (last+1, tope 3). El recordatorio congela
en receivables_json los documentos vencidos cubiertos.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.kernels.portfolio.collections import (
    collections_workbench,
    create_collection_reminder,
    list_collection_reminders,
)
from apps.kernels.portfolio.models import CollectionReminder
from apps.kernels.portfolio.services import PortfolioDomainError, create_receivable
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.parties.models import Party
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

User = get_user_model()


def _scope():
    t = uuid.uuid4().hex[:8]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H{t}", code=f"H-{t}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, parent=holding, name=f"C{t}", code=f"C-{t}")
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, parent=company, name=f"B{t}", code=f"B-{t}")
    return company, branch


def _actor():
    t = uuid.uuid4().hex[:8]
    return User.objects.create_user(username=f"u_{t}", email=f"u_{t}@t.local", password="x")


def _party(company, name="Cliente Moroso"):
    return Party.objects.create(
        company=company, party_type=Party.PartyType.NATURAL,
        display_name=f"{name} {uuid.uuid4().hex[:4]}",
    )


def _overdue(company, branch, party, *, days, amount="100.00", currency="NIO"):
    today = timezone.localdate()
    return create_receivable(
        company=company, branch=branch, party=party,
        reference_type="BILLING_DOC", reference_id=int(uuid.uuid4().int % 1_000_000),
        principal_amount=Decimal(amount), currency=currency,
        issue_date=today - timedelta(days=days + 30), due_date=today - timedelta(days=days),
        invoice_number=f"F-{uuid.uuid4().hex[:5]}",
    )


@pytest.mark.django_db
def test_workbench_groups_by_party_and_levels():
    company, branch = _scope()
    p1 = _party(company, "Leve")        # 10 días → nivel 1
    p2 = _party(company, "Media")       # 45 días → nivel 2
    p3 = _party(company, "Crónica")     # 90 días → nivel 3
    _overdue(company, branch, p1, days=10, amount="100.00")
    _overdue(company, branch, p1, days=5, amount="50.00")
    _overdue(company, branch, p2, days=45, amount="200.00")
    _overdue(company, branch, p3, days=90, amount="300.00")
    # No vencida: NO aparece.
    create_receivable(
        company=company, branch=branch, party=p1,
        reference_type="BILLING_DOC", reference_id=999_999,
        principal_amount=Decimal("999.00"), currency="NIO",
        issue_date=timezone.localdate(), due_date=timezone.localdate() + timedelta(days=30),
    )

    rows = {r["party_id"]: r for r in collections_workbench(company=company)}
    assert set(rows) == {p1.id, p2.id, p3.id}
    assert rows[p1.id]["docs"] == 2
    assert rows[p1.id]["total_outstanding"] == "150.00"
    assert rows[p1.id]["max_days_overdue"] == 10
    assert rows[p1.id]["suggested_level"] == 1
    assert rows[p2.id]["suggested_level"] == 2
    assert rows[p3.id]["suggested_level"] == 3
    assert rows[p1.id]["last_reminder"] is None
    assert rows[p1.id]["cooldown_active"] is False


@pytest.mark.django_db
def test_workbench_separates_currencies():
    company, branch = _scope()
    party = _party(company)
    _overdue(company, branch, party, days=10, amount="100.00", currency="NIO")
    _overdue(company, branch, party, days=10, amount="40.00", currency="USD")
    rows = collections_workbench(company=company)
    assert len(rows) == 2
    assert {r["currency"] for r in rows} == {"NIO", "USD"}


@pytest.mark.django_db
def test_reminder_snapshot_and_escalation_never_drops():
    company, branch = _scope()
    actor = _actor()
    party = _party(company)
    _overdue(company, branch, party, days=40, amount="200.00")
    _overdue(company, branch, party, days=12, amount="100.00")

    first = create_collection_reminder(
        company=company, branch=branch, actor=actor, party_id=party.id,
    )
    # Nivel sugerido por mora máxima (40 días → 2); snapshot con los 2 documentos.
    assert first["level"] == 2
    assert first["total_outstanding"] == "300.00"
    assert len(first["receivables"]) == 2
    days = sorted(line["days_overdue"] for line in first["receivables"])
    assert days == [12, 40]

    # El siguiente nunca baja: base seguiría 2, pero last+1 → 3 (tope 3).
    second = create_collection_reminder(
        company=company, branch=branch, actor=actor, party_id=party.id,
    )
    assert second["level"] == 3
    third = create_collection_reminder(
        company=company, branch=branch, actor=actor, party_id=party.id,
    )
    assert third["level"] == 3

    rows = collections_workbench(company=company)
    assert rows[0]["last_reminder"]["level"] == 3
    assert rows[0]["cooldown_active"] is True

    history = list_collection_reminders(company=company, party_id=party.id)
    assert [r["level"] for r in history] == [3, 3, 2]


@pytest.mark.django_db
def test_reminder_without_overdue_rejected():
    company, branch = _scope()
    actor = _actor()
    party = _party(company)
    with pytest.raises(PortfolioDomainError) as exc:
        create_collection_reminder(company=company, branch=branch, actor=actor, party_id=party.id)
    assert exc.value.code == "PORTFOLIO_NO_OVERDUE_RECEIVABLES"


@pytest.mark.django_db
def test_reminder_scoped_by_company():
    company, branch = _scope()
    other_company, other_branch = _scope()
    actor = _actor()
    party = _party(other_company)
    _overdue(other_company, other_branch, party, days=20)
    # El vencido vive en OTRA empresa: desde esta no hay nada que recordar.
    with pytest.raises(PortfolioDomainError):
        create_collection_reminder(company=company, branch=branch, actor=actor, party_id=party.id)
    assert CollectionReminder.objects.filter(company=company).count() == 0


def _client(*, company, branch, perms):
    u = User.objects.create_user(
        username=f"u_{uuid.uuid4().hex[:8]}", email=f"e_{uuid.uuid4().hex[:8]}@t.com", password="x"
    )
    UserMembership.objects.create(user=u, org_unit=company, is_active=True)
    UserMembership.objects.create(user=u, org_unit=branch, is_active=True)
    role = Role.objects.create(name=f"r_{uuid.uuid4().hex[:8]}", is_active=True)
    for p in perms:
        perm, _ = Permission.objects.get_or_create(code=p, defaults={"description": p, "is_active": True})
        RolePermission.objects.get_or_create(role=role, permission=perm)
    RoleAssignment.objects.create(user=u, role=role, org_unit=company, is_active=True)
    RoleAssignment.objects.create(user=u, role=role, org_unit=branch, is_active=True)
    c = APIClient()
    login = c.post("/api/auth/login/", {"username": u.username, "password": "x"}, format="json")
    assert login.status_code == 200, login.data
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    c.defaults["HTTP_X_COMPANY_ID"] = str(company.id)
    c.defaults["HTTP_X_BRANCH_ID"] = str(branch.id)
    return c


@pytest.mark.django_db
def test_api_rbac_and_flow():
    company, branch = _scope()
    party = _party(company)
    _overdue(company, branch, party, days=35, amount="500.00")

    nada = _client(company=company, branch=branch, perms=())
    assert nada.get("/api/portfolio/collections/workbench/").status_code == 403

    lector = _client(company=company, branch=branch, perms=("portfolio.collections.read",))
    r = lector.get("/api/portfolio/collections/workbench/")
    assert r.status_code == 200 and r.data["results"][0]["suggested_level"] == 2
    # read no alcanza para generar recordatorios.
    assert lector.post(
        "/api/portfolio/collections/reminders/", {"party_id": party.id}, format="json"
    ).status_code == 403

    gestor = _client(
        company=company, branch=branch,
        perms=("portfolio.collections.read", "portfolio.collections.remind"),
    )
    r = gestor.post("/api/portfolio/collections/reminders/", {"party_id": party.id}, format="json")
    assert r.status_code == 201, r.data
    assert r.data["level"] == 2 and r.data["total_outstanding"] == "500.00"

    r = gestor.get(f"/api/portfolio/collections/reminders/?party_id={party.id}")
    assert r.status_code == 200 and len(r.data["results"]) == 1
