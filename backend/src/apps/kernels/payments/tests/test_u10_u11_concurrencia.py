"""
U10/U11 (oleada 2) — certificación de concurrencia del kernel payments:

- U10 (caja/arqueo): dos cierres concurrentes de la MISMA sesión no corrompen
  el arqueo — el lock serializa, uno fija el conteo y el otro es idempotente
  (devuelve la sesión ya CLOSED sin pisarle los montos).
- U10 (apertura): dos aperturas concurrentes del mismo register no crean dos
  sesiones OPEN.
- U11 (conciliación): dos match concurrentes del MISMO intent contra líneas
  distintas — exactamente uno gana; el otro recibe INTENT_ALREADY_MATCHED.
"""
from __future__ import annotations

import threading
import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.kernels.payments.models import BankStatementLine, CashSession
from apps.kernels.payments.reconciliation import (
    create_bank_account,
    create_bank_statement,
    match_line,
)
from apps.kernels.payments.services import (
    PaymentsConflictError,
    capture_payment_intent_for_scope,
    close_cash_session_for_scope,
    create_payment_intent_for_scope,
    open_cash_session_for_scope,
)
from apps.modulos.iam.models import OrgUnit

User = get_user_model()


def _scope():
    t = uuid.uuid4().hex[:8]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H{t}", code=f"H-{t}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, parent=holding, name=f"C{t}", code=f"C-{t}")
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, parent=company, name=f"B{t}", code=f"B-{t}")
    actor = User.objects.create_user(username=f"u_{t}", email=f"u_{t}@t.local", password="x")
    return SimpleNamespace(company=company, branch=branch, actor=actor)


def _run_concurrente(workers):
    """Corre los callables en hilos con barrier; devuelve la lista de excepciones (o None)."""
    from django.db import connection as db_conn

    barrier = threading.Barrier(len(workers), timeout=10)
    results: list[Exception | None] = [None] * len(workers)

    def wrap(i, fn):
        try:
            barrier.wait()
            fn()
        except Exception as exc:  # noqa: BLE001 — el test clasifica la excepción
            results[i] = exc
        finally:
            db_conn.close()

    threads = [threading.Thread(target=wrap, args=(i, fn)) for i, fn in enumerate(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


# ---------------------------------------------------------------------------
# U10 — caja/arqueo
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_cierre_de_caja_concurrente_no_corrompe_el_arqueo():
    ctx = _scope()
    session = open_cash_session_for_scope(
        company=ctx.company, branch=ctx.branch, actor=ctx.actor,
        opening_amount=Decimal("100.00"), register_id=f"caja-{uuid.uuid4().hex[:4]}",
    )

    resultados = _run_concurrente([
        lambda: close_cash_session_for_scope(
            company=ctx.company, branch=ctx.branch, actor=ctx.actor,
            session_id=session.id, counted_amount=Decimal("100.00"),
        ),
        lambda: close_cash_session_for_scope(
            company=ctx.company, branch=ctx.branch, actor=ctx.actor,
            session_id=session.id, counted_amount=Decimal("999.00"),
        ),
    ])

    # Ninguno debe morir con error inesperado (el 2º cierre es idempotente).
    assert all(r is None for r in resultados), resultados

    session.refresh_from_db()
    assert session.status == CashSession.Status.CLOSED
    # El conteo persistido es el del hilo que GANÓ el lock (uno de los dos),
    # y la diferencia es consistente con ese conteo — sin mezclas.
    assert session.counted_amount in (Decimal("100.00"), Decimal("999.00"))
    assert session.difference_amount == session.counted_amount - session.expected_amount


@pytest.mark.django_db(transaction=True)
def test_apertura_concurrente_mismo_register_solo_una_open():
    ctx = _scope()
    register = f"caja-{uuid.uuid4().hex[:4]}"

    def abrir():
        open_cash_session_for_scope(
            company=ctx.company, branch=ctx.branch, actor=ctx.actor,
            opening_amount=Decimal("50.00"), register_id=register,
        )

    resultados = _run_concurrente([abrir, abrir])

    abiertas = CashSession.objects.filter(
        company=ctx.company, branch=ctx.branch, register_id=register,
        status=CashSession.Status.OPEN,
    ).count()
    errores = [r for r in resultados if r is not None]
    assert abiertas == 1, f"esperaba 1 sesión OPEN, hay {abiertas}"
    assert len(errores) == 1 and isinstance(errores[0], PaymentsConflictError), errores


# ---------------------------------------------------------------------------
# U11 — conciliación bancaria
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_match_concurrente_mismo_intent_solo_uno_gana():
    ctx = _scope()
    account = create_bank_account(
        company=ctx.company, actor=ctx.actor, name="Cta",
        bank_name="BANPRO", account_number=f"9{uuid.uuid4().hex[:8]}",
    )
    intent, _ = create_payment_intent_for_scope(
        company=ctx.company, branch=ctx.branch, actor=ctx.actor,
        amount=Decimal("800.00"), idempotency_key=f"u11-{uuid.uuid4().hex[:8]}",
        external_ref="ref-u11", provider="CASHIER", payment_method="TRANSFER",
    )
    intent = capture_payment_intent_for_scope(
        company=ctx.company, branch=ctx.branch, actor=ctx.actor, payment_id=intent.payment_id,
    )

    today = timezone.localdate()
    st = create_bank_statement(
        company=ctx.company, actor=ctx.actor, bank_account_id=account.id,
        period_start=today - timedelta(days=5), period_end=today,
        opening_balance=Decimal("0.00"), closing_balance=Decimal("1600.00"),
        lines=[
            {"line_date": today, "description": "dep A", "amount": "800.00"},
            {"line_date": today, "description": "dep B", "amount": "800.00"},
        ],
    )
    l1, l2 = list(st.lines.order_by("id"))

    resultados = _run_concurrente([
        lambda: match_line(
            company=ctx.company, actor=ctx.actor, statement_id=st.id,
            line_id=l1.id, payment_id=intent.payment_id,
        ),
        lambda: match_line(
            company=ctx.company, actor=ctx.actor, statement_id=st.id,
            line_id=l2.id, payment_id=intent.payment_id,
        ),
    ])

    matched = BankStatementLine.objects.filter(
        statement=st, status=BankStatementLine.Status.MATCHED
    ).count()
    errores = [r for r in resultados if r is not None]
    assert matched == 1, f"esperaba 1 línea MATCHED, hay {matched} (doble uso del mismo cobro)"
    assert len(errores) == 1, f"esperaba exactamente un rechazo, hubo {len(errores)}: {errores}"
    assert "PAYMENTS_INTENT_ALREADY_MATCHED" in str(errores[0]) or "PAYMENTS_STATEMENT" in str(errores[0]), errores
