"""Orquestador de venta POS (mostrador): escaneo → precio del catálogo → contado o crédito.

Compone los kernels existentes SIN duplicar lógica:
- facturacion.create_draft / issue_doc — factura real (fiscal A/B) que baja inventario FEFO/FIFO.
- facturacion.create_payment — pagos múltiples por documento (recalcula UNPAID/PARTIAL/PAID).
- payments.post_cash_movement — el efectivo entra a la sesión de caja ABIERTA del cajero.
- comisariato.sell_on_credit — crédito: límite C-01 + CxC automática con vencimiento real.

Invariante anti-fraude: el PRECIO lo resuelve el servidor desde InventoryItem.sale_price;
un precio distinto al de catálogo exige el permiso sales.pos.price_override.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.contrib.auth import get_user_model
from django.core import signing
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.crypto import get_random_string

from apps.kernels.facturacion.models import BillingDocument, DocStatus, DocType
from apps.kernels.facturacion.services import BillingError, create_draft, create_payment, issue_doc
from apps.kernels.inventarios.models import InventoryItem
from apps.kernels.inventarios.pricing import resolve_sale_price
from apps.kernels.inventarios.services import InsufficientStockError
from apps.kernels.payments.models import CashMovement, CashSession
from apps.kernels.payments.services import (
    capture_payment_intent,
    create_payment_intent,
    post_cash_movement,
)
from apps.kernels.portfolio.models import ObligationStatus, Receivable
from apps.kernels.portfolio.services import allocate_payment_to_obligation
from apps.modulos.audit.writer import write_event
from apps.modulos.comisariato.models import CustomerCreditAccount
from apps.modulos.comisariato.services import available_credit, sell_on_credit
from apps.modulos.common.tender import TenderPaymentMethod
from apps.modulos.parties.models import Party
from apps.modulos.rbac.selectors import get_effective_permissions_for_scope
from apps.modulos.ventas.models import SelfServiceStatus, SelfServiceTicket

# Métodos aceptados en mostrador para venta de contado.
CONTADO_METHODS = frozenset(
    {
        TenderPaymentMethod.CASH,
        TenderPaymentMethod.TRANSFER,
        TenderPaymentMethod.CARD,
        TenderPaymentMethod.CHECK,
    }
)

_CENT = Decimal("0.01")


def _q2(x: Decimal) -> Decimal:
    return Decimal(x).quantize(_CENT)


class SalesError(Exception):
    """Errores de negocio de la venta POS; el código viaja como detail (422)."""


# --- Autorización de supervisor en caja (override de precio/descuento) -------------
#
# Cuando el cajero NO tiene `sales.pos.price_override`, un supervisor que SÍ lo tiene
# autoriza en el momento (reautenticándose). El backend emite un GRANT firmado y
# efímero (stateless, sin tabla): viaja en la siguiente venta y habilita el override
# SOLO para esa caja, esa sucursal y ese cajero. Espejo del patrón de firma del 2FA.
POS_OVERRIDE_SALT = "ventas.pos-override"
POS_OVERRIDE_MAX_AGE = 300  # segundos (5 min): se autoriza y se cobra enseguida.


def grant_pos_override(
    *, request, actor, supervisor_username: str, supervisor_password: str, reason: str
) -> dict[str, Any]:
    """Un supervisor autoriza, en la caja del cajero, un override de precio/descuento.

    Verifica credenciales del supervisor + que tenga `sales.pos.price_override` en el
    scope (company/branch). Devuelve un grant firmado que la venta debe adjuntar.
    """
    company = request.company
    branch = request.branch
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise SalesError("SALES_OVERRIDE_REASON_REQUIRED")

    # Valida la contraseña directamente (sin pasar por los backends/axes): así un typo
    # en caja no bloquea el login real del supervisor y no exige objeto `request`.
    supervisor = (
        get_user_model().objects
        .filter(username=(supervisor_username or "").strip())
        .first()
    )
    if (
        supervisor is None
        or not supervisor.is_active
        or not supervisor.check_password(supervisor_password or "")
    ):
        raise SalesError("SALES_OVERRIDE_BAD_CREDENTIALS")
    if supervisor.id == getattr(actor, "id", None):
        # El cajero no se autoriza a sí mismo: lo autoriza un segundo usuario (SoD).
        raise SalesError("SALES_OVERRIDE_SELF")

    perms = get_effective_permissions_for_scope(supervisor, company=company, branch=branch)
    if "*" not in perms and "sales.pos.price_override" not in perms:
        raise SalesError("SALES_OVERRIDE_NOT_AUTHORIZED")

    grant = signing.dumps(
        {"c": company.id, "b": branch.id, "cashier": actor.id, "sup": supervisor.id},
        salt=POS_OVERRIDE_SALT,
    )
    write_event(
        request=request, module="SALES", event_type="SALES_POS_OVERRIDE_GRANTED",
        reason_code="SALES_OK", actor_user=supervisor,
        subject_type="SALES_POS_OVERRIDE", subject_id=str(actor.id),
        metadata={"cashier_id": actor.id, "reason": reason},
    )
    nombre = supervisor.get_full_name() or supervisor.get_username()
    return {"grant": grant, "expires_in": POS_OVERRIDE_MAX_AGE, "authorized_by": nombre,
            "authorized_by_id": supervisor.id}


def verify_pos_override_grant(*, grant: str, company, branch, cashier) -> int:
    """Valida el grant y devuelve el id del supervisor que autorizó (o lanza SalesError)."""
    try:
        payload = signing.loads(grant, salt=POS_OVERRIDE_SALT, max_age=POS_OVERRIDE_MAX_AGE)
    except signing.SignatureExpired:
        raise SalesError("SALES_OVERRIDE_EXPIRED")
    except signing.BadSignature:
        raise SalesError("SALES_OVERRIDE_INVALID")
    if (
        payload.get("c") != company.id
        or payload.get("b") != branch.id
        or payload.get("cashier") != getattr(cashier, "id", None)
    ):
        raise SalesError("SALES_OVERRIDE_INVALID")
    return int(payload["sup"])


def _customer_segment(company, party_id: int | None) -> str:
    """Segmento del cliente si tiene cuenta de comisariato (EMPLOYEE/PRODUCER/PUBLIC).
    Aplica también de contado: el segmento es del CLIENTE, no del método de pago."""
    if not party_id:
        return ""
    account = (
        CustomerCreditAccount.objects
        .filter(company=company, party_id=party_id, is_active=True)
        .only("segment").first()
    )
    return account.segment if account else ""


def _catalog_price_for_qty(
    item: InventoryItem, qty: Decimal, *, party=None, segment: str = "", currency: str = "NIO",
) -> Decimal | None:
    """Precio de catálogo: listas de precios (party > segmento) > mayoreo > base.
    La precedencia completa vive en el kernel (`inventarios.pricing.resolve_sale_price`)."""
    return resolve_sale_price(
        company=item.company, item=item, qty=qty,
        party=party, segment=segment, currency=currency,
    )


def _resolve_lines(
    *,
    company,
    warehouse_id: int,
    lines: list[dict],
    allow_price_override: bool,
    party=None,
    segment: str = "",
    currency: str = "NIO",
) -> list[dict]:
    """Construye las líneas del kernel con precio de catálogo resuelto en servidor."""
    item_ids = [int(ln["inventory_item_id"]) for ln in lines]
    items = {
        it.id: it
        for it in InventoryItem.objects.filter(company=company, id__in=item_ids, is_active=True)
    }

    kernel_lines: list[dict] = []
    for ln in lines:
        item = items.get(int(ln["inventory_item_id"]))
        if item is None:
            raise SalesError("SALES_ITEM_NOT_FOUND")

        qty = Decimal(str(ln["quantity"]))
        catalog_price = _catalog_price_for_qty(
            item, qty, party=party, segment=segment, currency=currency,
        )

        provided = ln.get("unit_price")
        if provided is None:
            if catalog_price is None:
                # Sin precio de catálogo y sin override: la caja no puede inventar precios.
                raise SalesError("SALES_ITEM_WITHOUT_PRICE")
            unit_price = catalog_price
        else:
            provided = Decimal(str(provided))
            if catalog_price is None or provided != catalog_price:
                if not allow_price_override:
                    raise SalesError("SALES_PRICE_OVERRIDE_FORBIDDEN")
            unit_price = provided

        # El descuento tambien altera el precio efectivo: mismo permiso que el override.
        discount = Decimal(str(ln.get("discount_pct") or "0"))
        if discount > 0 and not allow_price_override:
            raise SalesError("SALES_PRICE_OVERRIDE_FORBIDDEN")

        kernel_lines.append(
            {
                "description": item.name,
                "quantity": str(ln["quantity"]),
                "unit_price": str(unit_price),
                "tax_rate": str(item.default_tax_rate),
                "discount_pct": str(ln.get("discount_pct") or "0"),
                "inventory_item_id": item.id,
                "warehouse_id": int(ln.get("warehouse_id") or warehouse_id),
            }
        )
    return kernel_lines


def _open_cash_session(*, company, branch, actor) -> CashSession:
    """Sesión de caja abierta del cajero (o la única abierta de la sucursal)."""
    own = (
        CashSession.objects.filter(
            company=company, branch=branch, status=CashSession.Status.OPEN, opened_by=actor
        )
        .order_by("-id")
        .first()
    )
    if own is not None:
        return own
    opened = list(
        CashSession.objects.filter(company=company, branch=branch, status=CashSession.Status.OPEN)[:2]
    )
    if len(opened) == 1:
        return opened[0]
    raise SalesError("SALES_NO_OPEN_CASH_SESSION")


def pos_sale(
    *,
    request,
    actor,
    warehouse_id: int,
    lines: list[dict],
    payments: list[dict],
    idempotency_key: str,
    customer_party_id: int | None = None,
    customer_name: str = "",
    currency: str = "NIO",
    is_fiscal: bool = True,
    allow_price_override: bool = False,
    self_service_code: str = "",
) -> dict[str, Any]:
    """Venta de mostrador completa e idempotente (por `idempotency_key`).

    Si viene `self_service_code`, la venta cobra un pre-ticket de auto-facturación:
    se marca CHARGED en la MISMA transacción (si el cobro falla, el ticket sigue OPEN).
    """
    if not idempotency_key:
        raise SalesError("SALES_IDEMPOTENCY_REQUIRED")
    if not lines:
        raise SalesError("SALES_LINES_REQUIRED")
    if not payments:
        raise SalesError("SALES_PAYMENTS_REQUIRED")

    company = request.company
    branch = request.branch

    methods = [str(p["method"]) for p in payments]
    is_credit = TenderPaymentMethod.CREDIT in methods
    if is_credit and len(payments) > 1:
        # v1: el crédito no se mezcla con otros métodos en la misma venta.
        raise SalesError("SALES_CREDIT_MUST_BE_ONLY_PAYMENT")
    if not is_credit and any(m not in CONTADO_METHODS for m in methods):
        raise SalesError("SALES_INVALID_PAYMENT_METHOD")

    customer_party = None
    if customer_party_id:
        customer_party = Party.objects.filter(company=company, pk=customer_party_id).first()
    kernel_lines = _resolve_lines(
        company=company, warehouse_id=warehouse_id, lines=lines,
        allow_price_override=allow_price_override,
        party=customer_party,
        segment=_customer_segment(company, customer_party_id),
        currency=currency,
    )

    # ------------------------------------------------------------------ crédito
    if is_credit:
        if not customer_party_id:
            raise SalesError("SALES_CREDIT_REQUIRES_CUSTOMER")
        account = CustomerCreditAccount.objects.filter(
            company=company, party_id=customer_party_id, is_active=True
        ).first()
        if account is None:
            raise SalesError("SALES_NO_CREDIT_ACCOUNT")

        with transaction.atomic():
            result = sell_on_credit(
                request=request, actor=actor, account=account, warehouse_id=warehouse_id,
                lines=kernel_lines, reference_code=idempotency_key,
                currency=currency, is_fiscal=is_fiscal,
            )
            if self_service_code:
                _charge_self_service_ticket(
                    request=request, actor=actor, company=company,
                    code=self_service_code, doc_id=int(result["doc_id"]),
                )
        result["sale_type"] = "CREDIT"
        return result

    # ------------------------------------------------------------------ contado
    with transaction.atomic():
        res = create_draft(
            request=request, actor=actor, doc_type=DocType.INVOICE, series="A",
            currency=currency,
            customer_name=customer_name or "Consumidor final",
            customer_ref="", is_fiscal=is_fiscal,
            customer_party_id=customer_party_id, lines=kernel_lines,
            idempotency_key=f"pos-sale:{company.id}:{idempotency_key}",
            payment_method=methods[0] if len(set(methods)) == 1 else TenderPaymentMethod.MIXED,
            source_module="SALES", source_type="POS_SALE", source_id=idempotency_key,
        )
        doc = BillingDocument.objects.select_for_update().get(id=res.doc_id)

        if doc.status == DocStatus.ISSUED:
            # Reentrada idempotente: ya emitida y cobrada; no re-cobra ni re-despacha.
            # El ticket de auto-factura también se reconcilia (cubre el crash entre
            # emisión y marca: si quedó OPEN, esta reentrada lo cierra).
            if self_service_code:
                _charge_self_service_ticket(
                    request=request, actor=actor, company=company,
                    code=self_service_code, doc_id=doc.id,
                )
            return {
                "sale_type": "CASH",
                "doc_id": doc.id,
                "number": doc.number,
                "total": str(doc.total),
                "payment_status": doc.payment_status,
                "duplicate": True,
            }

        paid_total = _q2(sum((Decimal(str(p["amount"])) for p in payments), Decimal("0.00")))
        if paid_total != _q2(Decimal(doc.total)):
            # Rollback total: el borrador recién creado se descarta.
            raise SalesError("SALES_PAYMENTS_MISMATCH")

        cash_total = _q2(
            sum(
                (Decimal(str(p["amount"])) for p in payments if p["method"] == TenderPaymentMethod.CASH),
                Decimal("0.00"),
            )
        )
        session = _open_cash_session(company=company, branch=branch, actor=actor) if cash_total > 0 else None

        try:
            issue_doc(
                request=request, actor=actor, doc_id=doc.id, apply_inventory=True,
                idempotency_key=f"pos-issue:{doc.id}",
            )
        except InsufficientStockError:
            # BUG-6: sin existencias el kernel de inventario lanza un ValueError tipado.
            # Se traduce a error de dominio para que el POS responda 422 con envelope
            # legible (antes propagaba un 500 con traceback crudo). El atomic descarta
            # el borrador recién creado.
            raise SalesError("SALES_INSUFFICIENT_STOCK")

        last_payment_status = doc.payment_status
        for i, p in enumerate(payments):
            pay = create_payment(
                request=request, actor=actor, doc_id=doc.id,
                payment_method=str(p["method"]), amount=Decimal(str(p["amount"])),
                currency=currency, reference=f"pos-sale:{idempotency_key}:{i}",
            )
            last_payment_status = pay.payment_status

        cash_movement_id = None
        if session is not None:
            movement = post_cash_movement(
                request=request, actor=actor, session_id=session.id,
                movement_type=CashMovement.MovementType.INCOME, amount=cash_total,
                reference=f"pos-sale:{doc.id}", reason="POS_SALE",
                idempotency_key=f"pos-cash:{doc.id}",
            )
            cash_movement_id = movement.id

        if self_service_code:
            _charge_self_service_ticket(
                request=request, actor=actor, company=company,
                code=self_service_code, doc_id=doc.id,
            )

        doc.refresh_from_db()
        return {
            "sale_type": "CASH",
            "doc_id": doc.id,
            "number": doc.number,
            "total": str(doc.total),
            "payment_status": last_payment_status,
            "cash_movement_id": cash_movement_id,
            "cash_session_id": session.id if session is not None else None,
            "duplicate": False,
        }


# --------------------------------------------------------------------------- auto-factura
# Pre-tickets de auto-facturación: el cliente arma su compra solo en una tableta
# (usuario kiosko) y la caja la cobra después por código corto. El pre-ticket NO
# reserva stock ni fija precios; el estimado es con precio PÚBLICO (sin cliente) y
# la caja re-resuelve con el cliente real al cobrar.

SELF_SERVICE_TTL_HOURS = 8
# Sin 0/O/1/I/L para dictarlo o teclearlo sin ambigüedad.
_SS_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def _ss_ticket_payload(ticket: SelfServiceTicket, lines: list[dict]) -> dict[str, Any]:
    return {
        "code": ticket.code,
        "status": ticket.status,
        "currency": ticket.currency,
        "expires_at": ticket.expires_at.isoformat(),
        "estimated_subtotal": str(ticket.estimated_subtotal),
        "estimated_tax": str(ticket.estimated_tax),
        "estimated_total": str(ticket.estimated_total),
        "lines": lines,
        "charged_doc_id": ticket.charged_doc_id,
    }


def _resolve_ss_lines(*, company, lines: list[dict], currency: str) -> tuple[list[dict], Decimal, Decimal]:
    """Resuelve líneas del pre-ticket con precio público ACTUAL del catálogo.

    Devuelve (líneas_resueltas, subtotal, iva). Un artículo desactivado o sin precio
    después de creado el ticket sale con ``unavailable: True`` (la caja decide).
    """
    item_ids = [int(ln["inventory_item_id"]) for ln in lines]
    items = {
        it.id: it
        for it in InventoryItem.objects.filter(company=company, id__in=item_ids)
    }
    resolved: list[dict] = []
    subtotal = Decimal("0.00")
    tax = Decimal("0.00")
    for ln in lines:
        item = items.get(int(ln["inventory_item_id"]))
        qty = Decimal(str(ln["quantity"]))
        price = None
        if item is not None and item.is_active:
            price = _catalog_price_for_qty(item, qty, currency=currency)
        if item is None or price is None:
            resolved.append(
                {
                    "inventory_item_id": int(ln["inventory_item_id"]),
                    "quantity": str(qty),
                    "name": item.name if item is not None else "",
                    "sku": item.sku if item is not None else "",
                    "unit_price": None,
                    "line_total": None,
                    "unavailable": True,
                }
            )
            continue
        line_subtotal = _q2(qty * price)
        line_tax = _q2(line_subtotal * Decimal(item.default_tax_rate))
        subtotal += line_subtotal
        tax += line_tax
        resolved.append(
            {
                "inventory_item_id": item.id,
                "quantity": str(qty),
                "name": item.name,
                "sku": item.sku,
                "unit_price": str(_q2(price)),
                "line_total": str(_q2(line_subtotal + line_tax)),
                "unavailable": False,
            }
        )
    return resolved, _q2(subtotal), _q2(tax)


def create_self_service_ticket(
    *, request, actor, lines: list[dict], currency: str = "NIO"
) -> dict[str, Any]:
    """Crea el pre-ticket desde la tableta; todo artículo debe tener precio público."""
    if not lines:
        raise SalesError("SALES_LINES_REQUIRED")

    company = request.company
    branch = request.branch

    resolved, subtotal, tax = _resolve_ss_lines(company=company, lines=lines, currency=currency)
    if any(ln["unavailable"] for ln in resolved):
        # Al CREAR no se aceptan artículos sin precio: el kiosko no inventa precios.
        raise SalesError("SALES_ITEM_WITHOUT_PRICE")

    stored_lines = [
        {"inventory_item_id": ln["inventory_item_id"], "quantity": ln["quantity"]}
        for ln in resolved
    ]
    expires_at = timezone.now() + timedelta(hours=SELF_SERVICE_TTL_HOURS)

    ticket = None
    for _attempt in range(5):
        code = get_random_string(6, _SS_CODE_ALPHABET)
        try:
            with transaction.atomic():
                ticket = SelfServiceTicket.objects.create(
                    company=company, branch=branch, code=code,
                    lines=stored_lines, currency=currency,
                    estimated_subtotal=subtotal, estimated_tax=tax,
                    estimated_total=_q2(subtotal + tax),
                    expires_at=expires_at, created_by=actor,
                )
            break
        except IntegrityError:
            continue  # código en uso por otro ticket OPEN: reintenta con otro
    if ticket is None:
        raise SalesError("SALES_SELF_SERVICE_CODE_EXHAUSTED")

    write_event(
        request=request, module="SALES", event_type="SALES_SELFSERVICE_CREATED",
        reason_code="SALES_OK", actor_user=actor,
        subject_type="SALES_SS_TICKET", subject_id=str(ticket.id),
        metadata={
            "code": ticket.code, "lines": len(stored_lines),
            "estimated_total": str(ticket.estimated_total),
        },
    )
    return _ss_ticket_payload(ticket, resolved)


def _ss_ticket_for_code(*, company, code: str) -> SelfServiceTicket | None:
    """Ticket por código: el OPEN si existe; si no, el cerrado más reciente."""
    qs = SelfServiceTicket.objects.filter(company=company, code=code.strip().upper())
    return (
        qs.filter(status=SelfServiceStatus.OPEN).first()
        or qs.order_by("-created_at").first()
    )


def _expire_if_due(ticket: SelfServiceTicket) -> bool:
    """Expiración lazy: marca EXPIRED si el ticket OPEN ya venció."""
    if ticket.status == SelfServiceStatus.OPEN and ticket.expires_at <= timezone.now():
        ticket.status = SelfServiceStatus.EXPIRED
        ticket.save(update_fields=["status"])
        return True
    return False


def get_self_service_ticket(*, company, code: str) -> dict[str, Any]:
    """Carga el pre-ticket para la caja, con precios públicos re-resueltos HOY."""
    ticket = _ss_ticket_for_code(company=company, code=code)
    if ticket is None:
        raise SalesError("SALES_SELF_SERVICE_NOT_FOUND")
    if _expire_if_due(ticket):
        raise SalesError("SALES_SELF_SERVICE_EXPIRED")
    if ticket.status != SelfServiceStatus.OPEN:
        raise SalesError("SALES_SELF_SERVICE_NOT_OPEN")

    resolved, subtotal, tax = _resolve_ss_lines(
        company=company, lines=ticket.lines, currency=ticket.currency
    )
    payload = _ss_ticket_payload(ticket, resolved)
    # El estimado que ve el cajero es el ACTUAL, no el del momento de creación.
    payload["estimated_subtotal"] = str(subtotal)
    payload["estimated_tax"] = str(tax)
    payload["estimated_total"] = str(_q2(subtotal + tax))
    return payload


def cancel_self_service_ticket(*, request, actor, code: str) -> dict[str, Any]:
    """Cancela el pre-ticket (kiosko se arrepiente). Idempotente sobre CANCELLED."""
    with transaction.atomic():
        ticket = (
            SelfServiceTicket.objects.select_for_update()
            .filter(company=request.company, code=code.strip().upper())
            .order_by("-created_at")
            .first()
        )
        if ticket is None:
            raise SalesError("SALES_SELF_SERVICE_NOT_FOUND")
        if ticket.status == SelfServiceStatus.CANCELLED:
            return {"ok": True, "code": ticket.code, "already_cancelled": True}
        _expire_if_due(ticket)
        if ticket.status != SelfServiceStatus.OPEN:
            raise SalesError("SALES_SELF_SERVICE_NOT_OPEN")
        ticket.status = SelfServiceStatus.CANCELLED
        ticket.cancelled_at = timezone.now()
        ticket.save(update_fields=["status", "cancelled_at"])

    write_event(
        request=request, module="SALES", event_type="SALES_SELFSERVICE_CANCELLED",
        reason_code="SALES_OK", actor_user=actor,
        subject_type="SALES_SS_TICKET", subject_id=str(ticket.id),
        metadata={"code": ticket.code},
    )
    return {"ok": True, "code": ticket.code, "already_cancelled": False}


def _charge_self_service_ticket(*, request, actor, company, code: str, doc_id: int) -> None:
    """Marca el pre-ticket CHARGED dentro de la transacción de la venta.

    Reentrada idempotente: si ya está CHARGED con el MISMO doc, no hace nada (cubre
    el reintento de pos_sale). Scoped por company: un código ajeno es NOT_FOUND.
    """
    ticket = (
        SelfServiceTicket.objects.select_for_update()
        .filter(company=company, code=code.strip().upper())
        .order_by("-created_at")
        .first()
    )
    # Preferir el OPEN si el código fue reciclado.
    open_ticket = (
        SelfServiceTicket.objects.select_for_update()
        .filter(
            company=company, code=code.strip().upper(), status=SelfServiceStatus.OPEN
        )
        .first()
    )
    if open_ticket is not None:
        ticket = open_ticket
    if ticket is None:
        raise SalesError("SALES_SELF_SERVICE_NOT_FOUND")
    if ticket.status == SelfServiceStatus.CHARGED and ticket.charged_doc_id == doc_id:
        return
    if _expire_if_due(ticket):
        raise SalesError("SALES_SELF_SERVICE_EXPIRED")
    if ticket.status != SelfServiceStatus.OPEN:
        raise SalesError("SALES_SELF_SERVICE_NOT_OPEN")

    ticket.status = SelfServiceStatus.CHARGED
    ticket.charged_doc_id = doc_id
    ticket.charged_at = timezone.now()
    ticket.save(update_fields=["status", "charged_doc_id", "charged_at"])
    write_event(
        request=request, module="SALES", event_type="SALES_SELFSERVICE_CHARGED",
        reason_code="SALES_OK", actor_user=actor,
        subject_type="SALES_SS_TICKET", subject_id=str(ticket.id),
        metadata={"code": ticket.code, "doc_id": doc_id},
    )


def collect_receivable(
    *,
    request,
    actor,
    receivable_id: int,
    amount: Decimal,
    method: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Cobro de una CxC en caja: intent capturado → aplicación en cartera → efectivo a la sesión.

    Si la CxC nació de una factura (BILLING_DOC), también registra el abono en el
    documento para que su payment_status (UNPAID/PARTIAL/PAID) refleje el cobro.
    """
    if not idempotency_key:
        raise SalesError("SALES_IDEMPOTENCY_REQUIRED")
    if method not in CONTADO_METHODS:
        raise SalesError("SALES_INVALID_PAYMENT_METHOD")

    company = request.company
    branch = request.branch
    amount = _q2(Decimal(str(amount)))
    if amount <= 0:
        raise SalesError("SALES_AMOUNT_INVALID")

    with transaction.atomic():
        rec = (
            Receivable.objects.select_for_update()
            .filter(id=receivable_id, company=company)
            .first()
        )
        if rec is None:
            raise SalesError("SALES_RECEIVABLE_NOT_FOUND")
        if rec.status in (ObligationStatus.PAID, ObligationStatus.WRITTEN_OFF, ObligationStatus.CANCELLED):
            raise SalesError("SALES_RECEIVABLE_NOT_OPEN")
        if amount > _q2(Decimal(rec.outstanding_amount)):
            raise SalesError("SALES_AMOUNT_EXCEEDS_OUTSTANDING")

        session = (
            _open_cash_session(company=company, branch=branch, actor=actor)
            if method == TenderPaymentMethod.CASH
            else None
        )

        intent, _created = create_payment_intent(
            request=request, actor=actor, amount=amount, currency=rec.currency,
            idempotency_key=f"cobro:{company.id}:{idempotency_key}",
            external_ref=f"receivable:{rec.obligation_id}", provider="CASHIER",
            payment_method=method,
        )
        intent = capture_payment_intent(
            request=request, actor=actor, payment_id=intent.payment_id,
            provider_txn_id=f"cobro:{idempotency_key}",
            metadata={"receivable_id": str(rec.obligation_id), "channel": "caja"},
        )

        allocation = allocate_payment_to_obligation(
            payment_intent=intent,
            obligation=rec,
            allocated_amount=amount,
            allocation_date=timezone.localdate(),
            created_by=actor,
        )

        # Reflejar el abono en la factura de origen (si existe y sigue viva).
        if rec.reference_type == "BILLING_DOC" and rec.reference_id:
            try:
                create_payment(
                    request=request, actor=actor, doc_id=int(rec.reference_id),
                    payment_method=method, amount=amount, currency=rec.currency,
                    reference=f"cobro-cxc:{rec.obligation_id}",
                )
            except BillingError:
                # La CxC manda; si el doc ya no admite pagos (p. ej. anulado), el cobro
                # de cartera sigue siendo válido.
                pass

        cash_movement_id = None
        if session is not None:
            movement = post_cash_movement(
                request=request, actor=actor, session_id=session.id,
                movement_type=CashMovement.MovementType.INCOME, amount=amount,
                reference=f"cobro-cxc:{rec.id}", reason="COBRO_CXC",
                idempotency_key=f"cobro-cash:{company.id}:{idempotency_key}",
            )
            cash_movement_id = movement.id

        rec.refresh_from_db()
        return {
            "receivable_id": str(rec.obligation_id),
            "allocation_id": str(allocation.allocation_id),
            "allocated": str(amount),
            "outstanding_after": str(rec.outstanding_amount),
            "status_after": rec.status,
            "cash_movement_id": cash_movement_id,
        }


