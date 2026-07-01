from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response
from django.utils import timezone
from rest_framework.views import APIView

from apps.kernels.facturacion.services import BillingError
from apps.kernels.payments.services import PaymentsDomainError
from apps.kernels.portfolio.services import PortfolioDomainError
from apps.modulos.comisariato.services import ComisariatoError
from apps.modulos.common.permissions import rbac_permission
from apps.modulos.rbac.selectors import get_effective_permissions_for_scope

from .serializers import (
    CollectReceivableSerializer,
    PosOverrideSerializer,
    PosSaleSerializer,
    SelfServiceCreateSerializer,
)
from .services import (
    SalesError,
    cancel_self_service_ticket,
    collect_receivable,
    create_self_service_ticket,
    credit_account_summary,
    get_self_service_ticket,
    grant_pos_override,
    pos_daily_report,
    pos_sale,
    verify_pos_override_grant,
)
from apps.modulos.audit.writer import write_event

# Códigos de negocio que son culpa del pedido (422), no del sistema.
_UNPROCESSABLE = {
    "SALES_ITEM_WITHOUT_PRICE",
    "SALES_AMOUNT_INVALID",
    "SALES_AMOUNT_EXCEEDS_OUTSTANDING",
    "SALES_RECEIVABLE_NOT_OPEN",
    "SALES_PRICE_OVERRIDE_FORBIDDEN",
    "SALES_PAYMENTS_MISMATCH",
    "SALES_NO_OPEN_CASH_SESSION",
    "SALES_NO_CREDIT_ACCOUNT",
    "SALES_CREDIT_REQUIRES_CUSTOMER",
    "SALES_CREDIT_MUST_BE_ONLY_PAYMENT",
    "SALES_INVALID_PAYMENT_METHOD",
    "SALES_INSUFFICIENT_STOCK",
    "COMISARIATO_CREDIT_LIMIT_EXCEEDED",
    "SALES_SELF_SERVICE_NOT_OPEN",
    "SALES_SELF_SERVICE_EXPIRED",
    "SALES_SELF_SERVICE_CODE_EXHAUSTED",
    "SALES_OVERRIDE_REASON_REQUIRED",
    "SALES_OVERRIDE_SELF",
    "SALES_OVERRIDE_INVALID",
    "SALES_OVERRIDE_EXPIRED",
}

# Códigos que significan "no existe" (404).
_NOT_FOUND = {"SALES_RECEIVABLE_NOT_FOUND", "SALES_SELF_SERVICE_NOT_FOUND"}

# Credenciales del supervisor inválidas / sin permiso para autorizar el override.
_UNAUTHORIZED = {"SALES_OVERRIDE_BAD_CREDENTIALS"}
_FORBIDDEN = {"SALES_OVERRIDE_NOT_AUTHORIZED"}


def _sales_error_response(exc: SalesError) -> Response:
    code = str(exc)
    if code in _NOT_FOUND:
        http: int = status.HTTP_404_NOT_FOUND
    elif code in _UNAUTHORIZED:
        http = status.HTTP_401_UNAUTHORIZED
    elif code in _FORBIDDEN:
        http = status.HTTP_403_FORBIDDEN
    elif code in _UNPROCESSABLE:
        http = status.HTTP_422_UNPROCESSABLE_ENTITY
    else:
        http = status.HTTP_400_BAD_REQUEST
    return Response({"detail": code}, status=http)


class HealthView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response({"ok": True, "module": "sales"})


class PosSaleView(APIView):
    permission_classes = [rbac_permission("sales.pos.sell")]

    def post(self, request):
        if getattr(request, "company", None) is None or getattr(request, "branch", None) is None:
            return Response(
                {"detail": "X-Company-Id y X-Branch-Id requeridos"}, status=status.HTTP_400_BAD_REQUEST
            )
        s = PosSaleSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data

        effective = get_effective_permissions_for_scope(
            request.user, company=request.company, branch=request.branch
        )
        allow_override = "*" in effective or "sales.pos.price_override" in effective

        # El cajero sin permiso puede traer un grant firmado por un supervisor.
        override_grant = (v.get("override_grant") or "").strip()
        override_authorized_by = None
        if not allow_override and override_grant:
            try:
                override_authorized_by = verify_pos_override_grant(
                    grant=override_grant, company=request.company,
                    branch=request.branch, cashier=request.user,
                )
            except SalesError as exc:
                return _sales_error_response(exc)
            allow_override = True

        try:
            result = pos_sale(
                request=request, actor=request.user,
                warehouse_id=v["warehouse_id"],
                lines=v["lines"], payments=v["payments"],
                idempotency_key=v["idempotency_key"],
                customer_party_id=v.get("customer_party_id"),
                customer_name=v.get("customer_name") or "",
                currency=v.get("currency") or "NIO",
                is_fiscal=v["is_fiscal"],
                allow_price_override=allow_override,
                self_service_code=v.get("self_service_code") or "",
            )
        except SalesError as exc:
            return _sales_error_response(exc)
        except ComisariatoError as exc:
            code = str(exc)
            http = (
                status.HTTP_422_UNPROCESSABLE_ENTITY
                if code in _UNPROCESSABLE
                else status.HTTP_400_BAD_REQUEST
            )
            return Response({"detail": code}, status=http)
        except BillingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        # Override autorizado por un supervisor: deja rastro atado a la factura.
        if override_authorized_by is not None and not result.get("duplicate"):
            write_event(
                request=request, module="SALES", event_type="SALES_POS_OVERRIDE_USED",
                reason_code="SALES_OK", actor_user=request.user,
                subject_type="SALES_POS_OVERRIDE", subject_id=str(result.get("doc_id")),
                metadata={"authorized_by_id": override_authorized_by, "doc_id": result.get("doc_id")},
            )
        return Response(result, status=status.HTTP_201_CREATED)


