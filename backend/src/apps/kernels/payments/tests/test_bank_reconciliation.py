"""Tests de conciliación bancaria (Ola D): cuentas, extractos, matching y cierre.

Se concilia contra PaymentIntents CAPTURED de métodos bancarios (TRANSFER/CHECK/
CARD); conciliar exige 100% de líneas resueltas Y cuadre de saldos; el extracto
RECONCILED queda inmutable.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.kernels.payments.models import BankStatement
from apps.kernels.payments.reconciliation import (
    create_bank_account,
    create_bank_statement,
    exclude_line,
    match_line,
    reconcile_statement,
    suggest_matches,
    unmatch_line,
)
from apps.kernels.payments.services import (
    PaymentsDomainError,
    capture_payment_intent_for_scope,
    create_payment_intent_for_scope,
)
from apps.modulos.iam.models import OrgUnit, UserMembership
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


def _captured_intent(company, branch, actor, *, amount="500.00", method="TRANSFER", ref=""):
    intent, _ = create_payment_intent_for_scope(
        company=company, branch=branch, actor=actor,
        amount=Decimal(amount), idempotency_key=f"bk-{uuid.uuid4().hex[:8]}",
        external_ref=ref or f"ref-{uuid.uuid4().hex[:6]}", provider="CASHIER", payment_method=method,
    )
    return capture_payment_intent_for_scope(
        company=company, branch=branch, actor=actor, payment_id=intent.payment_id,
    )


@pytest.fixture
def ctx(db):
    company, branch = _scope()
    actor = _actor()
    account = create_bank_account(
        company=company, actor=actor, name="Cuenta Corriente",
        bank_name="BANPRO", account_number="100200300",
    )
    return SimpleNamespace(company=company, branch=branch, actor=actor, account=account)


def _statement(ctx, *, lines, opening="1000.00", closing=None):
    today = timezone.localdate()
    if closing is None:
        closing = str(Decimal(opening) + sum(Decimal(str(ln["amount"])) for ln in lines))
    return create_bank_statement(
        company=ctx.company, actor=ctx.actor, bank_account_id=ctx.account.id,
        period_start=today - timedelta(days=30), period_end=today,
        opening_balance=Decimal(opening), closing_balance=Decimal(closing), lines=lines,
    )


def test_duplicate_account_rejected(ctx):
    with pytest.raises(PaymentsDomainError, match="PAYMENTS_BANK_ACCOUNT_DUPLICATE"):
        create_bank_account(
            company=ctx.company, actor=ctx.actor, name="Otra",
            bank_name="BANPRO", account_number="100200300",
        )


def test_suggest_finds_intent_by_amount_and_date(ctx):
    intent = _captured_intent(ctx.company, ctx.branch, ctx.actor, amount="750.00")
    # Mismo monto pero EFECTIVO: jamás se sugiere (el efectivo se arquea en caja).
    _captured_intent(ctx.company, ctx.branch, ctx.actor, amount="750.00", method="CASH")
    today = timezone.localdate()
    st = _statement(ctx, lines=[
        {"line_date": today.isoformat(), "description": "Depósito", "amount": "750.00"},
        {"line_date": today.isoformat(), "description": "Comisión", "amount": "-25.00"},
    ])
    suggestions = {s["line_id"]: s["candidates"] for s in suggest_matches(company=ctx.company, statement_id=st.id)}
    lines = list(st.lines.all())
    assert [c["payment_id"] for c in suggestions[lines[0].id]] == [str(intent.payment_id)]
    assert suggestions[lines[1].id] == []  # la comisión no tiene pago del sistema


def test_suggest_ignores_already_matched_and_far_dates(ctx):
    intent = _captured_intent(ctx.company, ctx.branch, ctx.actor, amount="300.00")
    today = timezone.localdate()
    st = _statement(ctx, lines=[
        {"line_date": today.isoformat(), "amount": "300.00"},
        {"line_date": (today - timedelta(days=20)).isoformat(), "amount": "300.00"},
    ])
    l1, l2 = list(st.lines.all())
    # l2 está a 20 días del captured_at: fuera de la ventana ±3.
    sug = {s["line_id"]: s["candidates"] for s in suggest_matches(company=ctx.company, statement_id=st.id)}
    assert len(sug[l1.id]) == 1 and sug[l2.id] == []
    # Una vez matcheado a l1, deja de sugerirse en cualquier parte.
    match_line(company=ctx.company, actor=ctx.actor, statement_id=st.id, line_id=l1.id,
               payment_id=intent.payment_id)
    sug = {s["line_id"]: s["candidates"] for s in suggest_matches(company=ctx.company, statement_id=st.id)}
    assert sug[l2.id] == []


def test_intent_cannot_back_two_lines(ctx):
    intent = _captured_intent(ctx.company, ctx.branch, ctx.actor, amount="100.00")
    today = timezone.localdate()
    st = _statement(ctx, lines=[
        {"line_date": today.isoformat(), "amount": "100.00"},
        {"line_date": today.isoformat(), "amount": "100.00"},
    ])
    l1, l2 = list(st.lines.all())
    match_line(company=ctx.company, actor=ctx.actor, statement_id=st.id, line_id=l1.id,
               payment_id=intent.payment_id)
    with pytest.raises(PaymentsDomainError, match="PAYMENTS_INTENT_ALREADY_MATCHED"):
        match_line(company=ctx.company, actor=ctx.actor, statement_id=st.id, line_id=l2.id,
                   payment_id=intent.payment_id)
    # unmatch libera el intent para la otra línea.
    unmatch_line(company=ctx.company, actor=ctx.actor, statement_id=st.id, line_id=l1.id)
    out = match_line(company=ctx.company, actor=ctx.actor, statement_id=st.id, line_id=l2.id,
                     payment_id=intent.payment_id)
    assert out["status"] == "MATCHED"


def test_match_amount_mismatch_rejected(ctx):
    intent = _captured_intent(ctx.company, ctx.branch, ctx.actor, amount="100.00")
    today = timezone.localdate()
    st = _statement(ctx, lines=[{"line_date": today.isoformat(), "amount": "99.00"}])
    line = st.lines.get()
    with pytest.raises(PaymentsDomainError, match="PAYMENTS_MATCH_AMOUNT_MISMATCH"):
        match_line(company=ctx.company, actor=ctx.actor, statement_id=st.id, line_id=line.id,
                   payment_id=intent.payment_id)


def test_reconcile_requires_all_lines_and_balance(ctx):
    intent = _captured_intent(ctx.company, ctx.branch, ctx.actor, amount="400.00")
    today = timezone.localdate()
    st = _statement(ctx, lines=[
        {"line_date": today.isoformat(), "amount": "400.00"},
        {"line_date": today.isoformat(), "description": "Comisión mensual", "amount": "-15.00"},
    ])
    l1, l2 = list(st.lines.all())
    with pytest.raises(PaymentsDomainError, match="PAYMENTS_STATEMENT_LINES_PENDING"):
        reconcile_statement(company=ctx.company, actor=ctx.actor, statement_id=st.id)

    match_line(company=ctx.company, actor=ctx.actor, statement_id=st.id, line_id=l1.id,
               payment_id=intent.payment_id)
    exclude_line(company=ctx.company, actor=ctx.actor, statement_id=st.id, line_id=l2.id,
                 reason="Comisión bancaria, no es pago del sistema")
    out = reconcile_statement(company=ctx.company, actor=ctx.actor, statement_id=st.id)
    assert out.status == BankStatement.Status.RECONCILED
    assert out.reconciled_at is not None

    # Inmutable: ni deshacer ni re-conciliar.
    with pytest.raises(PaymentsDomainError, match="PAYMENTS_STATEMENT_NOT_OPEN"):
        unmatch_line(company=ctx.company, actor=ctx.actor, statement_id=st.id, line_id=l1.id)
    with pytest.raises(PaymentsDomainError, match="PAYMENTS_STATEMENT_NOT_OPEN"):
        reconcile_statement(company=ctx.company, actor=ctx.actor, statement_id=st.id)


def test_reconcile_unbalanced_rejected(ctx):
    today = timezone.localdate()
    # Cuadre imposible: opening 1000 + (-15) ≠ closing 2000.
    st = _statement(ctx, lines=[{"line_date": today.isoformat(), "amount": "-15.00"}], closing="2000.00")
    line = st.lines.get()
    exclude_line(company=ctx.company, actor=ctx.actor, statement_id=st.id, line_id=line.id, reason="Comisión")
    with pytest.raises(PaymentsDomainError, match="PAYMENTS_STATEMENT_UNBALANCED"):
        reconcile_statement(company=ctx.company, actor=ctx.actor, statement_id=st.id)
    st.refresh_from_db()
    assert st.status == BankStatement.Status.OPEN


def test_exclude_requires_reason(ctx):
    today = timezone.localdate()
    st = _statement(ctx, lines=[{"line_date": today.isoformat(), "amount": "-15.00"}])
    line = st.lines.get()
    with pytest.raises(PaymentsDomainError, match="PAYMENTS_EXCLUDE_REASON_REQUIRED"):
        exclude_line(company=ctx.company, actor=ctx.actor, statement_id=st.id, line_id=line.id, reason="  ")


def test_cross_company_isolated(ctx):
    other_company, other_branch = _scope()
    other_actor = _actor()
    with pytest.raises(PaymentsDomainError, match="PAYMENTS_BANK_ACCOUNT_NOT_FOUND"):
        create_bank_statement(
            company=other_company, actor=other_actor, bank_account_id=ctx.account.id,
            period_start=timezone.localdate(), period_end=timezone.localdate(),
            opening_balance=Decimal("0"), closing_balance=Decimal("0"),
            lines=[{"line_date": timezone.localdate().isoformat(), "amount": "10.00"}],
        )


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
def test_api_rbac_split_read_manage_reconcile():
    company, branch = _scope()
    lector = _client(company=company, branch=branch, perms=("payments.bank.read",))
    assert lector.get("/api/payments/bank-accounts/").status_code == 200
    cuenta = {"name": "CC", "bank_name": "LAFISE", "account_number": "9"}
    assert lector.post("/api/payments/bank-accounts/", cuenta, format="json").status_code == 403

    gestor = _client(company=company, branch=branch, perms=("payments.bank.read", "payments.bank.manage"))
    r = gestor.post("/api/payments/bank-accounts/", cuenta, format="json")
    assert r.status_code == 201, r.data
    today = timezone.localdate().isoformat()
    r = gestor.post("/api/payments/bank-statements/", {
        "bank_account_id": r.data["id"], "period_start": today, "period_end": today,
        "opening_balance": "0.00", "closing_balance": "-15.00",
        "lines": [{"line_date": today, "description": "Comisión", "amount": "-15.00"}],
    }, format="json")
    assert r.status_code == 201, r.data
    st_id = r.data["id"]
    line_id = r.data["lines"][0]["id"]
    # manage no alcanza para conciliar.
    assert gestor.post(
        f"/api/payments/bank-statements/{st_id}/lines/{line_id}/exclude/",
        {"reason": "Comisión"}, format="json",
    ).status_code == 403

    conciliador = _client(
        company=company, branch=branch,
        perms=("payments.bank.read", "payments.bank.reconcile"),
    )
    assert conciliador.post(
        f"/api/payments/bank-statements/{st_id}/lines/{line_id}/exclude/",
        {"reason": "Comisión bancaria"}, format="json",
    ).status_code == 200
    r = conciliador.post(f"/api/payments/bank-statements/{st_id}/reconcile/")
    assert r.status_code == 200 and r.data["status"] == "RECONCILED"