def credit_account_summary(*, company, party_id: int) -> dict[str, Any] | None:
    """Resumen de la cuenta de crédito del cliente para la pantalla de caja."""
    account = CustomerCreditAccount.objects.filter(
        company=company, party_id=party_id, is_active=True
    ).select_related("party").first()
    if account is None:
        return None
    avail = available_credit(account)
    return {
        "account_id": account.id,
        "party_id": account.party_id,
        "party_display_name": account.party.display_name,
        "segment": account.segment,
        "credit_limit": str(account.credit_limit) if account.credit_limit is not None else None,
        "credit_days": account.credit_days,
        "available": str(avail) if avail is not None else None,
    }


def pos_daily_report(*, company, branch, day) -> dict[str, Any]:
    """Corte de ventas del día (estilo "corte X" de un POS de retail).

    Resume las facturas EMITIDAS del día en la sucursal: total vendido, desglose por
    método de pago (de los abonos CONFIRMADOS), ventas a crédito, devoluciones (NC),
    top de productos y UTILIDAD BRUTA (ingreso sin IVA − costo real de los despachos
    según kardex). Solo lectura: no toca nada.
    """
    from django.db.models import Count, F, Sum

    from apps.kernels.facturacion.models import BillingPayment
    from apps.kernels.inventarios.models import StockMovement

    docs = BillingDocument.objects.filter(
        company=company, branch=branch, status=DocStatus.ISSUED, issued_at__date=day,
    )
    invoices = docs.filter(doc_type=DocType.INVOICE)
    credit_notes = docs.filter(doc_type=DocType.CREDIT_NOTE)

    inv_totals = invoices.aggregate(
        count=Count("id"), subtotal=Sum("subtotal"), tax=Sum("tax_total"),
        total=Sum("total"), discount=Sum("discount_total"),
    )
    cn_totals = credit_notes.aggregate(count=Count("id"), total=Sum("total"))

    invoice_ids = list(invoices.values_list("id", flat=True))

    # Cobros del día por método (la verdad del dinero recibido, no del doc).
    by_method = list(
        BillingPayment.objects.filter(
            company=company, doc_id__in=invoice_ids, status=BillingPayment.Status.CONFIRMED,
        )
        .values("payment_method")
        .annotate(amount=Sum("amount"), count=Count("id"))
        .order_by("-amount")
    )

    credit_total = invoices.filter(credit_status="APPROVED").aggregate(t=Sum("total"))["t"] or Decimal("0.00")

    # Costo real de lo despachado por estas facturas (kardex; qty_delta negativo).
    cost = StockMovement.objects.filter(
        company=company, branch=branch,
        source_module="BILLING", source_type="DOC_ISSUE",
        source_id__in=[str(i) for i in invoice_ids],
    ).aggregate(c=Sum("total_cost"))["c"] or Decimal("0.00")
    cost = abs(cost)

    subtotal = inv_totals["subtotal"] or Decimal("0.00")
    gross_profit = _q2(Decimal(subtotal) - cost)

    top_products = list(
        invoices.filter(lines__inventory_item__isnull=False)
        .values(sku=F("lines__inventory_item__sku"), name=F("lines__inventory_item__name"))
        .annotate(qty=Sum("lines__quantity"), amount=Sum("lines__line_total"))
        .order_by("-amount")[:10]
    )

    by_cashier = list(
        invoices.values(username=F("created_by__username"))
        .annotate(count=Count("id"), total=Sum("total"))
        .order_by("-total")
    )

    def _s(v):
        return str(_q2(Decimal(v or 0)))

    return {
        "date": str(day),
        "sales": {
            "count": inv_totals["count"] or 0,
            "subtotal": _s(subtotal),
            "tax": _s(inv_totals["tax"]),
            "discount": _s(inv_totals["discount"]),
            "total": _s(inv_totals["total"]),
            "credit_total": _s(credit_total),
        },
        "payments_by_method": [
            {"method": r["payment_method"], "amount": _s(r["amount"]), "count": r["count"]}
            for r in by_method
        ],
        "returns": {"count": cn_totals["count"] or 0, "total": _s(cn_totals["total"])},
        "cost_of_goods": _s(cost),
        "gross_profit": str(gross_profit),
        "top_products": [
            {"sku": r["sku"], "name": r["name"], "qty": str(r["qty"]), "amount": _s(r["amount"])}
            for r in top_products
        ],
        "by_cashier": [
            {"username": r["username"], "count": r["count"], "total": _s(r["total"])}
            for r in by_cashier
        ],
    }
