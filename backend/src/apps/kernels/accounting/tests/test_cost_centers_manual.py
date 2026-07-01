"""Tests Ola E: centros de costo + asientos manuales con dimensión analítica.

El asiento manual se crea como draft VALIDATED y fluye por el flujo SoD EXISTENTE
(aprobar≠generar, postear≠aprobar). Al postear, el centro de costo queda en
`JournalEntryLine.cost_center`.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.accounting.models import (
    ChartOfAccount,
    CostCenter,
    JournalDraft,
    JournalEntryLine,
)
from apps.kernels.accounting.phase7 import get_or_create_accounting_config
from apps.kernels.accounting.services import approve_journal_drafts, post_journal_drafts
from apps.kernels.accounting.services_costcenters import (
    AccountingPlusError,
    create_cost_center,
    create_manual_journal_draft,
)
from apps.modulos.iam.models import OrgUnit

User = get_user_model()


def _company():
    s = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H_{s}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name=f"C_{s}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, name=f"B_{s}", parent=company)
    cfg = get_or_create_accounting_config(company=company)
    cfg.phase7_enabled = True
    cfg.save(update_fields=["phase7_enabled"])
    return company, branch


def _actor():
    n = f"u_{uuid.uuid4().hex[:8]}"
    return User.objects.create_user(username=n, email=f"{n}@t.com", password="x")


def _acc(company, code, atype, postable=True):
    return ChartOfAccount.objects.create(
        company=company, code=code, name=code, account_type=atype, is_postable=postable,
    )


@pytest.fixture
def ctx(db):
    company, branch = _company()
    maker = _actor()
    approver = _actor()
    expense = _acc(company, "GASTO", ChartOfAccount.AccountType.EXPENSE)
    cash = _acc(company, "CAJA", ChartOfAccount.AccountType.ASSET)
    cc1 = create_cost_center(company=company, actor=maker, code="ADM", name="Administración")
    cc2 = create_cost_center(company=company, actor=maker, code="PROD", name="Producción")
    return dict(company=company, branch=branch, maker=maker, approver=approver,
                expense=expense, cash=cash, cc1=cc1, cc2=cc2)


def test_cost_center_unique_code(ctx):
    with pytest.raises(AccountingPlusError) as e:
        create_cost_center(company=ctx["company"], actor=ctx["maker"], code="adm", name="dup")
    assert e.value.code == "ACCOUNTING_COST_CENTER_DUPLICATE"


def _manual(ctx, lines, entry_date=date(2026, 3, 10)):
    return create_manual_journal_draft(
        company=ctx["company"], branch=ctx["branch"], actor=ctx["maker"],
        entry_date=entry_date, memo="ajuste", lines=lines,
    )


def test_manual_draft_balanced_then_posts_with_cost_center(ctx):
    draft = _manual(ctx, [
        {"account_code": "GASTO", "side": "DEBIT", "amount": "300.00", "cost_center_id": ctx["cc1"].id},
        {"account_code": "CAJA", "side": "CREDIT", "amount": "300.00"},
    ])
    assert draft.state == JournalDraft.State.VALIDATED

    # SoD: el generador no puede aprobar su propio draft.
    self_appr = approve_journal_drafts(company_id=ctx["company"].id, actor_user=ctx["maker"])
    assert self_appr.approved == 0 and self_appr.failed == 1

    appr = approve_journal_drafts(company_id=ctx["company"].id, actor_user=ctx["approver"])
    assert appr.approved == 1
    # postear (poster=maker ≠ approver) → OK
    posted = post_journal_drafts(company_id=ctx["company"].id, require_approved=True, actor_user=ctx["maker"])
    assert posted.posted == 1

    draft.refresh_from_db()
    line = JournalEntryLine.objects.get(journal_entry__draft=draft, account=ctx["expense"])
    assert line.cost_center_id == ctx["cc1"].id
    assert line.debit_base == Decimal("300.00")
    # La línea de caja no llevaba centro de costo.
    cash_line = JournalEntryLine.objects.get(journal_entry__draft=draft, account=ctx["cash"])
    assert cash_line.cost_center_id is None


def test_manual_unbalanced_rejected(ctx):
    with pytest.raises(AccountingPlusError) as e:
        _manual(ctx, [
            {"account_code": "GASTO", "side": "DEBIT", "amount": "300.00"},
            {"account_code": "CAJA", "side": "CREDIT", "amount": "250.00"},
        ])
    assert e.value.code == "ACCOUNTING_MANUAL_UNBALANCED"


def test_manual_cost_center_foreign_company_rejected(ctx):
    other_company, _ = _company()
    foreign_cc = CostCenter.objects.create(company=other_company, code="X", name="X")
    with pytest.raises(AccountingPlusError) as e:
        _manual(ctx, [
            {"account_code": "GASTO", "side": "DEBIT", "amount": "100.00", "cost_center_id": foreign_cc.id},
            {"account_code": "CAJA", "side": "CREDIT", "amount": "100.00"},
        ])
    assert e.value.code == "ACCOUNTING_COST_CENTER_NOT_FOUND"


def test_manual_non_postable_account_rejected(ctx):
    _acc(ctx["company"], "PADRE", ChartOfAccount.AccountType.EXPENSE, postable=False)
    with pytest.raises(AccountingPlusError) as e:
        _manual(ctx, [
            {"account_code": "PADRE", "side": "DEBIT", "amount": "100.00"},
            {"account_code": "CAJA", "side": "CREDIT", "amount": "100.00"},
        ])
    assert e.value.code == "ACCOUNTING_ACCOUNT_NOT_POSTABLE"


def test_manual_closed_period_rejected(ctx):
    from apps.kernels.accounting.models import FiscalPeriod
    FiscalPeriod.objects.update_or_create(
        company=ctx["company"], year=2025, month=5,
        defaults={"status": FiscalPeriod.Status.CLOSED},
    )
    with pytest.raises(AccountingPlusError) as e:
        _manual(ctx, [
            {"account_code": "GASTO", "side": "DEBIT", "amount": "100.00"},
            {"account_code": "CAJA", "side": "CREDIT", "amount": "100.00"},
        ], entry_date=date(2025, 5, 4))
    assert e.value.code == "ACCOUNTING_PERIOD_CLOSED"


def test_manual_requires_phase7(ctx):
    cfg = get_or_create_accounting_config(company=ctx["company"])
    cfg.phase7_enabled = False
    cfg.save(update_fields=["phase7_enabled"])
    with pytest.raises(AccountingPlusError) as e:
        _manual(ctx, [
            {"account_code": "GASTO", "side": "DEBIT", "amount": "100.00"},
            {"account_code": "CAJA", "side": "CREDIT", "amount": "100.00"},
        ])
    assert e.value.code == "ACCOUNTING_PHASE7_REQUIRED"
