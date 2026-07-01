"""Tests Ola E: presupuestos mensuales + presupuesto-vs-real.

Lo REAL se agrega de JournalEntryLine (postings manuales) por cuenta+centro, con
signo natural por tipo de cuenta; el presupuesto suma los meses del rango.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.accounting.models import Budget, ChartOfAccount
from apps.kernels.accounting.phase7 import get_or_create_accounting_config
from apps.kernels.accounting.services import approve_journal_drafts, post_journal_drafts
from apps.kernels.accounting.services_budgets import (
    AccountingPlusError,
    approve_budget,
    budget_vs_actual,
    create_budget,
    upsert_budget_lines,
)
from apps.kernels.accounting.services_costcenters import create_cost_center, create_manual_journal_draft
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


def _acc(company, code, atype):
    return ChartOfAccount.objects.create(company=company, code=code, name=code, account_type=atype)


def _post_manual(company, branch, maker, approver, lines, entry_date):
    create_manual_journal_draft(
        company=company, branch=branch, actor=maker, entry_date=entry_date, memo="x", lines=lines,
    )
    approve_journal_drafts(company_id=company.id, actor_user=approver)
    post_journal_drafts(company_id=company.id, require_approved=True, actor_user=maker)


@pytest.fixture
def ctx(db):
    company, branch = _company()
    maker = _actor()
    approver = _actor()
    _acc(company, "GASTO", ChartOfAccount.AccountType.EXPENSE)
    _acc(company, "CAJA", ChartOfAccount.AccountType.ASSET)
    cc = create_cost_center(company=company, actor=maker, code="ADM", name="Administración")
    return dict(company=company, branch=branch, maker=maker, approver=approver, cc=cc)


def test_budget_create_lines_and_sod_approve(ctx):
    budget = create_budget(company=ctx["company"], actor=ctx["maker"], fiscal_year=2026, name="Operativo")
    upsert_budget_lines(
        company=ctx["company"], actor=ctx["maker"], budget_id=budget.id,
        lines=[{
            "account_code": "GASTO", "cost_center_id": ctx["cc"].id,
            "monthly": {str(m): "1000.00" for m in range(1, 13)},
        }],
    )
    budget.refresh_from_db()
    line = budget.lines.get()
    assert line.annual_amount == Decimal("12000.00")

    # SoD: el creador no aprueba su propio presupuesto.
    with pytest.raises(AccountingPlusError) as e:
        approve_budget(company=ctx["company"], actor=ctx["maker"], budget_id=budget.id)
    assert e.value.code == "ACCOUNTING_BUDGET_SOD_SELF_APPROVAL"

    approve_budget(company=ctx["company"], actor=ctx["approver"], budget_id=budget.id)
    budget.refresh_from_db()
    assert budget.status == Budget.Status.APPROVED

    # Aprobado: ya no se editan líneas.
    with pytest.raises(AccountingPlusError) as e:
        upsert_budget_lines(company=ctx["company"], actor=ctx["maker"], budget_id=budget.id, lines=[])
    assert e.value.code == "ACCOUNTING_BUDGET_NOT_DRAFT"


def test_budget_vs_actual_math_and_cost_center_filter(ctx):
    budget = create_budget(company=ctx["company"], actor=ctx["maker"], fiscal_year=2026, name="Op")
    upsert_budget_lines(
        company=ctx["company"], actor=ctx["maker"], budget_id=budget.id,
        lines=[{
            "account_code": "GASTO", "cost_center_id": ctx["cc"].id,
            "monthly": {**{str(m): "1000.00" for m in range(1, 13)}},
        }],
    )
    # Gasto real de 1200 imputado al centro ADM en marzo 2026.
    _post_manual(
        ctx["company"], ctx["branch"], ctx["maker"], ctx["approver"],
        lines=[
            {"account_code": "GASTO", "side": "DEBIT", "amount": "1200.00", "cost_center_id": ctx["cc"].id},
            {"account_code": "CAJA", "side": "CREDIT", "amount": "1200.00"},
        ],
        entry_date=date(2026, 3, 9),
    )

    # Solo marzo: presupuesto 1000 vs real 1200 → variación -200.
    res = budget_vs_actual(company=ctx["company"], budget_id=budget.id, month_from=3, month_to=3)
    row = next(r for r in res["rows"] if r["account_code"] == "GASTO")
    assert row["budget"] == "1000.00"
    assert row["actual"] == "1200.00"
    assert row["variance"] == "-200.00"
    assert res["total_variance"] == "-200.00"

    # Año completo: presupuesto 12000 vs real 1200 → variación 10800.
    res_year = budget_vs_actual(company=ctx["company"], budget_id=budget.id)
    assert res_year["total_budget"] == "12000.00"
    assert res_year["total_actual"] == "1200.00"

    # Filtro por OTRO centro de costo → sin real (y sin presupuesto de esa línea).
    other_cc = create_cost_center(company=ctx["company"], actor=ctx["maker"], code="PROD", name="Prod")
    res_other = budget_vs_actual(company=ctx["company"], budget_id=budget.id, cost_center_id=other_cc.id)
    assert res_other["total_actual"] == "0.00" and res_other["total_budget"] == "0.00"


def test_budget_duplicate_name_rejected(ctx):
    create_budget(company=ctx["company"], actor=ctx["maker"], fiscal_year=2026, name="Único")
    with pytest.raises(AccountingPlusError) as e:
        create_budget(company=ctx["company"], actor=ctx["maker"], fiscal_year=2026, name="Único")
    assert e.value.code == "ACCOUNTING_BUDGET_DUPLICATE"


def test_budget_approve_empty_rejected(ctx):
    budget = create_budget(company=ctx["company"], actor=ctx["maker"], fiscal_year=2026, name="Vacío")
    with pytest.raises(AccountingPlusError) as e:
        approve_budget(company=ctx["company"], actor=ctx["approver"], budget_id=budget.id)
    assert e.value.code == "ACCOUNTING_BUDGET_EMPTY"
