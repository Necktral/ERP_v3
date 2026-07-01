"""Cobro NEGOCIADO al pagar (Cobrador-Pagador / CO-PA) — orquestador.

Vive en el módulo `comisariato` (el hub de integración comisariato↔nómina; la dirección de
dependencia correcta es módulo→kernel, ya usada por `apply_store_credit_deductions`). A
diferencia del cobro automático al armar la planilla (deuda completa), acá el pagador NEGOCIA
cuánto abonar a cada deuda interna AL PAGAR: un abono parcial al **comisariato** (CxC por cédula)
y otro al **préstamo personal** (`portfolio.Credit`). El abono baja el neto a entregar y abona la
deuda; el resto se paga en efectivo. Reusa los rieles probados.

Filosofía del dueño: avanzar lo más posible con la deuda, pero el abono es LIBRE de 0 al saldo
(hay trabajadores que no pueden abonar). El neto a entregar nunca queda negativo.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import transaction

from apps.kernels.nomina.models import PayrollEntry
from apps.kernels.nomina.payroll_payments import register_payroll_payment_idempotent
from apps.kernels.nomina.portfolio_link import (
    register_payroll_loan_deduction,
    reverse_payroll_loan_deduction,
)
from apps.kernels.portfolio.models import Credit
from apps.modulos.audit.writer import write_event

from .payroll_link import (
    apply_amount_to_comisariato,
    employee_comisariato_balance,
)
from .services import _q2


class CobrarPagarError(ValueError):
    """Error de dominio del cobro negociado (se mapea a 422 en la vista)."""


# --- Préstamo personal (portfolio.Credit) — por cédula, FIFO -----------------------------------

def _open_credits_for(*, company, worker_code: str = "", cedula: str = "") -> list[Credit]:
    """Créditos abiertos del trabajador en la finca, por **carnet** (primario) o **cédula** (respaldo)."""
    wc = (worker_code or "").strip().upper()
    ced = (cedula or "").strip().upper()
    if not wc and not ced:
        return []
    credits = list(Credit.objects.filter(company=company).select_related("borrower_party").order_by("id"))

    def _collect(predicate) -> list[Credit]:
        out: list[Credit] = []
        for c in credits:
            bp = c.borrower_party
            if not bp or c.outstanding_amount <= 0:
                continue
            if predicate(bp):
                out.append(c)
        return out

    # Carnet primero (clave del holding); cédula como respaldo.
    if wc:
        hits = _collect(lambda bp: bool(bp.worker_code) and bp.worker_code.strip().upper() == wc)
        if hits:
            return hits
    if ced:
        return _collect(lambda bp: bool(bp.national_id) and bp.national_id.strip().upper() == ced)
    return []


def employee_loan_balance(*, company, worker_code: str = "", cedula: str = "") -> tuple[Decimal, list[Credit]]:
    credits = _open_credits_for(company=company, worker_code=worker_code, cedula=cedula)
    return _q2(sum((c.outstanding_amount for c in credits), Decimal("0.00"))), credits


# Etiqueta de origen del abono: marca las deducciones creadas POR el cobro del CO-PA, para que la
# rectificación reverse solo esas (y no las del auto-armado de la planilla).
COPA_SOURCE = "COPA"


def _apply_amount_to_loan(
    *, request, actor, entry: PayrollEntry, credits: list[Credit], amount: Decimal, source: str = ""
) -> Decimal:
    remaining = _q2(amount)
    applied = Decimal("0.00")
    for c in credits:
        if remaining <= 0:
            break
        amt = _q2(min(c.outstanding_amount, remaining))
        if amt <= 0:
            continue
        register_payroll_loan_deduction(
            request=request, actor=actor, entry=entry, credit_id=c.id, amount=amt, credit_type="CREDIT",
            source=source,
        )
        applied += amt
        remaining -= amt
    return _q2(applied)


# --- Orquestador --------------------------------------------------------------------------------

def cobrar_y_pagar(
    *,
    request,
    actor,
    entry: PayrollEntry,
    abono_comisariato,
    abono_prestamo,
    payment_method: str,
    idempotency_key: str = "",
) -> dict[str, Any]:
    """Negocia los abonos parciales + paga el neto a entregar. Atómico e idempotente.

    - El abono de cada tipo es 0..saldo de esa deuda; la suma no puede dejar el neto negativo.
    - Setea `store_credit_deduction`/`loan_payment` del entry con lo negociado y recalcula el neto.
    - Abona cada deuda (FIFO) y registra el pago en efectivo del neto a entregar.
    """
    key = (idempotency_key or "").strip()
    if key:
        existing = entry.payments.filter(reference=key).first()
        if existing is not None:
            return _result(entry, existing)  # reintento seguro (no re-aplica)

    abono_com = _q2(Decimal(str(abono_comisariato or 0)))
    abono_pre = _q2(Decimal(str(abono_prestamo or 0)))
    if abono_com < 0 or abono_pre < 0:
        raise CobrarPagarError("Los abonos no pueden ser negativos.")

    company = entry.sheet.period.company
    com_balance, account = employee_comisariato_balance(
        collecting_company=company, worker_code=entry.worker_code, cedula=entry.cedula
    )
    pre_balance, credits = employee_loan_balance(
        company=company, worker_code=entry.worker_code, cedula=entry.cedula
    )

    if abono_com > com_balance:
        raise CobrarPagarError(f"El abono al comisariato ({abono_com}) excede el saldo ({com_balance}).")
    if abono_pre > pre_balance:
        raise CobrarPagarError(f"El abono al préstamo ({abono_pre}) excede el saldo ({pre_balance}).")

    # Neto disponible = devengado − deducciones legales/otras (sin los cobros internos negociables).
    non_cobro = _q2(
        entry.inss_laboral + entry.ir_amount + entry.food_deduction
        + entry.advance_deduction + entry.other_deductions
    )
    available = _q2(entry.total_devengado - non_cobro)
    if abono_com + abono_pre > available:
        raise CobrarPagarError(
            f"Los abonos ({_q2(abono_com + abono_pre)}) dejan el neto a entregar negativo "
            f"(disponible {available})."
        )

    with transaction.atomic():
        entry.store_credit_deduction = abono_com
        entry.loan_payment = abono_pre
        entry.total_deductions = _q2(non_cobro + abono_com + abono_pre)
        entry.net_to_pay = _q2(entry.total_devengado - entry.total_deductions)
        entry.save(update_fields=["store_credit_deduction", "loan_payment", "total_deductions", "net_to_pay"])

        if abono_com > 0 and account is not None:
            apply_amount_to_comisariato(
                request=request, actor=actor, entry=entry, account=account, amount=abono_com,
                source=COPA_SOURCE,
            )
        if abono_pre > 0 and credits:
            _apply_amount_to_loan(
                request=request, actor=actor, entry=entry, credits=credits, amount=abono_pre,
                source=COPA_SOURCE,
            )

        payment = None
        if entry.net_to_pay > 0:
            payment = register_payroll_payment_idempotent(
                request=request, actor=actor, entry=entry, payment_method=payment_method,
                amount=entry.net_to_pay, idempotency_key=key,
            )
    return _result(entry, payment)


def rectificar_cobro(
    *,
    request,
    actor,
    entry: PayrollEntry,
    abono_comisariato,
    abono_prestamo,
    payment_method: str,
    motivo: str,
    idempotency_key: str = "",
) -> dict[str, Any]:
    """Rectifica un cobro YA aplicado: anula el recibo previo y reemite con los montos corregidos.

    Caso del dueño: el pagador puso 200 y eran 2000. Hay que (1) reversar los abonos del cobro
    (devolviendo el saldo a la deuda vía la reversa GLOBAL del portfolio), (2) anular el/los pago(s)
    en efectivo del entry, y (3) re-cobrar con el monto correcto. Atómico: o queda todo corregido o
    nada. El documento legal NO se toca (la rectificación es interna de empresa).

    Devuelve el resultado del nuevo cobro + `recibo_anulado` (id del pago previo) + `motivo`, para que
    el recibo nuevo se imprima como RECTIFICACIÓN que anula el anterior.
    """
    motivo = (motivo or "").strip()
    if not motivo:
        raise CobrarPagarError("El motivo de la rectificación es obligatorio.")

    with transaction.atomic():
        # 1) Recibo a anular = último pago del entry (número de ticket previo).
        prev_payments = list(entry.payments.order_by("id"))
        recibo_anulado = prev_payments[-1].id if prev_payments else None

        # 2) Reversar los abonos del COBRO (etiquetados COPA, aún no reversados) → restaura saldos.
        for ded in entry.loan_deductions.filter(notes=COPA_SOURCE).order_by("id"):
            reverse_payroll_loan_deduction(
                request=request, actor=actor, deduction=ded, reason=f"rectificación: {motivo}",
            )

        # 3) Anular el/los pago(s) en efectivo del entry (se reemite el correcto).
        for p in prev_payments:
            write_event(
                request=request,
                module="NOMINA",
                event_type="NOMINA_PAYMENT_VOIDED",
                reason_code="NOMINA_OK",
                actor_user=actor,
                subject_type="PAYROLL_PAYMENT",
                subject_id=str(p.id),
                metadata={
                    "entry_id": entry.id,
                    "amount": str(p.amount),
                    "payment_method": p.payment_method,
                    "reason": motivo,
                },
            )
            p.delete()

        # Limpiar el cobro previo en el entry antes de re-cobrar (cobrar_y_pagar lo recalcula).
        entry.store_credit_deduction = Decimal("0.00")
        entry.loan_payment = Decimal("0.00")
        entry.save(update_fields=["store_credit_deduction", "loan_payment"])

        # 4) Re-cobrar con los montos corregidos (idempotency_key nuevo, sin colisión con lo anulado).
        result = cobrar_y_pagar(
            request=request,
            actor=actor,
            entry=entry,
            abono_comisariato=abono_comisariato,
            abono_prestamo=abono_prestamo,
            payment_method=payment_method,
            idempotency_key=idempotency_key,
        )

    result["recibo_anulado"] = recibo_anulado
    result["motivo"] = motivo
    return result


def deudas_por_planilla(*, period) -> list[dict[str, Any]]:
    """Saldos de deuda interna (comisariato + préstamo) por entrada de las planillas del período.

    Lo consume el CO-PA para mostrar la deuda total y pre-cargar el abono negociado. El cruce se hace
    por **carnet** (primario) y **cédula** (respaldo). BATCHEADO: en vez de N×escaneos por entry (lento
    a 200 trabajadores), arma los saldos con un puñado de consultas y resuelve cada entry por mapa.
    """
    from collections import defaultdict

    from django.db.models import Q

    from apps.kernels.nomina.models import PayrollSheet
    from apps.kernels.portfolio.models import Receivable
    from apps.modulos.org.models import IntercompanyRelationship

    from .models import CustomerCreditAccount, CustomerSegment
    from .services import TERMINAL_STATUSES

    company = period.company
    sheet_ids = list(PayrollSheet.objects.filter(period=period).values_list("id", flat=True))
    entries = list(
        PayrollEntry.objects.filter(sheet_id__in=sheet_ids).only("id", "cedula", "worker_code", "employee_id")
    )

    def _k(v: str) -> str:
        return (v or "").strip().upper()

    # --- COMISARIATO (cross-company): solo comisariatos con relación CXC activa con la finca ---
    cxc_partners: set[int] = set()
    for a_id, b_id in (
        IntercompanyRelationship.objects.filter(
            is_active=True, relationship_type=IntercompanyRelationship.RelationshipType.CXC
        )
        .filter(Q(company_a=company) | Q(company_b=company))
        .values_list("company_a_id", "company_b_id")
    ):
        cxc_partners.add(b_id if a_id == company.id else a_id)
    cxc_partners.discard(company.id)

    com_by_wc: dict[str, Decimal] = {}
    com_by_ced: dict[str, Decimal] = {}
    if cxc_partners:
        accounts = list(
            CustomerCreditAccount.objects.filter(
                segment=CustomerSegment.EMPLOYEE, is_active=True,
                collecting_company=company, company_id__in=cxc_partners,
            ).select_related("party")
        )
        bal_by_party: dict[int, Decimal] = defaultdict(lambda: Decimal("0.00"))
        party_ids = [a.party_id for a in accounts]
        if party_ids:
            for r in (
                Receivable.objects.filter(company_id__in=cxc_partners, party_id__in=party_ids)
                .exclude(status__in=TERMINAL_STATUSES)
            ):
                bal_by_party[r.party_id] += r.outstanding_amount
        # Primera cuenta por clave (igual que find_employee_account, que devuelve la primera).
        for a in accounts:
            saldo = _q2(bal_by_party.get(a.party_id, Decimal("0.00")))
            wc = _k(a.party.worker_code)
            ced = _k(a.party.national_id)
            if wc and wc not in com_by_wc:
                com_by_wc[wc] = saldo
            if ced and ced not in com_by_ced:
                com_by_ced[ced] = saldo

    # --- PRÉSTAMO (intra-finca): Σ Credits abiertos del borrower por carnet/cédula ---
    loan_by_wc: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    loan_by_ced: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for c in Credit.objects.filter(company=company).select_related("borrower_party"):
        bp = c.borrower_party
        if not bp or c.outstanding_amount <= 0:
            continue
        wc = _k(bp.worker_code)
        ced = _k(bp.national_id)
        if wc:
            loan_by_wc[wc] += c.outstanding_amount
        if ced:
            loan_by_ced[ced] += c.outstanding_amount

    out: list[dict[str, Any]] = []
    for e in entries:
        wc = _k(e.worker_code)
        ced = _k(e.cedula)
        # Carnet primero (si hay cuenta/crédito por carnet, usar ese aunque sea 0); cédula como respaldo.
        com = com_by_wc.get(wc) if wc and wc in com_by_wc else (com_by_ced.get(ced) if ced else None)
        loan = loan_by_wc.get(wc) if wc and wc in loan_by_wc else (loan_by_ced.get(ced) if ced else None)
        out.append(
            {
                "entry_id": e.id,
                "cedula": e.cedula,
                "worker_code": e.worker_code,
                "comisariato_saldo": str(_q2(com if com is not None else Decimal("0.00"))),
                "prestamo_saldo": str(_q2(loan if loan is not None else Decimal("0.00"))),
            }
        )
    return out


def _result(entry: PayrollEntry, payment) -> dict[str, Any]:
    return {
        "payment_id": getattr(payment, "id", None),
        "neto_entregado": str(_q2(entry.net_to_pay)),
        "abono_comisariato": str(_q2(entry.store_credit_deduction)),
        "abono_prestamo": str(_q2(entry.loan_payment)),
    }
