"""Conciliación bancaria del kernel payments — Ola D.

Cuentas bancarias + extractos por período + matching de líneas contra los
PaymentIntents CAPTURED de métodos no-efectivo (TRANSFER/CHECK/CARD). El
efectivo NO se concilia aquí: su control es el arqueo de la sesión de caja.

Reglas:
- Sugerencia automática por |monto| igual + captured_at dentro de ±3 días de la
  fecha de línea + intent aún libre; el humano confirma (match manual disponible).
- Línea EXCLUDED con razón = ítems solo-banco (comisiones, intereses).
- Conciliar exige 100% de líneas resueltas Y cuadre:
  opening_balance + Σ(líneas) == closing_balance.
- Extracto RECONCILED queda inmutable.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.modulos.audit.service_audit import emit_service_event

from .models import BankAccount, BankStatement, BankStatementLine, PaymentIntent
from .services import PaymentsDomainError

# Métodos que mueven dinero por banco (el efectivo se arquea en caja).
BANK_METHODS = ("TRANSFER", "CHECK", "CARD")
# Ventana de fechas para sugerir un match (los bancos liquidan con rezago).
MATCH_DATE_WINDOW_DAYS = 3

_CENT = Decimal("0.01")


def _q2(x) -> Decimal:
    return Decimal(x).quantize(_CENT)


def _audit(*, company, branch, actor, event_type: str, subject_type: str, subject_id: str, metadata=None):
    emit_service_event(
        company=company,
        branch=branch,
        module="PAYMENTS",
        event_type=event_type,
        reason_code="OK",
        actor_user=actor,
        subject_type=subject_type,
        subject_id=str(subject_id),
        metadata=dict(metadata or {}),
    )


# ----------------------------------------------------------------- cuentas

def create_bank_account(
    *, company, actor, name: str, bank_name: str, account_number: str, currency: str = "NIO"
) -> BankAccount:
    name = (name or "").strip()
    bank_name = (bank_name or "").strip()
    account_number = (account_number or "").strip()
    if not name or not bank_name or not account_number:
        raise PaymentsDomainError("PAYMENTS_BANK_ACCOUNT_INVALID")
    if BankAccount.objects.filter(
        company=company, bank_name=bank_name, account_number=account_number
    ).exists():
        raise PaymentsDomainError("PAYMENTS_BANK_ACCOUNT_DUPLICATE")
    account = BankAccount.objects.create(
        company=company, name=name, bank_name=bank_name,
        account_number=account_number, currency=currency or "NIO", created_by=actor,
    )
    _audit(
        company=company, branch=None, actor=actor,
        event_type="PAYMENTS_BANK_ACCOUNT_CREATED", subject_type="BANK_ACCOUNT",
        subject_id=str(account.id), metadata={"bank_name": bank_name, "account_number": account_number},
    )
    return account


def account_payload(account: BankAccount) -> dict[str, Any]:
    return {
        "id": account.id,
        "name": account.name,
        "bank_name": account.bank_name,
        "account_number": account.account_number,
        "currency": account.currency,
        "is_active": account.is_active,
        "created_at": account.created_at.isoformat(),
    }


# ----------------------------------------------------------------- extractos

def _line_payload(line: BankStatementLine) -> dict[str, Any]:
    intent = line.matched_intent
    return {
        "id": line.id,
        "position": line.position,
        "line_date": line.line_date.isoformat(),
        "description": line.description,
        "reference": line.reference,
        "amount": str(_q2(line.amount)),
        "status": line.status,
        "matched_payment_id": str(intent.payment_id) if intent else None,
        "matched_method": intent.payment_method if intent else "",
        "matched_external_ref": intent.external_ref if intent else "",
        "excluded_reason": line.excluded_reason,
    }


def statement_payload(statement: BankStatement, *, with_lines: bool = True) -> dict[str, Any]:
    lines = list(statement.lines.all()) if with_lines else []
    resolved = sum(1 for ln in lines if ln.status != BankStatementLine.Status.UNMATCHED)
    payload: dict[str, Any] = {
        "id": statement.id,
        "bank_account_id": statement.bank_account_id,
        "bank_account_name": statement.bank_account.name,
        "bank_name": statement.bank_account.bank_name,
        "period_start": statement.period_start.isoformat(),
        "period_end": statement.period_end.isoformat(),
        "opening_balance": str(_q2(statement.opening_balance)),
        "closing_balance": str(_q2(statement.closing_balance)),
        "status": statement.status,
        "reconciled_at": statement.reconciled_at.isoformat() if statement.reconciled_at else None,
        "created_at": statement.created_at.isoformat(),
    }
    if with_lines:
        payload["lines"] = [_line_payload(ln) for ln in lines]
        payload["lines_total"] = len(lines)
        payload["lines_resolved"] = resolved
    return payload


def create_bank_statement(
    *,
    company,
    actor,
    bank_account_id: int,
    period_start: date,
    period_end: date,
    opening_balance: Decimal,
    closing_balance: Decimal,
    lines: list[dict],
) -> BankStatement:
    account = BankAccount.objects.filter(company=company, id=bank_account_id, is_active=True).first()
    if account is None:
        raise PaymentsDomainError("PAYMENTS_BANK_ACCOUNT_NOT_FOUND")
    if period_end < period_start:
        raise PaymentsDomainError("PAYMENTS_STATEMENT_PERIOD_INVALID")
    if not lines:
        raise PaymentsDomainError("PAYMENTS_STATEMENT_LINES_REQUIRED")

    with transaction.atomic():
        statement = BankStatement.objects.create(
            company=company, bank_account=account,
            period_start=period_start, period_end=period_end,
            opening_balance=_q2(Decimal(str(opening_balance))),
            closing_balance=_q2(Decimal(str(closing_balance))),
            created_by=actor,
        )
        rows = []
        for idx, raw in enumerate(lines, start=1):
            amount = _q2(Decimal(str(raw.get("amount", "0"))))
            if amount == 0:
                raise PaymentsDomainError("PAYMENTS_STATEMENT_LINE_AMOUNT_INVALID")
            rows.append(BankStatementLine(
                statement=statement, position=idx,
                line_date=raw["line_date"],
                description=str(raw.get("description", ""))[:200],
                reference=str(raw.get("reference", ""))[:96],
                amount=amount,
            ))
        BankStatementLine.objects.bulk_create(rows)
        _audit(
            company=company, branch=None, actor=actor,
            event_type="PAYMENTS_BANK_STATEMENT_CREATED", subject_type="BANK_STATEMENT",
            subject_id=str(statement.id),
            metadata={"bank_account_id": account.id, "lines": len(rows)},
        )
    return statement


def _statement_for_update(*, company, statement_id: int) -> BankStatement:
    statement = (
        BankStatement.objects.select_for_update()
        .select_related("bank_account")
        .filter(company=company, id=statement_id)
        .first()
    )
    if statement is None:
        raise PaymentsDomainError("PAYMENTS_STATEMENT_NOT_FOUND")
    return statement


def _require_open(statement: BankStatement) -> None:
    if statement.status != BankStatement.Status.OPEN:
        raise PaymentsDomainError("PAYMENTS_STATEMENT_NOT_OPEN")


# ----------------------------------------------------------------- matching

def _candidate_intents(*, company, currency: str, amount: Decimal, line_date: date):
    """Intents bancarios CAPTURED, libres, compatibles con la línea por sentido económico.

    Un PaymentIntent CAPTURED es SIEMPRE un cobro (entrada de dinero, amount > 0;
    el modelo no tiene noción de salida). Por eso solo puede respaldar una línea de
    DEPÓSITO (amount > 0): un RETIRO (amount < 0) jamás tiene candidatos aquí. Además
    el método debe ser bancario (el efectivo se arquea en caja) y la moneda del intent
    debe coincidir con la de la cuenta del extracto.
    """
    # Solo las líneas de entrada (depósitos) pueden corresponder a un cobro CAPTURED.
    if amount <= 0:
        return PaymentIntent.objects.none()
    window_start = line_date - timedelta(days=MATCH_DATE_WINDOW_DAYS)
    window_end = line_date + timedelta(days=MATCH_DATE_WINDOW_DAYS)
    return (
        PaymentIntent.objects.filter(
            company=company,
            status=PaymentIntent.Status.CAPTURED,
            payment_method__in=BANK_METHODS,
            currency=currency,
            amount=amount,
            captured_at__date__gte=window_start,
            captured_at__date__lte=window_end,
            bank_statement_lines__isnull=True,
        )
        .order_by("captured_at")
    )


def _intent_summary(intent: PaymentIntent) -> dict[str, Any]:
    return {
        "payment_id": str(intent.payment_id),
        "amount": str(_q2(intent.amount)),
        "currency": intent.currency,
        "method": intent.payment_method,
        "external_ref": intent.external_ref,
        "captured_at": intent.captured_at.isoformat() if intent.captured_at else None,
    }


def suggest_matches(*, company, statement_id: int) -> list[dict[str, Any]]:
    """Candidatos por línea con UNA query de intents para todo el extracto.

    Misma semántica que la versión línea-por-línea (monto exacto + ventana de
    fechas por línea + orden por captured_at + top 5), pero los intents libres
    se traen en un solo query global (montos IN + ventana envolvente) y se
    reparten en memoria — antes era una query por línea UNMATCHED.
    """
    statement = (
        BankStatement.objects.select_related("bank_account")
        .filter(company=company, id=statement_id)
        .first()
    )
    if statement is None:
        raise PaymentsDomainError("PAYMENTS_STATEMENT_NOT_FOUND")
    currency = statement.bank_account.currency

    lines = list(statement.lines.filter(status=BankStatementLine.Status.UNMATCHED))
    deposit_lines = [ln for ln in lines if ln.amount > 0]

    grouped: dict[Decimal, list[PaymentIntent]] = {}
    if deposit_lines:
        window_start = min(ln.line_date for ln in deposit_lines) - timedelta(days=MATCH_DATE_WINDOW_DAYS)
        window_end = max(ln.line_date for ln in deposit_lines) + timedelta(days=MATCH_DATE_WINDOW_DAYS)
        amounts = {ln.amount for ln in deposit_lines}
        intents = (
            PaymentIntent.objects.filter(
                company=company,
                status=PaymentIntent.Status.CAPTURED,
                payment_method__in=BANK_METHODS,
                currency=currency,
                amount__in=amounts,
                captured_at__date__gte=window_start,
                captured_at__date__lte=window_end,
                bank_statement_lines__isnull=True,
            )
            .order_by("captured_at")
        )
        for intent in intents:
            grouped.setdefault(_q2(intent.amount), []).append(intent)

    suggestions = []
    for line in lines:
        candidates: list[dict[str, Any]] = []
        if line.amount > 0:
            start = line.line_date - timedelta(days=MATCH_DATE_WINDOW_DAYS)
            end = line.line_date + timedelta(days=MATCH_DATE_WINDOW_DAYS)
            candidates = [
                _intent_summary(i)
                for i in grouped.get(_q2(line.amount), [])
                if i.captured_at is not None and start <= timezone.localtime(i.captured_at).date() <= end
            ][:5]
        suggestions.append({"line_id": line.id, "candidates": candidates})
    return suggestions


def match_line(*, company, actor, statement_id: int, line_id: int, payment_id) -> dict[str, Any]:
    with transaction.atomic():
        statement = _statement_for_update(company=company, statement_id=statement_id)
        _require_open(statement)
        line = statement.lines.select_for_update().filter(id=line_id).first()
        if line is None:
            raise PaymentsDomainError("PAYMENTS_STATEMENT_LINE_NOT_FOUND")
        if line.status == BankStatementLine.Status.MATCHED:
            raise PaymentsDomainError("PAYMENTS_STATEMENT_LINE_ALREADY_MATCHED")
        # Un cobro CAPTURED es una ENTRADA de dinero (amount > 0); solo respalda una
        # línea de DEPÓSITO. Un RETIRO (amount < 0) nunca puede conciliarse con un cobro.
        if _q2(line.amount) <= 0:
            raise PaymentsDomainError("PAYMENTS_MATCH_SIGN_MISMATCH")
        intent = (
            PaymentIntent.objects.select_for_update()
            .filter(company=company, payment_id=payment_id, status=PaymentIntent.Status.CAPTURED)
            .first()
        )
        if intent is None:
            raise PaymentsDomainError("PAYMENTS_INTENT_NOT_FOUND")
        if intent.bank_statement_lines.exists():
            raise PaymentsDomainError("PAYMENTS_INTENT_ALREADY_MATCHED")
        # El efectivo se concilia por ARQUEO de caja, no contra el extracto bancario.
        if intent.payment_method not in BANK_METHODS:
            raise PaymentsDomainError("PAYMENTS_MATCH_METHOD_NOT_BANKABLE")
        # La moneda del cobro debe coincidir con la de la cuenta bancaria del extracto.
        if intent.currency != statement.bank_account.currency:
            raise PaymentsDomainError("PAYMENTS_MATCH_CURRENCY_MISMATCH")
        if _q2(intent.amount) != _q2(line.amount):
            raise PaymentsDomainError("PAYMENTS_MATCH_AMOUNT_MISMATCH")

        line.status = BankStatementLine.Status.MATCHED
        line.matched_intent = intent
        line.excluded_reason = ""
        line.matched_by = actor
        line.matched_at = timezone.now()
        line.save(update_fields=["status", "matched_intent", "excluded_reason", "matched_by", "matched_at"])
        _audit(
            company=company, branch=None, actor=actor,
            event_type="PAYMENTS_BANK_LINE_MATCHED", subject_type="BANK_STATEMENT",
            subject_id=str(statement.id),
            metadata={"line_id": line.id, "payment_id": str(intent.payment_id)},
        )
        return _line_payload(line)


def unmatch_line(*, company, actor, statement_id: int, line_id: int) -> dict[str, Any]:
    with transaction.atomic():
        statement = _statement_for_update(company=company, statement_id=statement_id)
        _require_open(statement)
        line = statement.lines.select_for_update().filter(id=line_id).first()
        if line is None:
            raise PaymentsDomainError("PAYMENTS_STATEMENT_LINE_NOT_FOUND")
        line.status = BankStatementLine.Status.UNMATCHED
        line.matched_intent = None
        line.excluded_reason = ""
        line.matched_by = actor
        line.matched_at = timezone.now()
        line.save(update_fields=["status", "matched_intent", "excluded_reason", "matched_by", "matched_at"])
        return _line_payload(line)


def exclude_line(*, company, actor, statement_id: int, line_id: int, reason: str) -> dict[str, Any]:
    reason = (reason or "").strip()
    if not reason:
        raise PaymentsDomainError("PAYMENTS_EXCLUDE_REASON_REQUIRED")
    with transaction.atomic():
        statement = _statement_for_update(company=company, statement_id=statement_id)
        _require_open(statement)
        line = statement.lines.select_for_update().filter(id=line_id).first()
        if line is None:
            raise PaymentsDomainError("PAYMENTS_STATEMENT_LINE_NOT_FOUND")
        line.status = BankStatementLine.Status.EXCLUDED
        line.matched_intent = None
        line.excluded_reason = reason[:255]
        line.matched_by = actor
        line.matched_at = timezone.now()
        line.save(update_fields=["status", "matched_intent", "excluded_reason", "matched_by", "matched_at"])
        _audit(
            company=company, branch=None, actor=actor,
            event_type="PAYMENTS_BANK_LINE_EXCLUDED", subject_type="BANK_STATEMENT",
            subject_id=str(statement.id), metadata={"line_id": line.id, "reason": reason[:120]},
        )
        return _line_payload(line)


def reconcile_statement(*, company, actor, statement_id: int) -> BankStatement:
    with transaction.atomic():
        statement = _statement_for_update(company=company, statement_id=statement_id)
        _require_open(statement)
        if statement.lines.filter(status=BankStatementLine.Status.UNMATCHED).exists():
            raise PaymentsDomainError("PAYMENTS_STATEMENT_LINES_PENDING")
        total = statement.lines.aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
        if _q2(statement.opening_balance + total) != _q2(statement.closing_balance):
            raise PaymentsDomainError("PAYMENTS_STATEMENT_UNBALANCED")
        statement.status = BankStatement.Status.RECONCILED
        statement.reconciled_by = actor
        statement.reconciled_at = timezone.now()
        statement.save(update_fields=["status", "reconciled_by", "reconciled_at"])
        _audit(
            company=company, branch=None, actor=actor,
            event_type="PAYMENTS_BANK_STATEMENT_RECONCILED", subject_type="BANK_STATEMENT",
            subject_id=str(statement.id),
            metadata={"lines": statement.lines.count()},
        )
    return statement
