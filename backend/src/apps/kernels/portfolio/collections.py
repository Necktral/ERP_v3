"""Cobranza (dunning) del kernel portfolio — Ola D.

Mesa de cobranza por CLIENTE: agrupa las CxC vencidas, sugiere el nivel de
escalación (1→3 según días de mora, sin retroceder respecto del último
recordatorio emitido) y registra cada recordatorio con un snapshot de los
documentos cubiertos. La carta imprimible la arma el frontend; el aviso in-app
ya lo dan las alertas (scan_overdue_receivables) — aquí NO se duplica.

Multi-empresa nativo: todo scoped por company; un cliente con deuda en dos
monedas son dos filas (y dos recordatorios), una por moneda.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any, Optional

from django.db import transaction
from django.db.models import DecimalField, ExpressionWrapper, F
from django.utils import timezone

from .models import CollectionReminder, ObligationStatus, Receivable
from .services import PortfolioDomainError, _write_portfolio_audit_event

# Días de mora → nivel de escalación base (D4): cualquier mora arranca en 1.
LEVEL_2_DAYS = 30
LEVEL_3_DAYS = 60
# Un recordatorio más nuevo que esto marca cooldown (aviso, no bloqueo duro).
REMINDER_COOLDOWN_DAYS = 7

_OPEN_STATUSES = (
    ObligationStatus.PENDING,
    ObligationStatus.PARTIAL,
    ObligationStatus.OVERDUE,
)

_CENT = Decimal("0.01")


def _q2(x) -> Decimal:
    return Decimal(x).quantize(_CENT)


def _base_level(days_overdue: int) -> int:
    if days_overdue >= LEVEL_3_DAYS:
        return 3
    if days_overdue >= LEVEL_2_DAYS:
        return 2
    return 1


def _overdue_receivables(*, company, party_id: Optional[int] = None):
    """CxC vencidas con saldo, filtradas EN LA BD (oleada 5).

    Antes traía TODA la cartera vencida a memoria y filtraba el outstanding
    en Python; ahora el saldo (componentes − asignado) se calcula y filtra
    sargable en el queryset.
    """
    today = timezone.localdate()
    outstanding = ExpressionWrapper(
        F("principal_amount") + F("interest_amount") + F("fee_amount")
        + F("penalty_amount") - F("allocated_amount"),
        output_field=DecimalField(max_digits=18, decimal_places=2),
    )
    qs = (
        Receivable.objects.filter(
            company=company, status__in=_OPEN_STATUSES,
            due_date__isnull=False, due_date__lt=today,
        )
        .annotate(outstanding_db=outstanding)
        .filter(outstanding_db__gt=0)
        .select_related("party")
    )
    if party_id is not None:
        qs = qs.filter(party_id=party_id)
    return list(qs)


def _last_reminder(*, company, party_id: int, currency: str) -> Optional[CollectionReminder]:
    return (
        CollectionReminder.objects.filter(company=company, party_id=party_id, currency=currency)
        .order_by("-created_at")
        .first()
    )


def _suggested_level(*, max_days: int, last: Optional[CollectionReminder]) -> int:
    level = _base_level(max_days)
    if last is not None:
        level = max(level, min(3, last.level + 1))
    return level


def _snapshot_line(rx: Receivable, *, today) -> dict[str, Any]:
    return {
        "obligation_id": str(rx.obligation_id),
        "invoice_number": rx.invoice_number or "",
        "due_date": rx.due_date.isoformat(),
        "days_overdue": (today - rx.due_date).days,
        "outstanding": str(_q2(rx.outstanding_amount)),
    }


def collections_workbench(*, company) -> list[dict[str, Any]]:
    """Clientes con saldo vencido, agrupados por (cliente, moneda), listos para gestionar."""
    today = timezone.localdate()
    groups: dict[tuple[int, str], dict[str, Any]] = {}
    for rx in _overdue_receivables(company=company):
        key = (rx.party_id, rx.currency)
        g = groups.get(key)
        if g is None:
            g = groups[key] = {
                "party_id": rx.party_id,
                "party_name": rx.party.display_name,
                "currency": rx.currency,
                "docs": 0,
                "total_outstanding": Decimal("0.00"),
                "max_days_overdue": 0,
            }
        g["docs"] += 1
        g["total_outstanding"] += _q2(rx.outstanding_amount)
        g["max_days_overdue"] = max(g["max_days_overdue"], (today - rx.due_date).days)

    # Último recordatorio por (cliente, moneda) en UNA query (antes: una por
    # grupo). DISTINCT ON de Postgres: la primera fila de cada grupo ordenado
    # por -created_at es la más reciente.
    last_by_key: dict[tuple[int, str], CollectionReminder] = {
        (r.party_id, r.currency): r
        for r in CollectionReminder.objects.filter(company=company)
        .order_by("party_id", "currency", "-created_at")
        .distinct("party_id", "currency")
    }

    rows: list[dict[str, Any]] = []
    for (party_id, currency), g in groups.items():
        last = last_by_key.get((party_id, currency))
        cooldown = (
            last is not None
            and (timezone.now() - last.created_at) < timedelta(days=REMINDER_COOLDOWN_DAYS)
        )
        rows.append({
            **g,
            "total_outstanding": str(g["total_outstanding"]),
            "last_reminder": (
                {"level": last.level, "date": last.reminder_date.isoformat()} if last else None
            ),
            "suggested_level": _suggested_level(max_days=g["max_days_overdue"], last=last),
            "cooldown_active": cooldown,
        })
    rows.sort(key=lambda r: (-r["max_days_overdue"], r["party_name"]))
    return rows


def _reminder_payload(reminder: CollectionReminder) -> dict[str, Any]:
    return {
        "id": reminder.id,
        "party_id": reminder.party_id,
        "party_name": reminder.party.display_name,
        "level": reminder.level,
        "reminder_date": reminder.reminder_date.isoformat(),
        "total_outstanding": str(reminder.total_outstanding),
        "currency": reminder.currency,
        "receivables": reminder.receivables_json,
        "notes": reminder.notes,
        "generated_by": getattr(reminder.generated_by, "username", "") or "",
        "created_at": reminder.created_at.isoformat(),
    }


def create_collection_reminder(
    *,
    company,
    branch,
    actor,
    party_id: int,
    currency: str = "NIO",
    level: Optional[int] = None,
    notes: str = "",
) -> dict[str, Any]:
    """Registra un recordatorio de cobro para el cliente y devuelve el insumo de la carta."""
    today = timezone.localdate()
    overdue = [
        rx for rx in _overdue_receivables(company=company, party_id=party_id)
        if rx.currency == currency
    ]
    if not overdue:
        raise PortfolioDomainError(
            "PORTFOLIO_NO_OVERDUE_RECEIVABLES",
            "El cliente no tiene documentos vencidos en esa moneda",
        )

    max_days = max((today - rx.due_date).days for rx in overdue)
    last = _last_reminder(company=company, party_id=party_id, currency=currency)
    if level is None:
        level = _suggested_level(max_days=max_days, last=last)
    if not 1 <= int(level) <= 3:
        raise PortfolioDomainError("PORTFOLIO_INVALID_REMINDER_LEVEL", "Nivel fuera de rango (1-3)")

    lines = [_snapshot_line(rx, today=today) for rx in overdue]
    total = sum((_q2(rx.outstanding_amount) for rx in overdue), Decimal("0.00"))

    with transaction.atomic():
        reminder = CollectionReminder.objects.create(
            company=company,
            branch=branch,
            party=overdue[0].party,
            level=int(level),
            reminder_date=today,
            total_outstanding=total,
            currency=currency,
            receivables_json=lines,
            notes=notes,
            generated_by=actor,
        )
        _write_portfolio_audit_event(
            actor_user=actor,
            company=company,
            branch=branch,
            event_type="PORTFOLIO_COLLECTION_REMINDER_CREATED",
            subject_type="COLLECTION_REMINDER",
            subject_id=str(reminder.id),
            after_snapshot={
                "party_id": reminder.party_id,
                "level": reminder.level,
                "total_outstanding": str(total),
                "currency": currency,
                "docs": len(lines),
            },
        )
    return _reminder_payload(reminder)


def list_collection_reminders(*, company, party_id: Optional[int] = None) -> list[dict[str, Any]]:
    qs = (
        CollectionReminder.objects.filter(company=company)
        .select_related("party", "generated_by")
        .order_by("-created_at")
    )
    if party_id is not None:
        qs = qs.filter(party_id=party_id)
    return [_reminder_payload(r) for r in qs[:200]]
