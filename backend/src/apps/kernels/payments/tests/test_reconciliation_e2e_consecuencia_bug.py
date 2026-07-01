"""Consecuencia END-TO-END del bug de matching de conciliación bancaria.

Complementa test_bank_reconciliation_bordes_negocio.py mostrando el IMPACTO de
negocio: como match_line solo compara |monto| (ignora signo, moneda y método del
intent), un RETIRO del banco puede quedar "conciliado" contra un cobro de cliente
(entrada) y el extracto se sella como RECONCILED — un descuadre de sentido económico
que aprueba una conciliación falsa.

Este test FALLA hoy (documenta el bug). Cuando match_line valide signo/dirección
debe pasar a verde sin tocarlo. NO ablandar.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.kernels.payments.models import BankStatement
from apps.kernels.payments.reconciliation import (
    create_bank_account,
    create_bank_statement,
    match_line,
    reconcile_statement,
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


@pytest.fixture
def ctx(db):
    company, branch = _scope()
    actor = _actor()
    account = create_bank_account(
        company=company, actor=actor, name="Cuenta Corriente",
        bank_name="BANPRO", account_number=f"AC{uuid.uuid4().hex[:6]}",
    )
    return SimpleNamespace(company=company, branch=branch, actor=actor, account=account)


def test_un_cobro_no_debe_sellar_la_conciliacion_de_un_retiro(ctx):
    """Cobro de cliente C$1,000 (entrada). El extracto tiene un RETIRO de −C$1,000.

    El cobro NO respalda un retiro. Si match_line lo acepta, el extracto se concilia
    (RECONCILED) con una correspondencia económicamente falsa.
    """
    intent, _ = create_payment_intent_for_scope(
        company=ctx.company, branch=ctx.branch, actor=ctx.actor,
        amount=Decimal("1000.00"), idempotency_key=f"ck-{uuid.uuid4().hex[:8]}",
        external_ref="COBRO-CLIENTE", provider="CASHIER", payment_method="TRANSFER",
    )
    intent = capture_payment_intent_for_scope(
        company=ctx.company, branch=ctx.branch, actor=ctx.actor, payment_id=intent.payment_id,
    )

    today = timezone.localdate()
    st = create_bank_statement(
        company=ctx.company, actor=ctx.actor, bank_account_id=ctx.account.id,
        period_start=today - timedelta(days=5), period_end=today,
        # Saldo baja por un retiro: opening 5000 + (−1000) = closing 4000.
        opening_balance=Decimal("5000.00"), closing_balance=Decimal("4000.00"),
        lines=[{"line_date": today.isoformat(), "description": "Transferencia SALIENTE", "amount": "-1000.00"}],
    )
    retiro = st.lines.get()
    assert retiro.amount == Decimal("-1000.00")

    # Intentar conciliar el cobro (entrada) contra el retiro (salida) DEBE fallar.
    reconciled_ok = False
    try:
        match_line(
            company=ctx.company, actor=ctx.actor,
            statement_id=st.id, line_id=retiro.id, payment_id=intent.payment_id,
        )
        reconcile_statement(company=ctx.company, actor=ctx.actor, statement_id=st.id)
        reconciled_ok = True
    except Exception:
        reconciled_ok = False

    st.refresh_from_db()
    assert not reconciled_ok and st.status != BankStatement.Status.RECONCILED, (
        "BUG (payments/reconciliation.py match_line): un COBRO (entrada, amount>0) "
        "respaldó un RETIRO (salida, amount<0) y el extracto quedó RECONCILED. "
        "match_line compara solo abs(monto) e ignora el signo/dirección del movimiento."
    )
