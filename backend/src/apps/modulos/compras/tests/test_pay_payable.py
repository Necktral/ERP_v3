"""Tests del pago de CxP a proveedores desde caja (Ola D).

El pago compone kernels existentes: intent CASHIER capturado → allocation en
cartera → egreso EXPENSE de la sesión de caja (solo efectivo). Reentrada con la
misma idempotency_key NO vuelve a aplicar (dinero que sale).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import uuid
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connections
from django.utils import timezone
from rest_framework.test import APIClient

from apps.kernels.payments.models import CashMovement
from apps.kernels.payments.services import open_cash_session_for_scope
from apps.kernels.portfolio.models import ObligationStatus, PaymentAllocation
from apps.kernels.portfolio.services import create_payable
from apps.modulos.compras.services import ProcurementError, ProcurementNotFoundError
from apps.modulos.compras.services_payments import pay_payable
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.parties.models import Party
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

User = get_user_model()


def _scope():
    s = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H_{s}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name=f"C_{s}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, name=f"B_{s}", parent=company)
    return company, branch


def _actor():
    t = uuid.uuid4().hex[:8]
    return User.objects.create_user(username=f"u_{t}", email=f"u_{t}@t.local", password="x")


def _req(company, branch, actor):
    return SimpleNamespace(
        company=company, branch=branch, user=actor,
        request_id="", headers={}, META={}, path="", method="POST",
    )


def _payable(company, branch, *, amount="1000.00"):
    supplier = Party.objects.create(
        company=company, party_type=Party.PartyType.JURIDICAL,
        display_name=f"Proveedor {uuid.uuid4().hex[:4]}",
    )
    today = timezone.localdate()
    return create_payable(
        company=company, branch=branch, party=supplier,
        reference_type="TEST_DOC", reference_id=int(uuid.uuid4().int % 10**6),
        principal_amount=Decimal(amount), currency="NIO",
        issue_date=today, due_date=today + timedelta(days=30),
    )


@pytest.fixture
def ctx(db):
    company, branch = _scope()
    actor = _actor()
    req = _req(company, branch, actor)
    payable = _payable(company, branch)
    return SimpleNamespace(company=company, branch=branch, actor=actor, req=req, payable=payable)


def test_pay_cash_posts_expense_and_updates_payable(ctx):
    open_cash_session_for_scope(
        company=ctx.company, branch=ctx.branch, actor=ctx.actor, opening_amount=Decimal("500.00")
    )
    out = pay_payable(
        request=ctx.req, actor=ctx.actor, payable_id=ctx.payable.id,
        amount=Decimal("400.00"), method="CASH", idempotency_key="P1",
    )
    assert out["status_after"] == ObligationStatus.PARTIAL
    assert out["outstanding_after"] == "600.00"
    assert out["cash_movement_id"] is not None
    movement = CashMovement.objects.get(id=out["cash_movement_id"])
    assert movement.movement_type == CashMovement.MovementType.EXPENSE
    assert movement.amount == Decimal("400.00")
    assert movement.reason == "PAGO_CXP"
    assert PaymentAllocation.objects.filter(allocation_id=out["allocation_id"]).exists()


def test_pay_transfer_completes_without_cash_session(ctx):
    # Transferencia: no exige sesión de caja ni registra movimiento de efectivo.
    out = pay_payable(
        request=ctx.req, actor=ctx.actor, payable_id=ctx.payable.id,
        amount=Decimal("1000.00"), method="TRANSFER", idempotency_key="P2",
    )
    assert out["status_after"] == ObligationStatus.PAID
    assert out["outstanding_after"] == "0.00"
    assert out["cash_movement_id"] is None
    assert not CashMovement.objects.filter(session__company=ctx.company).exists()


def test_pay_cash_without_open_session_rejected(ctx):
    with pytest.raises(ProcurementError, match="PROCUREMENT_CASH_SESSION_REQUIRED"):
        pay_payable(
            request=ctx.req, actor=ctx.actor, payable_id=ctx.payable.id,
            amount=Decimal("100.00"), method="CASH", idempotency_key="P3",
        )


def test_pay_exceeding_outstanding_rejected(ctx):
    with pytest.raises(ProcurementError, match="PROCUREMENT_AMOUNT_EXCEEDS_OUTSTANDING"):
        pay_payable(
            request=ctx.req, actor=ctx.actor, payable_id=ctx.payable.id,
            amount=Decimal("1000.01"), method="TRANSFER", idempotency_key="P4",
        )


def test_reentry_same_key_does_not_duplicate(ctx):
    open_cash_session_for_scope(
        company=ctx.company, branch=ctx.branch, actor=ctx.actor, opening_amount=Decimal("0.00")
    )
    first = pay_payable(
        request=ctx.req, actor=ctx.actor, payable_id=ctx.payable.id,
        amount=Decimal("400.00"), method="CASH", idempotency_key="P5",
    )
    again = pay_payable(
        request=ctx.req, actor=ctx.actor, payable_id=ctx.payable.id,
        amount=Decimal("400.00"), method="CASH", idempotency_key="P5",
    )
    assert again["allocation_id"] == first["allocation_id"]
    assert again["outstanding_after"] == "600.00"
    assert PaymentAllocation.objects.filter(payment_intent__company=ctx.company).count() == 1
    assert CashMovement.objects.filter(session__company=ctx.company, reason="PAGO_CXP").count() == 1


def test_paid_payable_rejects_more_payments(ctx):
    pay_payable(
        request=ctx.req, actor=ctx.actor, payable_id=ctx.payable.id,
        amount=Decimal("1000.00"), method="TRANSFER", idempotency_key="P6",
    )
    with pytest.raises(ProcurementError, match="PROCUREMENT_PAYABLE_NOT_OPEN"):
        pay_payable(
            request=ctx.req, actor=ctx.actor, payable_id=ctx.payable.id,
            amount=Decimal("10.00"), method="TRANSFER", idempotency_key="P7",
        )


@pytest.mark.django_db(transaction=True)
def test_distinct_concurrent_payment_keys_cannot_overpay_same_payable():
    """U17: dos pagos de 600 contra CxP 1000 dejan un ganador y nunca saldo negativo."""
    company, branch = _scope()
    actor = _actor()
    req = _req(company, branch, actor)
    payable = _payable(company, branch, amount="1000.00")
    barrier = Barrier(2)

    def pay(index: int):
        close_old_connections()
        barrier.wait(timeout=10)
        try:
            result = pay_payable(
                request=req,
                actor=actor,
                payable_id=payable.id,
                amount=Decimal("600.00"),
                method="TRANSFER",
                idempotency_key=f"PAY-CONCURRENT-{index}",
            )
            return "ok", result
        except ProcurementError as exc:
            return "error", str(exc)
        finally:
            close_old_connections()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(pay, range(2)))
    finally:
        connections.close_all()

    payable.refresh_from_db()
    assert sorted(kind for kind, _ in results) == ["error", "ok"]
    assert [payload for kind, payload in results if kind == "error"] == [
        "PROCUREMENT_AMOUNT_EXCEEDS_OUTSTANDING"
    ]
    assert payable.outstanding_amount == Decimal("400.00")
    assert PaymentAllocation.objects.filter(obligation_object_id=payable.id).count() == 1


def test_cross_company_payable_not_found(ctx):
    other_company, other_branch = _scope()
    foreign = _payable(other_company, other_branch)
    with pytest.raises(ProcurementNotFoundError):
        pay_payable(
            request=ctx.req, actor=ctx.actor, payable_id=foreign.id,
            amount=Decimal("10.00"), method="TRANSFER", idempotency_key="P8",
        )


def test_invalid_inputs_rejected(ctx):
    with pytest.raises(ProcurementError, match="PROCUREMENT_IDEMPOTENCY_REQUIRED"):
        pay_payable(
            request=ctx.req, actor=ctx.actor, payable_id=ctx.payable.id,
            amount=Decimal("10.00"), method="TRANSFER", idempotency_key="",
        )
    with pytest.raises(ProcurementError, match="PROCUREMENT_INVALID_PAYMENT_METHOD"):
        pay_payable(
            request=ctx.req, actor=ctx.actor, payable_id=ctx.payable.id,
            amount=Decimal("10.00"), method="BITCOIN", idempotency_key="P9",
        )
    with pytest.raises(ProcurementError, match="PROCUREMENT_AMOUNT_INVALID"):
        pay_payable(
            request=ctx.req, actor=ctx.actor, payable_id=ctx.payable.id,
            amount=Decimal("0.00"), method="TRANSFER", idempotency_key="P10",
        )


def _client_with_perms(*, company, branch, perm_codes):
    username = f"pp_{uuid.uuid4().hex[:8]}"
    user = User.objects.create_user(username=username, email=f"{username}@test.local", password="pass12345")
    UserMembership.objects.create(user=user, org_unit=company, is_active=True)
    UserMembership.objects.create(user=user, org_unit=branch, is_active=True)
    role = Role.objects.create(name=f"role_{uuid.uuid4().hex[:8]}", is_active=True)
    for code in perm_codes:
        perm, _ = Permission.objects.get_or_create(code=code, defaults={"description": code, "is_active": True})
        RolePermission.objects.get_or_create(role=role, permission=perm)
    RoleAssignment.objects.create(user=user, role=role, org_unit=company, is_active=True)

    client = APIClient()
    login = client.post("/api/auth/login/", {"username": user.username, "password": "pass12345"}, format="json")
    assert login.status_code == 200, login.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data.get('access')}")
    client.defaults["HTTP_X_COMPANY_ID"] = str(company.id)
    client.defaults["HTTP_X_BRANCH_ID"] = str(branch.id)
    return client


@pytest.mark.django_db
def test_api_requires_pay_permission():
    company, branch = _scope()
    payable = _payable(company, branch)
    body = {"payable_id": payable.id, "amount": "10.00", "method": "TRANSFER", "idempotency_key": "X1"}

    sin_perm = _client_with_perms(company=company, branch=branch, perm_codes=("procurement.doc.read",))
    assert sin_perm.post("/api/procurement/pay-payable/", body, format="json").status_code == 403

    con_perm = _client_with_perms(company=company, branch=branch, perm_codes=("procurement.payable.pay",))
    r = con_perm.post("/api/procurement/pay-payable/", body, format="json")
    assert r.status_code == 201, r.data
    assert r.data["status_after"] == "PARTIAL"
