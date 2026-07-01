"""Centros de costo + asientos manuales — Ola E (Contabilidad plus).

Centros de costo: catálogo por empresa (dimensión analítica) que se imputa en
líneas de asientos manuales y de cierre.

Asientos manuales: el sistema es event-sourced (los asientos nacen de eventos
operacionales vía PostingRuleSet). Esta es la PRIMERA vía para registrar asientos
manuales/de ajuste (reclasificaciones, provisiones, depreciación): se compone la
maquinaria existente sin reinventarla:
- `EconomicEvent("ACCOUNTING","ManualJournal")` + `JournalDraft` (state VALIDATED)
  sobre un `PostingRuleSet` de sistema (SYSTEM_MANUAL), con cost_center_id en
  cada línea de `lines_json`.
- El draft fluye por el flujo SoD EXISTENTE (`approve_journal_drafts` +
  `post_journal_drafts`, maker≠checker); al postear, `ensure_journal_entry_lines`
  cuelga el centro de costo en `JournalEntryLine.cost_center`.
"""
from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction
from django.utils import timezone

from .audit_helpers import write_accounting_audit_event
from .models import (
    ChartOfAccount,
    CostCenter,
    DraftValidationResult,
    EconomicEvent,
    FiscalPeriod,
    JournalDraft,
    PostingRuleSet,
)
from .phase7 import get_or_create_accounting_config

_CENT = Decimal("0.01")


