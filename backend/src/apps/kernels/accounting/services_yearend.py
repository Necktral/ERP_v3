"""Cierre anual del ejercicio — Ola E.

Lleva las cuentas de resultado (REVENUE/EXPENSE) a 0 contra la cuenta de
resultados acumulados (`CompanyAccountingConfig.retained_earnings_account`)
mediante un asiento de cierre generado por el sistema (fecha 31-dic, mes 12), y
luego sella diciembre con `close_fiscal_period`. Reabrir reversa ese asiento.

Reusa la maquinaria existente: `_post_single_journal_draft`, `close_fiscal_period`,
`reopen_fiscal_period`, `reverse_journal_entry` y el `rule_set` de sistema.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, time
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .audit_helpers import write_accounting_audit_event
from .models import (
    ChartOfAccount,
    EconomicEvent,
    FiscalPeriod,
    JournalDraft,
    JournalEntry,
    JournalEntryLine,
    YearEndClosing,
)
from .phase7 import get_or_create_accounting_config
from .services import (
    AccountingConflictError,
    _post_single_journal_draft,
    close_fiscal_period,
    reopen_fiscal_period,
    reverse_journal_entry,
)
from .services_costcenters import (
    AccountingPlusError,
    AccountingPlusNotFound,
    _q2,
    _require_phase7,
    get_or_create_system_rule_set,
)

_RESULT_TYPES = (ChartOfAccount.AccountType.REVENUE, ChartOfAccount.AccountType.EXPENSE)


def _result_balances(*, company, fiscal_year: int) -> list[dict[str, Any]]:
    """Saldo (débito/crédito acumulado del año) por cuenta de resultado."""
    rows = (
        JournalEntryLine.objects.filter(
            journal_entry__company=company,
            journal_entry__is_posted=True,
            journal_entry__period__year=int(fiscal_year),
            account__account_type__in=_RESULT_TYPES,
        )
        .values("account__code", "account__name", "account__account_type")
        .annotate(debit=Sum("debit_base"), credit=Sum("credit_base"))
        .order_by("account__code")
    )
    out = []
    for r in rows:
        debit = _q2(r["debit"] or Decimal("0"))
        credit = _q2(r["credit"] or Decimal("0"))
        out.append({
            "code": r["account__code"],
            "name": r["account__name"],
            "type": r["account__account_type"],
            "debit": debit,
            "credit": credit,
            "net": _q2(debit - credit),  # >0 saldo deudor; <0 saldo acreedor
        })
    return out


def _months_status(*, company, fiscal_year: int) -> dict[int, str | None]:
    periods = {
        p.month: p.status
        for p in FiscalPeriod.objects.filter(company=company, year=int(fiscal_year))
    }
    return {m: periods.get(m) for m in range(1, 13)}


def get_year_end_status(*, company, fiscal_year: int) -> dict[str, Any]:
    closing = YearEndClosing.objects.filter(company=company, fiscal_year=int(fiscal_year)).first()
    months = _months_status(company=company, fiscal_year=fiscal_year)
    open_before_dec = [m for m in range(1, 12) if months.get(m) != FiscalPeriod.Status.CLOSED]
    balances = _result_balances(company=company, fiscal_year=fiscal_year)
    revenue = sum((b["credit"] - b["debit"] for b in balances if b["type"] == "REVENUE"), Decimal("0.00"))
    expense = sum((b["debit"] - b["credit"] for b in balances if b["type"] == "EXPENSE"), Decimal("0.00"))
    # Cerrado: el neto vive en el registro (los saldos en vivo ya están en 0). Abierto:
    # se proyecta de los saldos actuales.
    net_result = closing.net_result if closing is not None else _q2(revenue - expense)
    return {
        "fiscal_year": int(fiscal_year),
        "status": closing.status if closing else None,
        "net_result": str(_q2(net_result)),
        "revenue": str(_q2(revenue)),
        "expense": str(_q2(expense)),
        "months": {str(m): months.get(m) for m in range(1, 13)},
        "months_pending_close": open_before_dec,
        "december_open": months.get(12) == FiscalPeriod.Status.OPEN,
        "closing_entry_id": closing.closing_entry_id if closing else None,
        "manifest_hash": closing.manifest_hash if closing else "",
    }


def close_fiscal_year(*, company, fiscal_year: int, actor, force: bool = False) -> dict[str, Any]:
    fiscal_year = int(fiscal_year)
    _require_phase7(company)

    existing = YearEndClosing.objects.filter(company=company, fiscal_year=fiscal_year).first()
    if existing is not None and existing.status == YearEndClosing.Status.CLOSED:
        return get_year_end_status(company=company, fiscal_year=fiscal_year)

    cfg = get_or_create_accounting_config(company=company)
    if cfg.retained_earnings_account_id is None:
        raise AccountingPlusError("ACCOUNTING_RETAINED_EARNINGS_NOT_CONFIGURED")
    re_account = cfg.retained_earnings_account
    if re_account is None:
        raise AccountingPlusError("ACCOUNTING_RETAINED_EARNINGS_NOT_CONFIGURED")

    months = _months_status(company=company, fiscal_year=fiscal_year)
    if not force:
        for m in range(1, 12):
            if months.get(m) != FiscalPeriod.Status.CLOSED:
                raise AccountingPlusError("ACCOUNTING_YEAR_END_MONTHS_OPEN")
        if months.get(12) != FiscalPeriod.Status.OPEN:
            raise AccountingPlusError("ACCOUNTING_YEAR_END_DECEMBER_NOT_OPEN")
    # Asegurar que diciembre existe y está abierto para postear el asiento de cierre.
    dec, _ = FiscalPeriod.objects.get_or_create(
        company=company, year=fiscal_year, month=12, defaults={"status": FiscalPeriod.Status.OPEN}
    )
    if dec.status == FiscalPeriod.Status.CLOSED:
        raise AccountingPlusError("ACCOUNTING_YEAR_END_DECEMBER_NOT_OPEN")

    balances = _result_balances(company=company, fiscal_year=fiscal_year)
    closing_lines: list[dict[str, Any]] = []
    revenue_total = Decimal("0.00")
    expense_total = Decimal("0.00")
    sum_debit = Decimal("0.00")
    sum_credit = Decimal("0.00")
    for b in balances:
        if b["type"] == "REVENUE":
            revenue_total += _q2(b["credit"] - b["debit"])
        else:
            expense_total += _q2(b["debit"] - b["credit"])
        net = b["net"]
        if net == 0:
            continue
        if net > 0:  # saldo deudor → se acredita para llevar a 0
            closing_lines.append({"account": b["code"], "side": "CREDIT", "amount": str(net)})
            sum_credit += net
        else:  # saldo acreedor → se debita
            amt = _q2(-net)
            closing_lines.append({"account": b["code"], "side": "DEBIT", "amount": str(amt)})
            sum_debit += amt

    net_result = _q2(revenue_total - expense_total)

    closing_entry: JournalEntry | None = None
    if closing_lines:
        residual = _q2(sum_debit - sum_credit)
        if residual > 0:
            closing_lines.append({"account": re_account.code, "side": "CREDIT", "amount": str(residual)})
        elif residual < 0:
            closing_lines.append({"account": re_account.code, "side": "DEBIT", "amount": str(_q2(-residual))})
        # (residual == 0: no hace falta línea de RE; el cierre ya balancea.)

        total_debit = sum(_q2(line["amount"]) for line in closing_lines if line["side"] == "DEBIT")
        total_credit = sum(_q2(line["amount"]) for line in closing_lines if line["side"] == "CREDIT")
        if _q2(total_debit) != _q2(total_credit):
            raise AccountingConflictError("Asiento de cierre no balanceado.")

        occurred_at = timezone.make_aware(
            datetime.combine(datetime(fiscal_year, 12, 31).date(), time(23, 0)),
            timezone.get_current_timezone(),
        )
        rule_set = get_or_create_system_rule_set(company=company)
        manifest_hash = hashlib.sha256(
            json.dumps({"year": fiscal_year, "lines": closing_lines}, sort_keys=True).encode()
        ).hexdigest()

        with transaction.atomic():
            event = EconomicEvent.objects.create(
                source_module="ACCOUNTING",
                event_type="YearEndClosing",
                company=company,
                branch=None,
                occurred_at=occurred_at,
                contract_version="1.0",
                schema_version=1,
                correlation_id=f"year-end-{company.id}-{fiscal_year}",
                causation_id="",
                payload={
                    "source_module": "ACCOUNTING",
                    "event_type": "YearEndClosing",
                    "data": {"fiscal_year": fiscal_year, "net_result": str(net_result), "lines": closing_lines},
                    "scope": {"company_id": int(company.id), "branch_id": None},
                },
                input_manifest_hash=manifest_hash,
                close_run_id="",
            )
            draft = JournalDraft.objects.create(
                economic_event=event,
                rule_set=rule_set,
                state=JournalDraft.State.APPROVED_FOR_POSTING,
                contract_version="1.0",
                schema_version=1,
                close_run_id="",
                input_manifest_hash=manifest_hash,
                lines_json=closing_lines,
                total_debit=_q2(total_debit),
                total_credit=_q2(total_credit),
                generated_by=actor,
                approved_by=actor,
                approved_at=timezone.now(),
                validated_at=timezone.now(),
                metadata={"year_end": True, "fiscal_year": fiscal_year},
            )
            closing_entry = _post_single_journal_draft(draft=draft, actor_user=actor)
    else:
        manifest_hash = hashlib.sha256(
            json.dumps({"year": fiscal_year, "lines": []}, sort_keys=True).encode()
        ).hexdigest()

    # Sellar diciembre (asiento de cierre = del sistema → allow_same_poster).
    close_fiscal_period(
        company_id=int(company.id), year=fiscal_year, month=12,
        force=force, allow_same_poster=True, actor_user=actor,
    )

    with transaction.atomic():
        closing, _ = YearEndClosing.objects.update_or_create(
            company=company, fiscal_year=fiscal_year,
            defaults={
                "status": YearEndClosing.Status.CLOSED,
                "net_result": net_result,
                "closing_entry": closing_entry,
                "manifest_hash": manifest_hash,
                "closed_by": actor,
                "closed_at": timezone.now(),
                "reopened_by": None,
                "reopened_at": None,
                "reopen_reason": "",
            },
        )
        write_accounting_audit_event(
            actor_user=actor, company=company, branch=None,
            event_type="ACCOUNTING_YEAR_END_CLOSED",
            subject_type="YEAR_END_CLOSING", subject_id=str(closing.id),
            after_snapshot={"fiscal_year": fiscal_year, "net_result": str(net_result),
                            "closing_entry_id": closing_entry.id if closing_entry else None},
            metadata={"manifest_hash": manifest_hash, "forced": bool(force)},
        )
    return get_year_end_status(company=company, fiscal_year=fiscal_year)


def reopen_fiscal_year(*, company, fiscal_year: int, reason: str, actor, force: bool = False) -> dict[str, Any]:
    fiscal_year = int(fiscal_year)
    reason = str(reason or "").strip()
    if not reason:
        raise AccountingPlusError("ACCOUNTING_YEAR_END_REOPEN_REASON_REQUIRED")
    closing = YearEndClosing.objects.filter(company=company, fiscal_year=fiscal_year).first()
    if closing is None:
        raise AccountingPlusNotFound("ACCOUNTING_YEAR_END_NOT_FOUND")
    if closing.status == YearEndClosing.Status.REOPENED:
        return get_year_end_status(company=company, fiscal_year=fiscal_year)

    # Reabrir diciembre ANTES de reversar (la reversa exige período abierto).
    reopen_fiscal_period(
        company_id=int(company.id), year=fiscal_year, month=12,
        reason=reason, force=force, allow_same_closer=True, actor_user=actor,
    )
    if closing.closing_entry_id is not None:
        # La reversa debe caer en diciembre del ejercicio (donde vivió el cierre),
        # no en el período de hoy, para restaurar el P&L del año correcto.
        reverse_journal_entry(
            company_id=int(company.id), journal_entry_id=int(closing.closing_entry_id),
            reason=f"Reapertura de ejercicio {fiscal_year}: {reason}",
            reversal_date=datetime(fiscal_year, 12, 31).date(),
            allow_same_poster=True, actor_user=actor,
        )

    with transaction.atomic():
        closing.status = YearEndClosing.Status.REOPENED
        closing.reopened_by = actor
        closing.reopened_at = timezone.now()
        closing.reopen_reason = reason[:255]
        closing.save(update_fields=["status", "reopened_by", "reopened_at", "reopen_reason"])
        write_accounting_audit_event(
            actor_user=actor, company=company, branch=None,
            event_type="ACCOUNTING_YEAR_END_REOPENED",
            subject_type="YEAR_END_CLOSING", subject_id=str(closing.id),
            after_snapshot={"status": closing.status},
            metadata={"reason": reason[:120]},
        )
    return get_year_end_status(company=company, fiscal_year=fiscal_year)
