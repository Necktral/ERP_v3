"""Bordes de negocio del cierre/reapertura anual (finder de bugs).

Olas previas cubren el cierre, la idempotencia de doble cierre y reabrir-restaura.
Aquí se atacan los BORDES no cubiertos:
  - Reabrir y RE-CERRAR (segundo cierre tras una reapertura) debe volver a llevar
    REVENUE/EXPENSE a 0 y dejar retained_earnings con la utilidad correcta UNA vez.
  - El asiento de cierre debe seguir cuadrando (Σdébitos = Σcréditos).
  - El net_result reportado debe ser estable entre cierres.
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
    JournalEntry,
    JournalEntryLine,
    YearEndClosing,
)
from apps.kernels.accounting.phase7 import get_or_create_accounting_config
from apps.kernels.accounting.services import approve_journal_drafts, post_journal_drafts
from apps.kernels.accounting.services_costcenters import create_manual_journal_draft
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


def _company():
    s = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H_{s}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name=f"C_{s}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, name=f"B_{s}", parent=company)
    cfg = get_or_create_accounting_config(company=company)
    cfg.phase7_enabled = True
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


def _assert_all_entries_balanced(company):
    """Invariante de partida doble: cada JournalEntry posteado cuadra."""
    for je in JournalEntry.objects.filter(company=company, is_posted=True):
        d = sum((ln.debit_base for ln in je.lines.all()), Decimal("0.00"))
        c = sum((ln.credit_base for ln in je.lines.all()), Decimal("0.00"))
        assert d == c, f"JournalEntry {je.id} descuadrado: D={d} C={c}"


def test_reabrir_y_recerrar_deja_pnl_en_cero_y_re_una_sola_vez(ctx):
    """Cerrar → reabrir → re-cerrar: el segundo cierre debe volver a anular el P&L
    y dejar retained_earnings con la utilidad UNA sola vez (2000), no acumulada."""
    company = ctx["company"]
    _close_months_1_11(company)

    close_fiscal_year(company=company, fiscal_year=YEAR, actor=ctx["maker"])
    reopen_fiscal_year(company=company, fiscal_year=YEAR, reason="Ajuste", actor=ctx["maker"])

    # Re-cerrar el ejercicio reabierto.
    status2 = close_fiscal_year(company=company, fiscal_year=YEAR, actor=ctx["maker"])
    assert status2["status"] == YearEndClosing.Status.CLOSED
    assert status2["net_result"] == "2000.00", f"net_result inesperado: {status2['net_result']}"

    # REVENUE y EXPENSE deben quedar en 0 otra vez.
    rd, rc = _result_net(company, "VENTA")
    assert rd == rc, f"VENTA no quedó en 0 tras re-cerrar: D={rd} C={rc}"
    gd, gc = _result_net(company, "GASTO")
    assert gd == gc, f"GASTO no quedó en 0 tras re-cerrar: D={gd} C={gc}"

    # Resultados acumulados (EQUITY) debe tener la utilidad UNA sola vez (2000),
    # NO duplicada/acumulada por los dos cierres.
    ed, ec = _result_net(company, "RESULT")
    assert (ec - ed) == Decimal("2000.00"), (
        f"BUG: retained_earnings acumuló mal tras reabrir+re-cerrar: neto={ec - ed} (esperado 2000.00)"
    )

    # Todos los asientos (incluidos cierre, reversa y re-cierre) cuadran.
    _assert_all_entries_balanced(company)

    # Solo debe existir UN registro de cierre para el año.
    assert YearEndClosing.objects.filter(company=company, fiscal_year=YEAR).count() == 1

    # Diciembre cerrado de nuevo.
    dec = FiscalPeriod.objects.get(company=company, year=YEAR, month=12)
    assert dec.status == FiscalPeriod.Status.CLOSED


def test_status_neto_estable_entre_cierre_y_reapertura(ctx):
    """get_year_end_status debe reportar el mismo net_result (2000) en cada fase."""
    company = ctx["company"]
    _close_months_1_11(company)

    s_open = get_year_end_status(company=company, fiscal_year=YEAR)
    assert s_open["net_result"] == "2000.00"

    close_fiscal_year(company=company, fiscal_year=YEAR, actor=ctx["maker"])
    s_closed = get_year_end_status(company=company, fiscal_year=YEAR)
    assert s_closed["net_result"] == "2000.00", f"cerrado: {s_closed['net_result']}"

    reopen_fiscal_year(company=company, fiscal_year=YEAR, reason="x", actor=ctx["maker"])
    s_reopen = get_year_end_status(company=company, fiscal_year=YEAR)
    assert s_reopen["net_result"] == "2000.00", (
        f"BUG: net_result cambió tras reabrir: {s_reopen['net_result']} (esperado 2000.00)"
    )