class AccountingPlusError(Exception):
    """Error de negocio de la Ola E; el código viaja como detail (422)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class AccountingPlusNotFound(AccountingPlusError):
    """Recurso no encontrado (404)."""


def _q2(x) -> Decimal:
    try:
        return Decimal(str(x)).quantize(_CENT)
    except (InvalidOperation, ValueError) as exc:
        raise AccountingPlusError("ACCOUNTING_AMOUNT_INVALID") from exc


def _require_phase7(company) -> None:
    cfg = get_or_create_accounting_config(company=company)
    if not bool(cfg.phase7_enabled):
        raise AccountingPlusError("ACCOUNTING_PHASE7_REQUIRED")


# --------------------------------------------------------------- rule_set sistema

def get_or_create_system_rule_set(*, company) -> PostingRuleSet:
    """`PostingRuleSet` de sistema por empresa para asientos manuales y de cierre.

    El unique global es (code, version); se usa code=`SYSTEM_MANUAL:{company_id}`.
    """
    rule_set, _created = PostingRuleSet.objects.get_or_create(
        code=f"SYSTEM_MANUAL:{company.id}",
        version=1,
        defaults={
            "status": PostingRuleSet.Status.ACTIVE,
            "scope_company": company,
            "rules_json": {},
        },
    )
    if rule_set.status != PostingRuleSet.Status.ACTIVE:
        rule_set.status = PostingRuleSet.Status.ACTIVE
        rule_set.save(update_fields=["status"])
    return rule_set


# --------------------------------------------------------------- centros de costo

def cost_center_payload(cc: CostCenter) -> dict[str, Any]:
    return {
        "id": cc.id,
        "code": cc.code,
        "name": cc.name,
        "is_active": cc.is_active,
        "created_at": cc.created_at.isoformat(),
    }


def list_cost_centers(*, company, include_inactive: bool = True) -> list[dict[str, Any]]:
    qs = CostCenter.objects.filter(company=company)
    if not include_inactive:
        qs = qs.filter(is_active=True)
    return [cost_center_payload(cc) for cc in qs.order_by("code")]


def create_cost_center(*, company, actor, code: str, name: str) -> CostCenter:
    code = (code or "").strip().upper()
    name = (name or "").strip()
    if not code or not name:
        raise AccountingPlusError("ACCOUNTING_COST_CENTER_INVALID")
    if CostCenter.objects.filter(company=company, code=code).exists():
        raise AccountingPlusError("ACCOUNTING_COST_CENTER_DUPLICATE")
    cc = CostCenter.objects.create(company=company, code=code, name=name, created_by=actor)
    _audit_cost_center(company=company, actor=actor, cc=cc, action="created")
    return cc


def update_cost_center(*, company, actor, cost_center_id: int, name=None, is_active=None) -> CostCenter:
    cc = CostCenter.objects.filter(company=company, id=cost_center_id).first()
    if cc is None:
        raise AccountingPlusNotFound("ACCOUNTING_COST_CENTER_NOT_FOUND")
    fields: list[str] = []
    if name is not None:
        name = str(name).strip()
        if not name:
            raise AccountingPlusError("ACCOUNTING_COST_CENTER_INVALID")
        cc.name = name
        fields.append("name")
    if is_active is not None:
        cc.is_active = bool(is_active)
        fields.append("is_active")
    if fields:
        cc.save(update_fields=fields + ["updated_at"])
        _audit_cost_center(company=company, actor=actor, cc=cc, action="updated")
    return cc


def _audit_cost_center(*, company, actor, cc: CostCenter, action: str) -> None:
    write_accounting_audit_event(
        actor_user=actor, company=company, branch=None,
        event_type="ACCOUNTING_COST_CENTER_UPSERTED",
        subject_type="COST_CENTER", subject_id=str(cc.id),
        after_snapshot={"code": cc.code, "name": cc.name, "is_active": cc.is_active},
        metadata={"action": action},
    )


# --------------------------------------------------------------- asiento manual

def _period_open_for_date(*, company, entry_date) -> FiscalPeriod:
    period, _ = FiscalPeriod.objects.get_or_create(
        company=company, year=int(entry_date.year), month=int(entry_date.month),
        defaults={"status": FiscalPeriod.Status.OPEN},
    )
    if period.status == FiscalPeriod.Status.CLOSED:
        raise AccountingPlusError("ACCOUNTING_PERIOD_CLOSED")
    return period


def create_manual_journal_draft(
    *,
    company,
    branch,
    actor,
    entry_date,
    memo: str,
    lines: list[dict],
) -> JournalDraft:
    """Crea un asiento manual como draft VALIDATED (lo aprueba/postea el flujo SoD existente).

    lines = [{account_code, side("DEBIT"/"CREDIT"), amount, description?, cost_center_id?}]
    """
    _require_phase7(company)
    if not lines:
        raise AccountingPlusError("ACCOUNTING_MANUAL_NO_LINES")
    _period_open_for_date(company=company, entry_date=entry_date)

    codes = {str(ln.get("account_code") or "").strip().upper() for ln in lines}
    codes.discard("")
    accounts = {
        a.code: a for a in ChartOfAccount.objects.filter(company=company, code__in=codes)
    }
    cc_ids = {
        int(ln["cost_center_id"]) for ln in lines if ln.get("cost_center_id") not in (None, "")
    }
    cost_centers = {
        cc.id for cc in CostCenter.objects.filter(company=company, id__in=cc_ids, is_active=True)
    } if cc_ids else set()

    lines_json: list[dict[str, Any]] = []
    total_debit = Decimal("0.00")
    total_credit = Decimal("0.00")
    for idx, ln in enumerate(lines):
        code = str(ln.get("account_code") or "").strip().upper()
        account = accounts.get(code)
        if account is None:
            raise AccountingPlusError("ACCOUNTING_ACCOUNT_NOT_FOUND")
        if not account.is_active or not account.is_postable:
            raise AccountingPlusError("ACCOUNTING_ACCOUNT_NOT_POSTABLE")
        side = str(ln.get("side") or "").strip().upper()
        if side not in ("DEBIT", "CREDIT"):
            raise AccountingPlusError("ACCOUNTING_LINE_SIDE_INVALID")
        amount = _q2(ln.get("amount"))
        if amount <= 0:
            raise AccountingPlusError("ACCOUNTING_LINE_AMOUNT_INVALID")
        cc_id = ln.get("cost_center_id")
        if cc_id not in (None, ""):
            cc_id = int(str(cc_id))
            if cc_id not in cost_centers:
                raise AccountingPlusError("ACCOUNTING_COST_CENTER_NOT_FOUND")
        else:
            cc_id = None
        row: dict[str, Any] = {
            "account": account.code,
            "side": side,
            "amount": str(amount),
            "description": str(ln.get("description") or "")[:200],
        }
        if cc_id is not None:
            row["cost_center_id"] = cc_id
        lines_json.append(row)
        if side == "DEBIT":
            total_debit += amount
        else:
            total_credit += amount

    total_debit = _q2(total_debit)
    total_credit = _q2(total_credit)
    if total_debit != total_credit:
        raise AccountingPlusError("ACCOUNTING_MANUAL_UNBALANCED")
    if total_debit <= 0:
        raise AccountingPlusError("ACCOUNTING_MANUAL_EMPTY")

    occurred_at = timezone.make_aware(
        datetime.combine(entry_date, time(12, 0)), timezone.get_current_timezone()
    )
    rule_set = get_or_create_system_rule_set(company=company)

    with transaction.atomic():
        event = EconomicEvent.objects.create(
            source_module="ACCOUNTING",
            event_type="ManualJournal",
            company=company,
            branch=branch,
            occurred_at=occurred_at,
            contract_version="1.0",
            schema_version=1,
            correlation_id=f"manual-{company.id}-{timezone.now().timestamp()}",
            causation_id="",
            payload={
                "source_module": "ACCOUNTING",
                "event_type": "ManualJournal",
                "data": {"memo": str(memo or "")[:255], "lines": lines_json},
                "scope": {"company_id": int(company.id), "branch_id": getattr(branch, "id", None)},
            },
            input_manifest_hash="",
            close_run_id="",
        )
        draft = JournalDraft.objects.create(
            economic_event=event,
            rule_set=rule_set,
            state=JournalDraft.State.VALIDATED,
            contract_version="1.0",
            schema_version=1,
            close_run_id="",
            input_manifest_hash="",
            lines_json=lines_json,
            total_debit=total_debit,
            total_credit=total_credit,
            generated_by=actor,
            validated_at=timezone.now(),
            metadata={"manual": True, "memo": str(memo or "")[:255]},
        )
        DraftValidationResult.objects.update_or_create(
            draft=draft,
            defaults={"passed": True, "errors_json": [], "is_blocking": False, "validated_at": timezone.now()},
        )
        write_accounting_audit_event(
            actor_user=actor, company=company, branch=branch,
            event_type="ACCOUNTING_MANUAL_JOURNAL_DRAFTED",
            subject_type="JOURNAL_DRAFT", subject_id=str(draft.id),
            after_snapshot={"state": draft.state, "total": str(total_debit)},
            metadata={"memo": str(memo or "")[:120], "lines": len(lines_json)},
        )
    return draft


def manual_draft_payload(draft: JournalDraft) -> dict[str, Any]:
    return {
        "draft_id": draft.id,
        "state": draft.state,
        "total_debit": str(draft.total_debit),
        "total_credit": str(draft.total_credit),
        "lines": draft.lines_json,
        "memo": (draft.metadata or {}).get("memo", ""),
    }
