"""Tests Ola E: cierre anual del ejercicio.

El cierre lleva REVENUE/EXPENSE a 0 contra retained_earnings y sella diciembre;
reabrir reversa el asiento y restaura el P&L.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.accounting.models import (
    ChartOfAccount,
    FiscalPeriod,
    JournalEntryLine,
    YearEndClosing,
)
from apps.kernels.accounting.phase7 import get_or_create_accounting_config
from apps.kernels.accounting.services import approve_journal_drafts, post_journal_drafts
from apps.kernels.accounting.services_costcenters import (
    AccountingPlusError,
    create_manual_journal_draft,
)
from apps.kernels.accounting.services_yearend import (
    close_fiscal_year,
    get_year_end_status,
    reopen_fiscal_year,
)
from apps.modulos.iam.models import OrgUnit

User = get_user_model()
YEAR = 2024


def _actor():
    n = f"u_{uuid.uuid4().hex[:8]}"
    return User.objects.create_user(username=n, email=f"{n}@t.com", password="x")


def _acc(company, code, atype):
    return ChartOfAccount.objects.create(company=company, code=code, name=code, account_type=atype)


def _company(*, with_re=True):
    s = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H_{s}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name=f"C_{s}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, name=f"B_{s}", parent=company)
    cfg = get_or_create_accounting_config(company=company)
    cfg.phase7_enabled = True
    if with_re:
        cfg.retained_earnings_account = _acc(company, "RESULT", ChartOfAccount.AccountType.EQUITY)
    cfg.save(update_fields=["phase7_enabled", "retained_earnings_account"])
    return company, branch


def _post(company, branch, maker, approver, lines):
    create_manual_journal_draft(
        company=company, branch=branch, actor=maker,
        entry_date=date(YEAR, 12, 15), memo="op", lines=lines,
    )
    approve_journal_drafts(company_id=company.id, actor_user=approver)
    post_journal_drafts(company_id=company.id, require_approved=True, actor_user=maker)


def _result_net(company, code):
    agg = JournalEntryLine.objects.filter(
        journal_entry__company=company, journal_entry__is_posted=True,
        account__code=code, journal_entry__period__year=YEAR,
    )
    debit = sum((line.debit_base for line in agg), Decimal("0.00"))
    credit = sum((line.credit_base for line in agg), Decimal("0.00"))
    return debit, credit


def _close_months_1_11(company):
    for m in range(1, 12):
        FiscalPeriod.objects.update_or_create(
            company=company, year=YEAR, month=m, defaults={"status": FiscalPeriod.Status.CLOSED},
        )


@pytest.fixture
def ctx(db):
    company, branch = _company()
    maker = _actor()
    approver = _actor()
    _acc(company, "VENTA", ChartOfAccount.AccountType.REVENUE)
    _acc(company, "GASTO", ChartOfAccount.AccountType.EXPENSE)
    _acc(company, "CAJA", ChartOfAccount.AccountType.ASSET)
    # Ingreso 5000, gasto 3000 → utilidad neta 2000 (todo en diciembre).
    _post(company, branch, maker, approver, [
        {"account_code": "CAJA", "side": "DEBIT", "amount": "5000.00"},
        {"account_code": "VENTA", "side": "CREDIT", "amount": "5000.00"},
    ])
    _post(company, branch, maker, approver, [
        {"account_code": "GASTO", "side": "DEBIT", "amount": "3000.00"},
        {"account_code": "CAJA", "side": "CREDIT", "amount": "3000.00"},
    ])
    return dict(company=company, branch=branch, maker=maker, approver=approver)


def test_year_end_zeroes_pnl_into_retained_earnings(ctx):
    company = ctx["company"]
    _close_months_1_11(company)

    status = close_fiscal_year(company=company, fiscal_year=YEAR, actor=ctx["maker"])
    assert status["status"] == YearEndClosing.Status.CLOSED
    assert status["net_result"] == "2000.00"

    # REVENUE y EXPENSE quedan en 0 (saldo neto del año, incluido el asiento de cierre).
    rd, rc = _result_net(company, "VENTA")
    assert rd == rc  # neto 0
    gd, gc = _result_net(company, "GASTO")
    assert gd == gc

    # Resultados acumulados (EQUITY) recibió la utilidad como crédito (2000).
    ed, ec = _result_net(company, "RESULT")  # helper agrega cualquier cuenta del año
    assert (ec - ed) == Decimal("2000.00")

    # Diciembre quedó CLOSED.
    dec = FiscalPeriod.objects.get(company=company, year=YEAR, month=12)
    assert dec.status == FiscalPeriod.Status.CLOSED


def test_year_end_idempotent(ctx):
    company = ctx["company"]
    _close_months_1_11(company)
    a = close_fiscal_year(company=company, fiscal_year=YEAR, actor=ctx["maker"])
    b = close_fiscal_year(company=company, fiscal_year=YEAR, actor=ctx["maker"])
    assert a["closing_entry_id"] == b["closing_entry_id"]
    assert YearEndClosing.objects.filter(company=company, fiscal_year=YEAR).count() == 1


def test_year_end_gate_months_open(ctx):
    # Sin cerrar meses 1-11 → bloqueado.
    with pytest.raises(AccountingPlusError) as e:
        close_fiscal_year(company=ctx["company"], fiscal_year=YEAR, actor=ctx["maker"])
    assert e.value.code == "ACCOUNTING_YEAR_END_MONTHS_OPEN"


def test_year_end_requires_retained_earnings(db):
    company, branch = _company(with_re=False)
    maker, approver = _actor(), _actor()
    _acc(company, "VENTA", ChartOfAccount.AccountType.REVENUE)
    _acc(company, "CAJA", ChartOfAccount.AccountType.ASSET)
    _post(company, branch, maker, approver, [
        {"account_code": "CAJA", "side": "DEBIT", "amount": "100.00"},
        {"account_code": "VENTA", "side": "CREDIT", "amount": "100.00"},
    ])
    _close_months_1_11(company)
    with pytest.raises(AccountingPlusError) as e:
        close_fiscal_year(company=company, fiscal_year=YEAR, actor=maker)
    assert e.value.code == "ACCOUNTING_RETAINED_EARNINGS_NOT_CONFIGURED"


def test_year_end_reopen_restores_pnl(ctx):
    company = ctx["company"]
    _close_months_1_11(company)
    close_fiscal_year(company=company, fiscal_year=YEAR, actor=ctx["maker"])

    reopen = reopen_fiscal_year(
        company=company, fiscal_year=YEAR, reason="Ajuste posterior", actor=ctx["maker"],
    )
    assert reopen["status"] == YearEndClosing.Status.REOPENED

    # Tras la reversa, el ingreso vuelve a tener saldo vivo (5000 neto crédito).
    rd, rc = _result_net(company, "VENTA")
    assert (rc - rd) == Decimal("5000.00")
    # Resultados acumulados vuelve a 0.
    ed, ec = _result_net(company, "RESULT")
    assert (ec - ed) == Decimal("0.00")
    # Diciembre quedó reabierto.
    dec = FiscalPeriod.objects.get(company=company, year=YEAR, month=12)
    assert dec.status == FiscalPeriod.Status.OPEN


def test_year_end_status_reports_gate(ctx):
    company = ctx["company"]
    st = get_year_end_status(company=company, fiscal_year=YEAR)
    assert st["status"] is None
    assert st["net_result"] == "2000.00"
    assert sorted(st["months_pending_close"]) == list(range(1, 12))
