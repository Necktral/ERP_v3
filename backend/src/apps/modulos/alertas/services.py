"""Escáneres deterministas de alertas + upsert/reconcile con dedupe.

Cada escáner evalúa UNA condición operativa por empresa y devuelve los sujetos
activos; `_sync_alert_type` abre/reabre los nuevos, refresca los vigentes y RESUELVE
los que desaparecieron. Sin IA, sin red: solo lecturas de los kernels. La notificación
(in-app/push vía `notifications.notify_roles`) se emite SOLO al abrir o reabrir.

Diseño tomado de Odoo (actividades programadas / automated actions) aterrizado al
patrón de la casa: comando idempotente + estado deduplicado + outbox de notificaciones.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any, Callable, Optional

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.modulos.iam.models import OrgUnit
from apps.modulos.notifications.services import notify_roles

from .models import Alert, AlertSeverity, AlertStatus

# Roles que reciben la notificación cuando se abre/reabre cada tipo de alerta
# (company_admin siempre; el rol operativo dueño del tema, además).
_ALERT_ROLES: dict[str, list[str]] = {
    "RECEIVABLE_OVERDUE": ["company_admin", "collections_officer"],
    "RECEIVABLE_DUE_SOON": ["company_admin", "collections_officer"],
    "FINANCING_LOAN_OVERDUE": ["company_admin", "financing_officer"],
    "LOW_STOCK": ["company_admin", "warehouse_manager"],
    "FLEET_DOC_EXPIRING": ["company_admin", "fleet_supervisor"],
    "YIELD_ANOMALY": ["company_admin", "warehouse_manager"],
}


@dataclass
class AlertDraft:
    subject_type: str
    subject_id: str
    severity: str
    title: str
    detail: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


def upsert_alert(
    *, company: OrgUnit, alert_type: str, draft: AlertDraft, notify: bool = True,
) -> tuple[Alert, bool]:
    """Abre o refresca una alerta. Devuelve (alerta, abierta_o_reabierta)."""
    now = timezone.now()
    with transaction.atomic():
        alert, created = Alert.objects.select_for_update().get_or_create(
            company=company, alert_type=alert_type,
            subject_type=draft.subject_type, subject_id=draft.subject_id,
            defaults={
                "severity": draft.severity, "title": draft.title, "detail": draft.detail,
                "payload_json": draft.payload, "last_seen_at": now,
            },
        )
        reopened = False
        if not created:
            updates = {
                "last_seen_at": now, "severity": draft.severity,
                "title": draft.title, "detail": draft.detail, "payload_json": draft.payload,
            }
            if alert.status == AlertStatus.RESOLVED:
                updates.update({"status": AlertStatus.OPEN, "resolved_at": None,
                                "acknowledged_at": None, "acknowledged_by": None})
                reopened = True
            for k, v in updates.items():
                setattr(alert, k, v)
            alert.save(update_fields=[*updates.keys()])
    opened = created or reopened
    if opened and notify:
        roles = _ALERT_ROLES.get(alert_type, ["company_admin"])
        notify_roles(
            company=company, branch=None, roles=roles,
            event_type=f"ALERT_{alert_type}", title=draft.title, body=draft.detail,
            payload={"alert_id": alert.pk, "severity": draft.severity, **draft.payload},
            dedupe_prefix=f"alert:{alert.pk}:{now.date().isoformat()}",
        )
    return alert, opened


def _sync_alert_type(*, company: OrgUnit, alert_type: str, drafts: list[AlertDraft]) -> dict[str, int]:
    """Sincroniza el estado completo de un tipo: upsert de los activos + resolve del resto."""
    opened = 0
    for draft in drafts:
        _alert, was_opened = upsert_alert(company=company, alert_type=alert_type, draft=draft)
        opened += int(was_opened)
    active_keys = {(d.subject_type, d.subject_id) for d in drafts}
    resolved = 0
    stale = Alert.objects.filter(company=company, alert_type=alert_type).exclude(
        status=AlertStatus.RESOLVED
    )
    for alert in stale:
        if (alert.subject_type, alert.subject_id) not in active_keys:
            alert.status = AlertStatus.RESOLVED
            alert.resolved_at = timezone.now()
            alert.save(update_fields=["status", "resolved_at"])
            resolved += 1
    return {"active": len(drafts), "opened": opened, "resolved": resolved}


# ---------------------------------------------------------------------------
# Escáneres (uno por condición; todos deterministas y por empresa)
# ---------------------------------------------------------------------------

def scan_overdue_receivables(company: OrgUnit, *, due_soon_days: int = 7) -> dict[str, dict[str, int]]:
    """CxC vencidas (WARNING/CRITICAL por antigüedad) y por vencer (INFO)."""
    from apps.kernels.portfolio.models import ObligationStatus, Receivable

    today = timezone.localdate()
    open_statuses = [ObligationStatus.PENDING, ObligationStatus.PARTIAL, ObligationStatus.OVERDUE]
    overdue: list[AlertDraft] = []
    due_soon: list[AlertDraft] = []
    qs = Receivable.objects.filter(
        company=company, status__in=open_statuses, due_date__isnull=False,
        due_date__lte=today + timedelta(days=due_soon_days),
    ).select_related("party")
    for rx in qs:
        outstanding = rx.outstanding_amount
        if outstanding <= 0:
            continue
        days = (today - rx.due_date).days
        base = AlertDraft(
            subject_type="RECEIVABLE", subject_id=str(rx.obligation_id),
            severity=AlertSeverity.INFO, title="", detail="",
            payload={"party": rx.party.display_name, "outstanding": str(outstanding),
                     "currency": rx.currency, "due_date": rx.due_date.isoformat()},
        )
        if days > 0:
            base.severity = AlertSeverity.CRITICAL if days > 30 else AlertSeverity.WARNING
            base.title = f"CxC vencida hace {days} día(s): {rx.party.display_name}"
            base.detail = f"Saldo {outstanding} {rx.currency}, venció {rx.due_date.isoformat()}."
            overdue.append(base)
        else:
            base.title = f"CxC por vencer ({rx.due_date.isoformat()}): {rx.party.display_name}"
            base.detail = f"Saldo {outstanding} {rx.currency}, vence en {-days} día(s)."
            due_soon.append(base)
    return {
        "RECEIVABLE_OVERDUE": _sync_alert_type(company=company, alert_type="RECEIVABLE_OVERDUE", drafts=overdue),
        "RECEIVABLE_DUE_SOON": _sync_alert_type(company=company, alert_type="RECEIVABLE_DUE_SOON", drafts=due_soon),
    }


def scan_overdue_financing_loans(company: OrgUnit) -> dict[str, dict[str, int]]:
    """Préstamos de financiamiento ACTIVOS con vencimiento pasado y saldo vivo."""
    try:
        from apps.modulos.financiamiento.models import FinancingLoan, LoanStatus
    except ImportError:  # vertical no instalado en este despliegue
        return {"FINANCING_LOAN_OVERDUE": {"active": 0, "opened": 0, "resolved": 0}}

    today = timezone.localdate()
    drafts: list[AlertDraft] = []
    qs = FinancingLoan.objects.filter(
        company=company, status=LoanStatus.ACTIVE, maturity_date__lt=today,
    ).select_related("producer__party", "credit_nio", "credit_usd")
    for loan in qs:
        parts = []
        for credit in (loan.credit_nio, loan.credit_usd):
            if credit is not None and credit.outstanding_amount > 0:
                parts.append(f"{credit.outstanding_amount} {credit.currency}")
        if not parts:
            continue
        days = (today - loan.maturity_date).days
        drafts.append(AlertDraft(
            subject_type="FINANCING_LOAN", subject_id=str(loan.pk),
            severity=AlertSeverity.CRITICAL,
            title=f"Préstamo {loan.reference} vencido hace {days} día(s)",
            detail=f"{loan.producer.party.display_name}: saldo {' + '.join(parts)}.",
            payload={"reference": loan.reference, "maturity": loan.maturity_date.isoformat()},
        ))
    return {"FINANCING_LOAN_OVERDUE": _sync_alert_type(
        company=company, alert_type="FINANCING_LOAN_OVERDUE", drafts=drafts,
    )}


def scan_low_stock(company: OrgUnit) -> dict[str, dict[str, int]]:
    """Ítems con existencia total bajo el punto de reorden / mínimo (campos del kernel
    que hasta hoy estaban modelados pero muertos)."""
    from django.db.models import Q

    from apps.kernels.inventarios.models import InventoryItem, StockBalance

    drafts: list[AlertDraft] = []
    items = InventoryItem.objects.filter(company=company, is_active=True).filter(
        Q(reorder_point__gt=0) | Q(min_stock_qty__gt=0)
    )
    for item in items:
        on_hand = (
            StockBalance.objects.filter(company=company, item=item)
            .aggregate(s=Sum("qty_on_hand"))["s"] or Decimal("0")
        )
        min_qty = item.min_stock_qty or Decimal("0")
        reorder = item.reorder_point or Decimal("0")
        threshold = max(min_qty, reorder)
        if threshold <= 0 or on_hand >= threshold:
            continue
        critical = min_qty > 0 and on_hand < min_qty
        drafts.append(AlertDraft(
            subject_type="INVENTORY_ITEM", subject_id=str(item.pk),
            severity=AlertSeverity.CRITICAL if critical else AlertSeverity.WARNING,
            title=f"Stock bajo: {item.name} ({on_hand} {item.uom})",
            detail=(
                f"Existencia {on_hand} bajo "
                f"{'el mínimo ' + str(min_qty) if critical else 'el punto de reorden ' + str(reorder)}."
            ),
            payload={"sku": item.sku, "on_hand": str(on_hand),
                     "reorder_point": str(reorder), "min_stock_qty": str(min_qty)},
        ))
    return {"LOW_STOCK": _sync_alert_type(company=company, alert_type="LOW_STOCK", drafts=drafts)}


def scan_expiring_fleet_documents(company: OrgUnit, *, soon_days: int = 30) -> dict[str, dict[str, int]]:
    """Documentos de flota (circulación/seguro/licencias) vencidos o por vencer."""
    from apps.modulos.fleet.models import DocumentStatus, FleetDocument

    today = timezone.localdate()
    drafts: list[AlertDraft] = []
    qs = FleetDocument.objects.filter(
        company=company, status=DocumentStatus.VALID, expiry_date__isnull=False,
        expiry_date__lte=today + timedelta(days=soon_days),
    )
    for doc in qs:
        expiry_date = doc.expiry_date
        if expiry_date is None:
            continue
        days = (expiry_date - today).days
        expired = days < 0
        drafts.append(AlertDraft(
            subject_type="FLEET_DOCUMENT", subject_id=str(doc.pk),
            severity=AlertSeverity.CRITICAL if expired else AlertSeverity.WARNING,
            title=(
                f"Documento de flota {doc.doc_type} "
                + (f"VENCIDO hace {-days} día(s)" if expired else f"vence en {days} día(s)")
            ),
            detail=f"{doc.number or 'sin número'} — vence {expiry_date.isoformat()}.",
            payload={"doc_type": doc.doc_type, "expiry": expiry_date.isoformat()},
        ))
    return {"FLEET_DOC_EXPIRING": _sync_alert_type(
        company=company, alert_type="FLEET_DOC_EXPIRING", drafts=drafts,
    )}


_SCANNERS: list[Callable[[OrgUnit], dict[str, dict[str, int]]]] = [
    scan_overdue_receivables,
    scan_overdue_financing_loans,
    scan_low_stock,
    scan_expiring_fleet_documents,
]


def run_all_scanners(*, company: Optional[OrgUnit] = None) -> dict[str, Any]:
    """Corre todos los escáneres para una empresa o para todas (comando periódico)."""
    companies = (
        [company] if company is not None
        else list(OrgUnit.objects.filter(unit_type=OrgUnit.UnitType.COMPANY))
    )
    out: dict[str, Any] = {}
    for comp in companies:
        per_company: dict[str, dict[str, int]] = {}
        for scanner in _SCANNERS:
            per_company.update(scanner(comp))
        out[comp.code or str(comp.pk)] = per_company
    return out


# ---------------------------------------------------------------------------
# Acciones humanas sobre la alerta
# ---------------------------------------------------------------------------

def acknowledge_alert(*, alert: Alert, actor) -> Alert:
    if alert.status == AlertStatus.RESOLVED:
        return alert
    alert.status = AlertStatus.ACKNOWLEDGED
    alert.acknowledged_at = timezone.now()
    alert.acknowledged_by = actor if getattr(actor, "pk", None) else None
    alert.save(update_fields=["status", "acknowledged_at", "acknowledged_by"])
    return alert


def resolve_alert(*, alert: Alert) -> Alert:
    """Resolución manual (p.ej. el humano decide que ya no aplica). El escáner la
    reabrirá si la condición sigue activa — honestidad por diseño."""
    if alert.status != AlertStatus.RESOLVED:
        alert.status = AlertStatus.RESOLVED
        alert.resolved_at = timezone.now()
        alert.save(update_fields=["status", "resolved_at"])
    return alert
