"""Tests de auditoría de revaluación FX (Unidad #4, endurecimiento).

Cierra los contratos ACCOUNTING_FX_REVALUATION_EXECUTED / _BLOCKED, antes
declarados en audit/contracts.py pero sin emitirse desde run_fx_revaluation.
"""
from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.accounting.models import ChartOfAccount, RevaluationEntryLink, RevaluationRun
from apps.kernels.accounting.phase7 import get_or_create_accounting_config, run_fx_revaluation
from apps.modulos.audit.models import AuditEvent
from apps.modulos.iam.models import OrgUnit

User = get_user_model()


def _mk_company():
    s = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H_{s}")
    return OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name=f"C_{s}", parent=holding)


def _actor():
    name = f"u_{uuid.uuid4().hex[:8]}"
    return User.objects.create_user(username=name, email=f"{name}@test.com", password="x")


def _audit(event_type, subject_id):
    return AuditEvent.objects.filter(event_type=event_type, subject_id=str(subject_id))


@pytest.mark.django_db
def test_fx_revaluation_blocked_emits_audit():
    # Config fresca: phase7 deshabilitado + cuentas fx ausentes -> issues -> BLOCKED.
    company = _mk_company()
    actor = _actor()

    result = run_fx_revaluation(company_id=company.id, year=2026, month=1, strict=True, actor_user=actor)

    assert result.status == RevaluationRun.Status.BLOCKED
    ev = _audit("ACCOUNTING_FX_REVALUATION_BLOCKED", result.run_id).first()
    assert ev is not None
    assert ev.subject_type == "REVALUATION_RUN"
    assert ev.reason_code == "ACCOUNTING_REVALUATION_BLOCKED"
    assert int(ev.metadata.get("issues_count") or 0) >= 1


@pytest.mark.django_db
def test_fx_revaluation_executed_emits_audit():
    # phase7 habilitado + cuentas fx presentes, sin exposición -> COMPLETED (0 asientos).
    company = _mk_company()
    actor = _actor()
    gain = ChartOfAccount.objects.create(
        company=company, code="FXG", name="FX Gain", account_type=ChartOfAccount.AccountType.REVENUE
    )
    loss = ChartOfAccount.objects.create(
        company=company, code="FXL", name="FX Loss", account_type=ChartOfAccount.AccountType.EXPENSE
    )
    cfg = get_or_create_accounting_config(company=company)
    cfg.phase7_enabled = True
    cfg.fx_gain_account = gain
    cfg.fx_loss_account = loss
    cfg.save(update_fields=["phase7_enabled", "fx_gain_account", "fx_loss_account"])

    result = run_fx_revaluation(company_id=company.id, year=2026, month=2, strict=True, actor_user=actor)

    assert result.status == RevaluationRun.Status.COMPLETED
    assert result.entries_created == 0
    ev = _audit("ACCOUNTING_FX_REVALUATION_EXECUTED", result.run_id).first()
    assert ev is not None
    assert ev.subject_type == "REVALUATION_RUN"
    assert ev.after_snapshot.get("status") == RevaluationRun.Status.COMPLETED


@pytest.mark.django_db
def test_fx_revaluation_blocked_can_retry_then_replays_completed_once():
    company = _mk_company()
    actor = _actor()

    blocked = run_fx_revaluation(company_id=company.id, year=2026, month=3, strict=True, actor_user=actor)
    assert blocked.status == RevaluationRun.Status.BLOCKED

    gain = ChartOfAccount.objects.create(
        company=company, code="FXG", name="FX Gain", account_type=ChartOfAccount.AccountType.REVENUE
    )
    loss = ChartOfAccount.objects.create(
        company=company, code="FXL", name="FX Loss", account_type=ChartOfAccount.AccountType.EXPENSE
    )
    cfg = get_or_create_accounting_config(company=company)
    cfg.phase7_enabled = True
    cfg.fx_gain_account = gain
    cfg.fx_loss_account = loss
    cfg.save(update_fields=["phase7_enabled", "fx_gain_account", "fx_loss_account"])

    completed = run_fx_revaluation(company_id=company.id, year=2026, month=3, strict=True, actor_user=actor)
    assert completed.run_id == blocked.run_id
    assert completed.status == RevaluationRun.Status.COMPLETED
    assert completed.idempotent is False
    assert completed.entries_created == 0

    replay = run_fx_revaluation(company_id=company.id, year=2026, month=3, strict=True, actor_user=actor)
    assert replay.run_id == completed.run_id
    assert replay.status == RevaluationRun.Status.COMPLETED
    assert replay.idempotent is True
    assert RevaluationRun.objects.filter(company=company, year=2026, month=3).count() == 1
    assert RevaluationEntryLink.objects.filter(revaluation_run__run_id=completed.run_id).count() == 0
    assert _audit("ACCOUNTING_FX_REVALUATION_BLOCKED", completed.run_id).count() == 1
    assert _audit("ACCOUNTING_FX_REVALUATION_EXECUTED", completed.run_id).count() == 1
