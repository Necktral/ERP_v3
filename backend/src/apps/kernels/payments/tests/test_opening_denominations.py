"""HUECO 2 (BUG-10) — desglose por denominación en la APERTURA (fondo).

Antes solo el cierre (arqueo) persistía el desglose por denominación; el fondo de
apertura entraba como un monto plano. El fix (services.py ~491-500) hace que, si se
da `denominations` al abrir, se persistan con `stage=OPENING` y su suma pase a ser el
fondo autoritativo (opening_amount/expected_amount). Apertura y cierre coexisten en la
misma sesión (constraint único por session+stage+value), y el endpoint los expone por
separado con su subtotal.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.kernels.payments.models import CashDenomination
from apps.kernels.payments.services import (
    open_cash_session_for_scope,
    submit_denomination_count,
)
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

User = get_user_model()
UT = OrgUnit.UnitType


def _scope():
    s = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=UT.HOLDING, name=f"H{s}")
    company = OrgUnit.objects.create(unit_type=UT.COMPANY, name=f"C{s}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=UT.BRANCH, name=f"B{s}", parent=company)
    return company, branch


def _actor():
    name = f"actor_{uuid.uuid4().hex[:8]}"
    return User.objects.create_user(username=name, email=f"{name}@test.com", password="x")


def _client(company, branch, perms):
    username = f"u_{uuid.uuid4().hex[:10]}"
    user = User.objects.create_user(username=username, email=f"{username}@t.local", password="x")
    UserMembership.objects.create(user=user, org_unit=company, is_active=True)
    UserMembership.objects.create(user=user, org_unit=branch, is_active=True)

    role = Role.objects.create(name=f"r_{uuid.uuid4().hex[:8]}", is_active=True)
    for p in perms:
        perm, _ = Permission.objects.get_or_create(code=p, defaults={"description": p, "is_active": True})
        RolePermission.objects.get_or_create(role=role, permission=perm)
    RoleAssignment.objects.create(user=user, role=role, org_unit=company, is_active=True)
    RoleAssignment.objects.create(user=user, role=role, org_unit=branch, is_active=True)

    c = APIClient()
    login = c.post("/api/auth/login/", {"username": username, "password": "x"}, format="json")
    assert login.status_code == 200
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    c.defaults["HTTP_X_COMPANY_ID"] = str(company.id)
    c.defaults["HTTP_X_BRANCH_ID"] = str(branch.id)
    return c, user


# ---------------------------------------------------------------------------
# Servicio
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_opening_denominations_persist_as_stage_opening_and_drive_fund():
    """El desglose de apertura se guarda con stage=OPENING y su suma fija el fondo."""
    company, branch = _scope()
    actor = _actor()
    # 5×100 + 10×20 = 700 — y NO el opening_amount plano (que se ignora si hay desglose).
    session = open_cash_session_for_scope(
        company=company, branch=branch, actor=actor, register_id="R-OPEN",
        opening_amount=Decimal("999.00"),
        denominations=[
            {"denomination_value": "100.00", "quantity": 5, "denomination_type": "BILL"},
            {"denomination_value": "20.00", "quantity": 10, "denomination_type": "BILL"},
        ],
    )

    rows = CashDenomination.objects.filter(session=session, stage=CashDenomination.Stage.OPENING)
    assert rows.count() == 2
    assert all(r.stage == CashDenomination.Stage.OPENING for r in rows)
    # subtotal se calcula solo (value × qty) en .save().
    by_value = {r.denomination_value: r.subtotal for r in rows}
    assert by_value[Decimal("100.00")] == Decimal("500.00")
    assert by_value[Decimal("20.00")] == Decimal("200.00")

    session.refresh_from_db()
    assert session.opening_amount == Decimal("700.00")
    assert session.expected_amount == Decimal("700.00")


@pytest.mark.django_db
def test_opening_without_denominations_keeps_plain_amount():
    """Sin desglose, el fondo plano se respeta y no se crea ninguna fila OPENING."""
    company, branch = _scope()
    actor = _actor()
    session = open_cash_session_for_scope(
        company=company, branch=branch, actor=actor, register_id="R-PLAIN",
        opening_amount=Decimal("250.00"),
    )
    session.refresh_from_db()
    assert session.opening_amount == Decimal("250.00")
    assert not CashDenomination.objects.filter(
        session=session, stage=CashDenomination.Stage.OPENING
    ).exists()


@pytest.mark.django_db
def test_opening_and_closing_denominations_coexist_independently():
    """Apertura y cierre conviven: distinto stage, mismo value sin colisión de constraint."""
    company, branch = _scope()
    actor = _actor()
    fake_request = type("R", (), {"company": company, "branch": branch})()

    session = open_cash_session_for_scope(
        company=company, branch=branch, actor=actor, register_id="R-BOTH",
        denominations=[
            {"denomination_value": "100.00", "quantity": 2, "denomination_type": "BILL"},
        ],
    )
    # Arqueo de cierre con la MISMA denominación 100 → stage CLOSING, no choca.
    submit_denomination_count(
        request=fake_request, actor=actor, session_id=session.id,
        denominations=[
            {"denomination_value": "100.00", "quantity": 7, "denomination_type": "BILL"},
        ],
    )

    opening = CashDenomination.objects.filter(session=session, stage=CashDenomination.Stage.OPENING)
    closing = CashDenomination.objects.filter(session=session, stage=CashDenomination.Stage.CLOSING)
    assert opening.count() == 1 and opening.first().quantity == 2
    assert closing.count() == 1 and closing.first().quantity == 7

    session.refresh_from_db()
    assert session.opening_amount == Decimal("200.00")   # 2×100
    assert session.counted_amount == Decimal("700.00")   # 7×100


# ---------------------------------------------------------------------------
# HTTP: el detalle expone opening_denominations / closing_denominations
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_session_detail_exposes_opening_and_closing_denominations():
    company, branch = _scope()
    c, actor = _client(company, branch, perms=["payments.cash_session.read"])
    session = open_cash_session_for_scope(
        company=company, branch=branch, actor=actor, register_id="R-HTTP",
        denominations=[
            {"denomination_value": "500.00", "quantity": 1, "denomination_type": "BILL"},
            {"denomination_value": "5.00", "quantity": 4, "denomination_type": "COIN"},
        ],
    )

    r = c.get(f"/api/payments/cash-sessions/{session.id}/")
    assert r.status_code == 200, r.data
    body = r.data

    assert len(body["opening_denominations"]) == 2
    assert body["closing_denominations"] == []
    assert body["opening_amount"] == "520.00"  # 500 + 4×5
    by_value = {d["denomination_value"]: d["subtotal"] for d in body["opening_denominations"]}
    assert by_value["500.00"] == "500.00"
    assert by_value["5.00"] == "20.00"
