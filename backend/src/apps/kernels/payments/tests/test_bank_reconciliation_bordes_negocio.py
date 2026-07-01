"""Bordes de negocio de la conciliación bancaria (finder de bugs).

Se concilia contra PaymentIntents CAPTURED, que SIEMPRE son cobros (entradas de
dinero; el modelo fuerza amount > 0 y no tiene noción de dirección saliente).
Una línea de extracto lleva SIGNO: +depósito / −retiro (ver docstring del modelo
BankStatementLine). El invariante de negocio es que un cobro (entrada) solo puede
respaldar una línea de DEPÓSITO (positiva), nunca un RETIRO (negativa).

El matching del kernel (reconciliation.match_line / _candidate_intents) compara
solo |monto| con abs(line.amount), por lo que un cobro de C$500 puede conciliar
una salida de −C$500. Esto es un descuadre de SENTIDO económico aunque el cuadre
de saldos (opening + Σ = closing) siga dando.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.kernels.payments.models import BankStatementLine
from apps.kernels.payments.reconciliation import (
    create_bank_account,
    create_bank_statement,
    match_line,
    suggest_matches,
)
from apps.kernels.payments.services import (
    capture_payment_intent_for_scope,
    create_payment_intent_for_scope,
)
from apps.modulos.iam.models import OrgUnit

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


def _captured_intent(company, branch, actor, *, amount, method="TRANSFER"):
    intent, _ = create_payment_intent_for_scope(
        company=company, branch=branch, actor=actor,
        amount=Decimal(amount), idempotency_key=f"bk-{uuid.uuid4().hex[:8]}",
        external_ref=f"ref-{uuid.uuid4().hex[:6]}", provider="CASHIER", payment_method=method,
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
        bank_name="BANPRO", account_number=f"AC{uuid.uuid4().hex[:6]}",
    )
    return SimpleNamespace(company=company, branch=branch, actor=actor, account=account)


def test_cobro_no_debe_conciliar_un_retiro_negativo(ctx):
    """Un cobro CAPTURED (entrada) NO debe poder respaldar una línea de RETIRO (−).

    Esto expone que match_line solo compara |monto| (abs) e ignora el signo de la
    línea: acepta conciliar un depósito esperado contra una salida del banco.
    """
    intent = _captured_intent(ctx.company, ctx.branch, ctx.actor, amount="500.00")
    today = timezone.localdate()
    st = create_bank_statement(
        company=ctx.company, actor=ctx.actor, bank_account_id=ctx.account.id,
        period_start=today - timedelta(days=10), period_end=today,
        opening_balance=Decimal("1000.00"), closing_balance=Decimal("500.00"),
        lines=[{"line_date": today.isoformat(), "description": "Pago a proveedor", "amount": "-500.00"}],
    )
    retiro = st.lines.get()
    assert retiro.amount == Decimal("-500.00")

    with pytest.raises(Exception) as exc:
        match_line(
            company=ctx.company, actor=ctx.actor,
            statement_id=st.id, line_id=retiro.id, payment_id=intent.payment_id,
        )
    # El error debe ser de mismatch de signo/dirección, no de monto absoluto.
    retiro.refresh_from_db()
    assert retiro.status == BankStatementLine.Status.UNMATCHED, (
        "BUG: un cobro (entrada, amount>0) quedó conciliado contra un retiro "
        "(salida, amount<0) — el matching ignora el signo de la línea."
    )
    assert "MISMATCH" in str(getattr(exc.value, "code", "")) or "SIGN" in str(getattr(exc.value, "code", ""))


def test_suggest_no_debe_proponer_cobro_para_un_retiro(ctx):
    """suggest_matches no debería ofrecer un cobro como candidato de un retiro (−)."""
    _captured_intent(ctx.company, ctx.branch, ctx.actor, amount="320.00")
    today = timezone.localdate()
    st = create_bank_statement(
        company=ctx.company, actor=ctx.actor, bank_account_id=ctx.account.id,
        period_start=today - timedelta(days=10), period_end=today,
        opening_balance=Decimal("1000.00"), closing_balance=Decimal("680.00"),
        lines=[{"line_date": today.isoformat(), "description": "Retiro/transf saliente", "amount": "-320.00"}],
    )
    retiro = st.lines.get()
    sug = {s["line_id"]: s["candidates"] for s in suggest_matches(company=ctx.company, statement_id=st.id)}
    assert sug[retiro.id] == [], (
        "BUG: suggest_matches propuso un cobro (entrada) como candidato para una "
        "línea de RETIRO (salida) por comparar solo el valor absoluto."
    )


def test_match_no_debe_conciliar_efectivo_contra_el_banco(ctx):
    """El efectivo se concilia por ARQUEO de caja, NO por extracto bancario.

    match_line solo filtra el intent por company+payment_id+CAPTURED (no por
    payment_method bancario), por lo que admite conciliar un cobro en EFECTIVO
    (CASH) contra una línea de extracto. El docstring del módulo es explícito:
    "el efectivo se arquea en caja".
    """
    intent_cash = _captured_intent(ctx.company, ctx.branch, ctx.actor, amount="200.00", method="CASH")
    today = timezone.localdate()
    st = create_bank_statement(
        company=ctx.company, actor=ctx.actor, bank_account_id=ctx.account.id,
        period_start=today - timedelta(days=10), period_end=today,
        opening_balance=Decimal("1000.00"), closing_balance=Decimal("1200.00"),
        lines=[{"line_date": today.isoformat(), "description": "Depósito", "amount": "200.00"}],
    )
    line = st.lines.get()
    with pytest.raises(Exception):
        match_line(
            company=ctx.company, actor=ctx.actor,
            statement_id=st.id, line_id=line.id, payment_id=intent_cash.payment_id,
        )
    line.refresh_from_db()
    assert line.status == BankStatementLine.Status.UNMATCHED, (
        "BUG: un cobro en EFECTIVO (CASH) quedó conciliado contra el extracto "
        "bancario; el efectivo debe conciliarse por arqueo de caja, no aquí."
    )


def test_match_no_debe_cruzar_monedas_distintas(ctx):
    """match_line no valida la moneda: concilia un cobro en USD contra una cuenta
    bancaria NIO solo porque el valor numérico coincide.

    La cuenta de ctx es NIO; un intent en USD por 150.00 NO debe poder respaldar
    una línea de C$150.00 (son monedas distintas; el valor absoluto coincide pero
    el sentido económico no).
    """
    intent_usd = create_payment_intent_for_scope(
        company=ctx.company, branch=ctx.branch, actor=ctx.actor,
        amount=Decimal("150.00"), currency="USD",
        idempotency_key=f"usd-{uuid.uuid4().hex[:8]}",
        external_ref=f"ref-{uuid.uuid4().hex[:6]}", provider="CASHIER", payment_method="TRANSFER",
    )[0]
    intent_usd = capture_payment_intent_for_scope(
        company=ctx.company, branch=ctx.branch, actor=ctx.actor, payment_id=intent_usd.payment_id,
    )
    assert intent_usd.currency == "USD"
    assert ctx.account.currency == "NIO"

    today = timezone.localdate()
    st = create_bank_statement(
        company=ctx.company, actor=ctx.actor, bank_account_id=ctx.account.id,
        period_start=today - timedelta(days=10), period_end=today,
        opening_balance=Decimal("1000.00"), closing_balance=Decimal("1150.00"),
        lines=[{"line_date": today.isoformat(), "description": "Depósito C$150", "amount": "150.00"}],
    )
    line = st.lines.get()
    with pytest.raises(Exception):
        match_line(
            company=ctx.company, actor=ctx.actor,
            statement_id=st.id, line_id=line.id, payment_id=intent_usd.payment_id,
        )
    line.refresh_from_db()
    assert line.status == BankStatementLine.Status.UNMATCHED, (
        "BUG: un cobro en USD quedó conciliado contra una línea de cuenta NIO; "
        "match_line no valida la moneda del intent vs la cuenta bancaria."
    )
