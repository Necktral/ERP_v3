"""Invariantes contables del cierre anual (caza de bugs de cómputo/regla).

Ataca, con números concretos:
- Todo asiento de cierre CUADRA (Σ débito_base == Σ crédito_base) a nivel de JournalEntry.
- Año con PÉRDIDA (gasto > ingreso): net_result < 0 y retained_earnings se DEBITA.
- Reabrir = REVERSA EXACTA: el saldo neto de TODAS las cuentas (no solo VENTA/RESULT)
  vuelve a su valor pre-cierre.
- Signo natural por account_type en el net_result reportado.

Reusa el estilo/fixtures de test_year_end.py.
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
from apps.kernels.accounting.services_costcenters import (
    create_cost_center,
    create_manual_journal_draft,
)
from apps.kernels.accounting.services_yearend import (
    close_fiscal_year,
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


def _close_months_1_11(company):
    for m in range(1, 12):
        FiscalPeriod.objects.update_or_create(
            company=company, year=YEAR, month=m, defaults={"status": FiscalPeriod.Status.CLOSED},
        )


def _net_by_account(company):
    """Saldo neto (débito - crédito) por código de cuenta, sobre asientos posteados del año."""
    net: dict[str, Decimal] = {}
    for line in JournalEntryLine.objects.filter(
        journal_entry__company=company, journal_entry__is_posted=True,
        journal_entry__period__year=YEAR,
    ).select_related("account"):
        code = line.account.code
        net[code] = net.get(code, Decimal("0.00")) + (line.debit_base - line.credit_base)
    return net


@pytest.mark.django_db
def test_closing_entry_balances_line_by_line():
    """El asiento de cierre debe cuadrar: Σ débito_base == Σ crédito_base."""
    company, branch = _company()
    maker, approver = _actor(), _actor()
    _acc(company, "VENTA", ChartOfAccount.AccountType.REVENUE)
    _acc(company, "GASTO", ChartOfAccount.AccountType.EXPENSE)
    _acc(company, "CAJA", ChartOfAccount.AccountType.ASSET)
    _post(company, branch, maker, approver, [
        {"account_code": "CAJA", "side": "DEBIT", "amount": "8000.00"},
        {"account_code": "VENTA", "side": "CREDIT", "amount": "8000.00"},
    ])
    _post(company, branch, maker, approver, [
        {"account_code": "GASTO", "side": "DEBIT", "amount": "3000.00"},
        {"account_code": "CAJA", "side": "CREDIT", "amount": "3000.00"},
    ])
    _close_months_1_11(company)
    status = close_fiscal_year(company=company, fiscal_year=YEAR, actor=maker)
    assert status["status"] == YearEndClosing.Status.CLOSED
    assert status["net_result"] == "5000.00"  # 8000 - 3000

    closing = YearEndClosing.objects.get(company=company, fiscal_year=YEAR)
    je = JournalEntry.objects.get(id=closing.closing_entry_id)
    lines = list(je.lines.all())
    total_d = sum((ln.debit_base for ln in lines), Decimal("0.00"))
    total_c = sum((ln.credit_base for ln in lines), Decimal("0.00"))
    assert total_d == total_c, f"Asiento de cierre descuadrado: D={total_d} C={total_c}"
    assert total_d > 0


@pytest.mark.django_db
def test_loss_year_debits_retained_earnings():
    """Año con PÉRDIDA: net_result negativo y retained_earnings se DEBITA (no acredita)."""
    company, branch = _company()
    maker, approver = _actor(), _actor()
    _acc(company, "VENTA", ChartOfAccount.AccountType.REVENUE)
    _acc(company, "GASTO", ChartOfAccount.AccountType.EXPENSE)
    _acc(company, "CAJA", ChartOfAccount.AccountType.ASSET)
    # Ingreso 2000, gasto 5000 -> pérdida de 3000.
    _post(company, branch, maker, approver, [
        {"account_code": "CAJA", "side": "DEBIT", "amount": "2000.00"},
        {"account_code": "VENTA", "side": "CREDIT", "amount": "2000.00"},
    ])
    _post(company, branch, maker, approver, [
        {"account_code": "GASTO", "side": "DEBIT", "amount": "5000.00"},
        {"account_code": "CAJA", "side": "CREDIT", "amount": "5000.00"},
    ])
    _close_months_1_11(company)
    status = close_fiscal_year(company=company, fiscal_year=YEAR, actor=maker)
    assert status["net_result"] == "-3000.00"

    net = _net_by_account(company)
    # RESULT (EQUITY) recibió la pérdida como saldo DEUDOR neto = +3000 (debit - credit).
    assert net.get("RESULT") == Decimal("3000.00"), f"RESULT debe quedar deudor 3000, got {net.get('RESULT')}"
    # REVENUE y EXPENSE quedan en cero.
    assert net.get("VENTA") == Decimal("0.00")
    assert net.get("GASTO") == Decimal("0.00")


@pytest.mark.django_db
def test_reopen_is_exact_reverse_of_close_all_accounts():
    """Reabrir el ejercicio debe restaurar el saldo neto de TODAS las cuentas a su
    valor pre-cierre (reversa exacta), no solo de unas pocas."""
    company, branch = _company()
    maker, approver = _actor(), _actor()
    _acc(company, "VENTA", ChartOfAccount.AccountType.REVENUE)
    _acc(company, "OTROING", ChartOfAccount.AccountType.REVENUE)
    _acc(company, "GASTO", ChartOfAccount.AccountType.EXPENSE)
    _acc(company, "GASTO2", ChartOfAccount.AccountType.EXPENSE)
    _acc(company, "CAJA", ChartOfAccount.AccountType.ASSET)
    _post(company, branch, maker, approver, [
        {"account_code": "CAJA", "side": "DEBIT", "amount": "7000.00"},
        {"account_code": "VENTA", "side": "CREDIT", "amount": "4000.00"},
        {"account_code": "OTROING", "side": "CREDIT", "amount": "3000.00"},
    ])
    _post(company, branch, maker, approver, [
        {"account_code": "GASTO", "side": "DEBIT", "amount": "1500.00"},
        {"account_code": "GASTO2", "side": "DEBIT", "amount": "2500.00"},
        {"account_code": "CAJA", "side": "CREDIT", "amount": "4000.00"},
    ])

    pre = _net_by_account(company)
    _close_months_1_11(company)
    close_fiscal_year(company=company, fiscal_year=YEAR, actor=maker)
    reopen_fiscal_year(company=company, fiscal_year=YEAR, reason="Ajuste", actor=maker)

    post = _net_by_account(company)
    # Reversa exacta: cada cuenta de resultado y RESULT vuelve a su saldo pre-cierre.
    for code in ("VENTA", "OTROING", "GASTO", "GASTO2"):
        assert post.get(code) == pre.get(code), (
            f"Cuenta {code}: pre={pre.get(code)} post-reopen={post.get(code)} (no es reversa exacta)."
        )
    # RESULT vuelve a 0 (no tenía saldo antes del cierre).
    assert post.get("RESULT", Decimal("0.00")) == Decimal("0.00")
    dec = FiscalPeriod.objects.get(company=company, year=YEAR, month=12)
    assert dec.status == FiscalPeriod.Status.OPEN


@pytest.mark.django_db
def test_close_is_idempotent():
    """Cerrar dos veces el mismo ejercicio NO duplica el asiento de cierre ni cambia
    el net_result; la segunda llamada devuelve el estado ya cerrado."""
    company, branch = _company()
    maker, approver = _actor(), _actor()
    _acc(company, "VENTA", ChartOfAccount.AccountType.REVENUE)
    _acc(company, "GASTO", ChartOfAccount.AccountType.EXPENSE)
    _acc(company, "CAJA", ChartOfAccount.AccountType.ASSET)
    _post(company, branch, maker, approver, [
        {"account_code": "CAJA", "side": "DEBIT", "amount": "9000.00"},
        {"account_code": "VENTA", "side": "CREDIT", "amount": "9000.00"},
    ])
    _post(company, branch, maker, approver, [
        {"account_code": "GASTO", "side": "DEBIT", "amount": "4000.00"},
        {"account_code": "CAJA", "side": "CREDIT", "amount": "4000.00"},
    ])
    _close_months_1_11(company)
    s1 = close_fiscal_year(company=company, fiscal_year=YEAR, actor=maker)
    closings_after_first = YearEndClosing.objects.filter(company=company, fiscal_year=YEAR).count()
    closing1 = YearEndClosing.objects.get(company=company, fiscal_year=YEAR)
    entry_id_1 = closing1.closing_entry_id

    s2 = close_fiscal_year(company=company, fiscal_year=YEAR, actor=maker)
    closings_after_second = YearEndClosing.objects.filter(company=company, fiscal_year=YEAR).count()
    closing2 = YearEndClosing.objects.get(company=company, fiscal_year=YEAR)

    assert s1["net_result"] == s2["net_result"] == "5000.00"
    assert closings_after_first == closings_after_second == 1
    assert closing2.closing_entry_id == entry_id_1, "El re-cierre no debe crear un asiento nuevo."
    # No se duplicaron asientos de cierre posteados: el draft de cierre lleva metadata
    # {"year_end": True}; debe existir uno solo posteado para el ejercicio.
    n_closings = JournalEntry.objects.filter(
        company=company, is_posted=True, draft__metadata__year_end=True,
    ).count()
    assert n_closings == 1


@pytest.mark.django_db
def test_reopen_then_reclose_is_stable():
    """Reabrir y volver a cerrar deja el mismo net_result y el P&L estable."""
    company, branch = _company()
    maker, approver = _actor(), _actor()
    _acc(company, "VENTA", ChartOfAccount.AccountType.REVENUE)
    _acc(company, "GASTO", ChartOfAccount.AccountType.EXPENSE)
    _acc(company, "CAJA", ChartOfAccount.AccountType.ASSET)
    _post(company, branch, maker, approver, [
        {"account_code": "CAJA", "side": "DEBIT", "amount": "10000.00"},
        {"account_code": "VENTA", "side": "CREDIT", "amount": "10000.00"},
    ])
    _post(company, branch, maker, approver, [
        {"account_code": "GASTO", "side": "DEBIT", "amount": "6000.00"},
        {"account_code": "CAJA", "side": "CREDIT", "amount": "6000.00"},
    ])
    _close_months_1_11(company)
    first = close_fiscal_year(company=company, fiscal_year=YEAR, actor=maker)
    assert first["net_result"] == "4000.00"

    reopen_fiscal_year(company=company, fiscal_year=YEAR, reason="ajuste", actor=maker)
    # Tras reabrir, las cuentas de resultado vuelven a tener su saldo -> re-cerrar da igual neto.
    second = close_fiscal_year(company=company, fiscal_year=YEAR, actor=maker)
    assert second["net_result"] == "4000.00", (
        f"Re-cierre tras reapertura cambió el net_result: {second['net_result']} != 4000.00"
    )
    # RESULT queda acreedor 4000 (utilidad) tras el segundo cierre.
    net = _net_by_account(company)
    assert net.get("RESULT") == Decimal("-4000.00"), f"RESULT esperado -4000, got {net.get('RESULT')}"
    assert net.get("VENTA") == Decimal("0.00")
    assert net.get("GASTO") == Decimal("0.00")


@pytest.mark.django_db
def test_closing_balances_with_cost_centers():
    """El cierre debe cuadrar aunque las cuentas de resultado tengan centro de costo:
    el asiento de cierre agrega por cuenta y balancea Σ débito == Σ crédito."""
    company, branch = _company()
    maker, approver = _actor(), _actor()
    cc = create_cost_center(company=company, actor=maker, code="CC1", name="Beneficio")
    _acc(company, "VENTA", ChartOfAccount.AccountType.REVENUE)
    _acc(company, "GASTO", ChartOfAccount.AccountType.EXPENSE)
    _acc(company, "CAJA", ChartOfAccount.AccountType.ASSET)
    # Operaciones con centro de costo en las cuentas de resultado.
    create_manual_journal_draft(
        company=company, branch=branch, actor=maker, entry_date=date(YEAR, 12, 15), memo="venta",
        lines=[
            {"account_code": "CAJA", "side": "DEBIT", "amount": "12000.00"},
            {"account_code": "VENTA", "side": "CREDIT", "amount": "12000.00", "cost_center_id": cc.id},
        ],
    )
    create_manual_journal_draft(
        company=company, branch=branch, actor=maker, entry_date=date(YEAR, 12, 15), memo="gasto",
        lines=[
            {"account_code": "GASTO", "side": "DEBIT", "amount": "5000.00", "cost_center_id": cc.id},
            {"account_code": "CAJA", "side": "CREDIT", "amount": "5000.00"},
        ],
    )
    approve_journal_drafts(company_id=company.id, actor_user=approver)
    post_journal_drafts(company_id=company.id, require_approved=True, actor_user=maker)

    _close_months_1_11(company)
    status = close_fiscal_year(company=company, fiscal_year=YEAR, actor=maker)
    assert status["net_result"] == "7000.00"  # 12000 - 5000

    closing = YearEndClosing.objects.get(company=company, fiscal_year=YEAR)
    je = JournalEntry.objects.get(id=closing.closing_entry_id)
    lines = list(je.lines.all())
    total_d = sum((ln.debit_base for ln in lines), Decimal("0.00"))
    total_c = sum((ln.credit_base for ln in lines), Decimal("0.00"))
    assert total_d == total_c, f"Cierre con cost center descuadrado: D={total_d} C={total_c}"
    # Cuentas de resultado quedan en cero.
    net = _net_by_account(company)
    assert net.get("VENTA") == Decimal("0.00")
    assert net.get("GASTO") == Decimal("0.00")


@pytest.mark.django_db
def test_closing_company_a_does_not_touch_company_b():
    """Multi-empresa: cerrar el ejercicio de la empresa A no toca el P&L ni el
    estado de cierre de la empresa B (mismas cuentas, mismo año)."""
    company_a, branch_a = _company()
    company_b, branch_b = _company()
    maker, approver = _actor(), _actor()
    for co, br in ((company_a, branch_a), (company_b, branch_b)):
        _acc(co, "VENTA", ChartOfAccount.AccountType.REVENUE)
        _acc(co, "GASTO", ChartOfAccount.AccountType.EXPENSE)
        _acc(co, "CAJA", ChartOfAccount.AccountType.ASSET)
        _post(co, br, maker, approver, [
            {"account_code": "CAJA", "side": "DEBIT", "amount": "8000.00"},
            {"account_code": "VENTA", "side": "CREDIT", "amount": "8000.00"},
        ])
        _post(co, br, maker, approver, [
            {"account_code": "GASTO", "side": "DEBIT", "amount": "3000.00"},
            {"account_code": "CAJA", "side": "CREDIT", "amount": "3000.00"},
        ])

    pre_b = _net_by_account(company_b)
    _close_months_1_11(company_a)
    close_fiscal_year(company=company_a, fiscal_year=YEAR, actor=maker)

    # B no fue cerrada: sin registro de cierre y P&L intacto.
    assert not YearEndClosing.objects.filter(company=company_b, fiscal_year=YEAR).exists()
    post_b = _net_by_account(company_b)
    for code in ("VENTA", "GASTO", "CAJA"):
        assert post_b.get(code) == pre_b.get(code), (
            f"Fuga multi-empresa: cuenta {code} de B cambió al cerrar A "
            f"(pre={pre_b.get(code)} post={post_b.get(code)})."
        )
    # Diciembre de B sigue abierto (o inexistente), no fue sellado por el cierre de A.
    dec_b = FiscalPeriod.objects.filter(company=company_b, year=YEAR, month=12).first()
    assert dec_b is None or dec_b.status == FiscalPeriod.Status.OPEN
