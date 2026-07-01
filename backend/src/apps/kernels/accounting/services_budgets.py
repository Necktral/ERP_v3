"""Presupuestos mensuales + presupuesto-vs-real — Ola E.

Un presupuesto anual por empresa; cada línea es (cuenta, centro de costo) con 12
montos mensuales. El reporte presupuesto-vs-real compara, por rango de meses, lo
presupuestado contra lo REAL agregado de `JournalEntryLine` (requiere phase7), con
el signo natural según el tipo de cuenta.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .audit_helpers import write_accounting_audit_event
from .models import Budget, BudgetLine, ChartOfAccount, CostCenter, JournalEntryLine
from .services_costcenters import AccountingPlusError, AccountingPlusNotFound, _q2, _require_phase7

# Signo natural del saldo por tipo de cuenta: + cuando aumenta su naturaleza.
_NATURAL_DEBIT = {"ASSET", "EXPENSE"}


def _natural_amount(account_type: str, debit: Decimal, credit: Decimal) -> Decimal:
    if account_type in _NATURAL_DEBIT:
        return _q2(debit - credit)
    return _q2(credit - debit)


def _months_in_range(month_from: int, month_to: int) -> list[int]:
    a = max(1, min(12, int(month_from)))
    b = max(1, min(12, int(month_to)))
    if b < a:
        a, b = b, a
    return list(range(a, b + 1))


# --------------------------------------------------------------- CRUD presupuesto

def budget_payload(budget: Budget, *, with_lines: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": budget.id,
        "fiscal_year": budget.fiscal_year,
        "name": budget.name,
        "currency": budget.currency,
        "status": budget.status,
        "created_at": budget.created_at.isoformat(),
        "approved_at": budget.approved_at.isoformat() if budget.approved_at else None,
    }
    if with_lines:
        data["lines"] = [
            {
                "id": ln.id,
                "account_code": ln.account.code,
                "account_name": ln.account.name,
                "cost_center_id": ln.cost_center_id,
                "cost_center_code": ln.cost_center.code if ln.cost_center is not None else None,
                "monthly": ln.monthly_json,
                "annual_amount": str(ln.annual_amount),
            }
            for ln in budget.lines.select_related("account", "cost_center").order_by("account__code")
        ]
    return data


def list_budgets(*, company, fiscal_year: int | None = None) -> list[dict[str, Any]]:
    qs = Budget.objects.filter(company=company)
    if fiscal_year is not None:
        qs = qs.filter(fiscal_year=int(fiscal_year))
    return [budget_payload(b) for b in qs.order_by("-fiscal_year", "name")]


def get_budget(*, company, budget_id: int) -> dict[str, Any]:
    budget = Budget.objects.filter(company=company, id=budget_id).first()
    if budget is None:
        raise AccountingPlusNotFound("ACCOUNTING_BUDGET_NOT_FOUND")
    return budget_payload(budget, with_lines=True)


def create_budget(*, company, actor, fiscal_year: int, name: str, currency: str = "NIO") -> Budget:
    name = (name or "").strip()
    if not name:
        raise AccountingPlusError("ACCOUNTING_BUDGET_INVALID")
    if Budget.objects.filter(company=company, fiscal_year=int(fiscal_year), name=name).exists():
        raise AccountingPlusError("ACCOUNTING_BUDGET_DUPLICATE")
    budget = Budget.objects.create(
        company=company, fiscal_year=int(fiscal_year), name=name,
        currency=(currency or "NIO"), created_by=actor,
    )
    write_accounting_audit_event(
        actor_user=actor, company=company, branch=None,
        event_type="ACCOUNTING_BUDGET_CREATED", subject_type="BUDGET", subject_id=str(budget.id),
        after_snapshot={"fiscal_year": budget.fiscal_year, "name": budget.name},
    )
    return budget


def upsert_budget_lines(*, company, actor, budget_id: int, lines: list[dict]) -> Budget:
    """Reemplaza las líneas del presupuesto (solo en DRAFT)."""
    budget = Budget.objects.filter(company=company, id=budget_id).first()
    if budget is None:
        raise AccountingPlusNotFound("ACCOUNTING_BUDGET_NOT_FOUND")
    if budget.status != Budget.Status.DRAFT:
        raise AccountingPlusError("ACCOUNTING_BUDGET_NOT_DRAFT")

    codes = {str(ln.get("account_code") or "").strip().upper() for ln in lines}
    codes.discard("")
    accounts = {a.code: a for a in ChartOfAccount.objects.filter(company=company, code__in=codes)}
    cc_ids = {int(ln["cost_center_id"]) for ln in lines if ln.get("cost_center_id") not in (None, "")}
    cost_centers = {
        cc.id: cc for cc in CostCenter.objects.filter(company=company, id__in=cc_ids)
    } if cc_ids else {}

    new_lines: list[BudgetLine] = []
    seen: set[tuple[str, int | None]] = set()
    for ln in lines:
        code = str(ln.get("account_code") or "").strip().upper()
        account = accounts.get(code)
        if account is None:
            raise AccountingPlusError("ACCOUNTING_ACCOUNT_NOT_FOUND")
        cc_raw = ln.get("cost_center_id")
        cc_id = None
        if cc_raw not in (None, ""):
            cc_id = int(str(cc_raw))
            if cc_id not in cost_centers:
                raise AccountingPlusError("ACCOUNTING_COST_CENTER_NOT_FOUND")
        key = (code, cc_id)
        if key in seen:
            raise AccountingPlusError("ACCOUNTING_BUDGET_LINE_DUPLICATE")
        seen.add(key)
        monthly_raw = ln.get("monthly") or {}
        monthly: dict[str, str] = {}
        annual = Decimal("0.00")
        for m in range(1, 13):
            val = monthly_raw.get(str(m)) or monthly_raw.get(m) or "0"
            try:
                amt = _q2(val)
            except AccountingPlusError:
                raise AccountingPlusError("ACCOUNTING_BUDGET_AMOUNT_INVALID")
            monthly[str(m)] = str(amt)
            annual += amt
        new_lines.append(BudgetLine(
            budget=budget, account=account,
            cost_center=cost_centers.get(cc_id) if cc_id else None,
            monthly_json=monthly, annual_amount=_q2(annual),
        ))

    with transaction.atomic():
        budget.lines.all().delete()
        BudgetLine.objects.bulk_create(new_lines)
    return budget


def approve_budget(*, company, actor, budget_id: int, allow_same_creator: bool = False) -> Budget:
    budget = Budget.objects.filter(company=company, id=budget_id).first()
    if budget is None:
        raise AccountingPlusNotFound("ACCOUNTING_BUDGET_NOT_FOUND")
    if budget.status != Budget.Status.DRAFT:
        raise AccountingPlusError("ACCOUNTING_BUDGET_NOT_DRAFT")
    if not budget.lines.exists():
        raise AccountingPlusError("ACCOUNTING_BUDGET_EMPTY")
    if (
        actor is not None and budget.created_by_id is not None
        and int(budget.created_by_id) == int(actor.id) and not allow_same_creator
    ):
        raise AccountingPlusError("ACCOUNTING_BUDGET_SOD_SELF_APPROVAL")
    budget.status = Budget.Status.APPROVED
    budget.approved_by = actor
    budget.approved_at = timezone.now()
    budget.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    write_accounting_audit_event(
        actor_user=actor, company=company, branch=None,
        event_type="ACCOUNTING_BUDGET_APPROVED", subject_type="BUDGET", subject_id=str(budget.id),
        after_snapshot={"status": budget.status},
    )
    return budget


def archive_budget(*, company, actor, budget_id: int) -> Budget:
    budget = Budget.objects.filter(company=company, id=budget_id).first()
    if budget is None:
        raise AccountingPlusNotFound("ACCOUNTING_BUDGET_NOT_FOUND")
    budget.status = Budget.Status.ARCHIVED
    budget.save(update_fields=["status", "updated_at"])
    return budget


# --------------------------------------------------------------- presupuesto vs real

def budget_vs_actual(
    *,
    company,
    budget_id: int,
    month_from: int = 1,
    month_to: int = 12,
    cost_center_id: int | None = None,
) -> dict[str, Any]:
    _require_phase7(company)
    budget = Budget.objects.filter(company=company, id=budget_id).first()
    if budget is None:
        raise AccountingPlusNotFound("ACCOUNTING_BUDGET_NOT_FOUND")
    months = _months_in_range(month_from, month_to)

    # Presupuesto por (cuenta, centro) en el rango.
    budget_map: dict[tuple[str, int | None], dict[str, Any]] = {}
    line_qs = budget.lines.select_related("account", "cost_center")
    if cost_center_id is not None:
        line_qs = line_qs.filter(cost_center_id=int(cost_center_id))
    for ln in line_qs:
        amt = Decimal("0.00")
        for m in months:
            amt += _q2(ln.monthly_json.get(str(m), "0"))
        key = (ln.account.code, ln.cost_center_id)
        budget_map[key] = {
            "account_code": ln.account.code,
            "account_name": ln.account.name,
            "account_type": ln.account.account_type,
            "cost_center_id": ln.cost_center_id,
            "cost_center_code": ln.cost_center.code if ln.cost_center is not None else None,
            "budget": _q2(amt),
        }

    # Real agregado de JournalEntryLine en el año/rango. El presupuesto-vs-real es
    # una herramienta de P&L: se consideran cuentas de RESULTADO (REVENUE/EXPENSE)
    # más cualquier cuenta presupuestada (por si se presupuesta una de balance);
    # las demás (caja, bancos…) no ensucian los totales.
    from django.db.models import Q

    budgeted_codes = {code for (code, _cc) in budget_map}
    actual_qs = JournalEntryLine.objects.filter(
        journal_entry__company=company,
        journal_entry__is_posted=True,
        journal_entry__period__year=int(budget.fiscal_year),
        journal_entry__period__month__gte=months[0],
        journal_entry__period__month__lte=months[-1],
    ).filter(
        Q(account__account_type__in=["REVENUE", "EXPENSE"])
        | Q(account__code__in=budgeted_codes)
    )
    if cost_center_id is not None:
        actual_qs = actual_qs.filter(cost_center_id=int(cost_center_id))
    actual_rows = (
        actual_qs.values(
            "account__code", "account__name", "account__account_type", "cost_center_id", "cost_center__code"
        ).annotate(debit=Sum("debit_base"), credit=Sum("credit_base"))
    )
    actual_map: dict[tuple[str, int | None], dict[str, Any]] = {}
    for r in actual_rows:
        key = (r["account__code"], r["cost_center_id"])
        actual_map[key] = {
            "account_code": r["account__code"],
            "account_name": r["account__name"],
            "account_type": r["account__account_type"],
            "cost_center_id": r["cost_center_id"],
            "cost_center_code": r["cost_center__code"],
            "actual": _natural_amount(r["account__account_type"], r["debit"] or Decimal("0"), r["credit"] or Decimal("0")),
        }

    rows: list[dict[str, Any]] = []
    total_budget = Decimal("0.00")
    total_actual = Decimal("0.00")
    for key in sorted(set(budget_map) | set(actual_map), key=lambda k: (k[0], k[1] or 0)):
        b = budget_map.get(key, {})
        a = actual_map.get(key, {})
        meta = b or a
        budget_amt = _q2(b.get("budget", Decimal("0.00")))
        actual_amt = _q2(a.get("actual", Decimal("0.00")))
        variance = _q2(budget_amt - actual_amt)
        variance_pct = (
            str(_q2((variance / budget_amt) * Decimal("100"))) if budget_amt != 0 else None
        )
        total_budget += budget_amt
        total_actual += actual_amt
        rows.append({
            "account_code": meta["account_code"],
            "account_name": meta["account_name"],
            "account_type": meta["account_type"],
            "cost_center_id": meta["cost_center_id"],
            "cost_center_code": meta["cost_center_code"],
            "budget": str(budget_amt),
            "actual": str(actual_amt),
            "variance": str(variance),
            "variance_pct": variance_pct,
        })

    return {
        "budget_id": budget.id,
        "fiscal_year": budget.fiscal_year,
        "name": budget.name,
        "month_from": months[0],
        "month_to": months[-1],
        "cost_center_id": cost_center_id,
        "rows": rows,
        "total_budget": str(_q2(total_budget)),
        "total_actual": str(_q2(total_actual)),
        "total_variance": str(_q2(total_budget - total_actual)),
    }