class PosOverrideGrantView(APIView):
    """Un supervisor se reautentica en la caja para autorizar precio/descuento (grant firmado)."""

    permission_classes = [rbac_permission("sales.pos.sell")]

    def post(self, request):
        if getattr(request, "company", None) is None or getattr(request, "branch", None) is None:
            return Response(
                {"detail": "X-Company-Id y X-Branch-Id requeridos"}, status=status.HTTP_400_BAD_REQUEST
            )
        s = PosOverrideSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        try:
            result = grant_pos_override(
                request=request, actor=request.user,
                supervisor_username=v["supervisor_username"],
                supervisor_password=v["supervisor_password"],
                reason=v["reason"],
            )
        except SalesError as exc:
            return _sales_error_response(exc)
        return Response(result, status=status.HTTP_201_CREATED)


class CollectReceivableView(APIView):
    """Cobro de una CxC en caja (cliente abona su cuenta)."""

    permission_classes = [rbac_permission("payments.cash_movement.create")]

    def post(self, request):
        if getattr(request, "company", None) is None or getattr(request, "branch", None) is None:
            return Response(
                {"detail": "X-Company-Id y X-Branch-Id requeridos"}, status=status.HTTP_400_BAD_REQUEST
            )
        s = CollectReceivableSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        try:
            result = collect_receivable(
                request=request, actor=request.user,
                receivable_id=v["receivable_id"], amount=v["amount"],
                method=v["method"], idempotency_key=v["idempotency_key"],
            )
        except SalesError as exc:
            return _sales_error_response(exc)
        except PortfolioDomainError as exc:
            return Response({"detail": exc.code}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except PaymentsDomainError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(result, status=status.HTTP_201_CREATED)


class PosReportView(APIView):
    """Corte de ventas del día (total, métodos de pago, devoluciones, utilidad)."""

    permission_classes = [rbac_permission("sales.pos.report")]

    def get(self, request):
        if getattr(request, "company", None) is None or getattr(request, "branch", None) is None:
            return Response(
                {"detail": "X-Company-Id y X-Branch-Id requeridos"}, status=status.HTTP_400_BAD_REQUEST
            )
        from datetime import date as _date

        raw = (request.query_params.get("date") or "").strip()
        try:
            day = _date.fromisoformat(raw) if raw else timezone.localdate()
        except ValueError:
            return Response({"detail": "date inválida (YYYY-MM-DD)"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(pos_daily_report(company=request.company, branch=request.branch, day=day))


class SelfServiceCreateView(APIView):
    """Kiosko de auto-facturación: el cliente crea su pre-ticket desde la tableta."""

    permission_classes = [rbac_permission("sales.pos.self_service")]

    def post(self, request):
        if getattr(request, "company", None) is None or getattr(request, "branch", None) is None:
            return Response(
                {"detail": "X-Company-Id y X-Branch-Id requeridos"}, status=status.HTTP_400_BAD_REQUEST
            )
        s = SelfServiceCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        try:
            result = create_self_service_ticket(
                request=request, actor=request.user,
                lines=v["lines"], currency=v.get("currency") or "NIO",
            )
        except SalesError as exc:
            return _sales_error_response(exc)
        return Response(result, status=status.HTTP_201_CREATED)


class SelfServiceDetailView(APIView):
    """La caja trae el pre-ticket por código (precios re-resueltos al momento)."""

    permission_classes = [rbac_permission("sales.pos.sell")]

    def get(self, request, code: str):
        if getattr(request, "company", None) is None:
            return Response({"detail": "X-Company-Id requerido"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            result = get_self_service_ticket(company=request.company, code=code)
        except SalesError as exc:
            return _sales_error_response(exc)
        return Response(result)


class SelfServiceCancelView(APIView):
    """El kiosko cancela su pre-ticket (se arrepintió antes de pasar a caja)."""

    permission_classes = [rbac_permission("sales.pos.self_service")]

    def post(self, request, code: str):
        if getattr(request, "company", None) is None:
            return Response({"detail": "X-Company-Id requerido"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            result = cancel_self_service_ticket(request=request, actor=request.user, code=code)
        except SalesError as exc:
            return _sales_error_response(exc)
        return Response(result)


class CreditAccountSummaryView(APIView):
    """Disponible de crédito del cliente para la pantalla de caja (read-only)."""

    permission_classes = [rbac_permission("sales.pos.sell")]

    def get(self, request, party_id: int):
        if getattr(request, "company", None) is None:
            return Response({"detail": "X-Company-Id requerido"}, status=status.HTTP_400_BAD_REQUEST)
        summary = credit_account_summary(company=request.company, party_id=party_id)
        if summary is None:
            return Response({"detail": "sin cuenta de crédito"}, status=status.HTTP_404_NOT_FOUND)
        return Response(summary)
