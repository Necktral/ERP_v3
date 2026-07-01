from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.kernels.nomina.models import PayrollEntry, PayrollPeriod, PayrollSheet
from apps.kernels.nomina.payroll_payments import PayrollPaymentError
from apps.modulos.common.pagination import get_limit_offset, paginate_queryset
from apps.modulos.common.permissions import rbac_permission
from apps.modulos.iam.models import OrgUnit
from apps.modulos.parties.models import Party

from .models import CustomerCreditAccount
from .pay_negotiated import CobrarPagarError, cobrar_y_pagar, deudas_por_planilla, rectificar_cobro
from .serializers import (
    AccountUpsertSerializer,
    CobrarYPagarSerializer,
    RectificarCobroSerializer,
    SaleSerializer,
)
from .services import (
    ComisariatoError,
    available_credit,
    get_or_create_account,
    outstanding_balance,
    sell_on_credit,
)


def _account_payload(account: CustomerCreditAccount) -> dict:
    avail = available_credit(account)
    return {
        "id": account.id,
        "company_id": account.company_id,
        "party_id": account.party_id,
        "party_display_name": account.party.display_name,
        "segment": account.segment,
        "credit_limit": str(account.credit_limit),
        "credit_days": account.credit_days,
        "outstanding": str(outstanding_balance(company=account.company, party=account.party)),
        "available": str(avail) if avail is not None else None,
        "collecting_company_id": account.collecting_company_id,
        "is_active": account.is_active,
        "notes": account.notes,
    }


class HealthView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response({"ok": True, "module": "comisariato"}, status=status.HTTP_200_OK)


class AccountListView(APIView):
    """Listado paginado de cuentas de crédito (filtros: q por tercero, segment, is_active)."""

    permission_classes = [rbac_permission("comisariato.read")]

    def get(self, request):
        company = getattr(request, "company", None)
        if company is None:
            return Response({"detail": "X-Company-Id requerido"}, status=status.HTTP_400_BAD_REQUEST)
        qs = (
            CustomerCreditAccount.objects.filter(company=company)
            .select_related("party")
            .order_by("party__display_name")
        )
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(party__display_name__icontains=q)
        segment = (request.query_params.get("segment") or "").strip().upper()
        if segment:
            qs = qs.filter(segment=segment)
        is_active = request.query_params.get("is_active")
        if is_active is not None and is_active != "":
            qs = qs.filter(is_active=is_active.lower() == "true")

        limit, offset = get_limit_offset(request)
        total, rows = paginate_queryset(qs, limit=limit, offset=offset)
        return Response(
            {
                "count": total,
                "limit": limit,
                "offset": offset,
                "results": [_account_payload(a) for a in rows],
            },
            status=status.HTTP_200_OK,
        )


class AccountUpsertView(APIView):
    permission_classes = [rbac_permission("comisariato.account.manage")]

    def post(self, request):
        company = getattr(request, "company", None)
        if company is None:
            return Response({"detail": "X-Company-Id requerido"}, status=status.HTTP_400_BAD_REQUEST)
        s = AccountUpsertSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data

        party = Party.objects.filter(id=v["party_id"], company=company).first()
        if party is None:
            return Response({"detail": "party no existe en esta empresa"}, status=status.HTTP_400_BAD_REQUEST)
        collecting = None
        if v.get("collecting_company_id"):
            collecting = OrgUnit.objects.filter(
                id=v["collecting_company_id"], unit_type=OrgUnit.UnitType.COMPANY
            ).first()
            if collecting is None:
                return Response({"detail": "collecting_company inválida"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            account = get_or_create_account(
                request=request, actor=request.user, company=company, party=party,
                segment=v["segment"], credit_limit=v["credit_limit"],
                credit_days=v.get("credit_days", 30), collecting_company=collecting,
                is_active=v["is_active"], notes=v.get("notes") or "",
            )
        except ComisariatoError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_account_payload(account), status=status.HTTP_200_OK)


class AccountDetailView(APIView):
    permission_classes = [rbac_permission("comisariato.read")]

    def get(self, request, account_id: int):
        company = getattr(request, "company", None)
        account = CustomerCreditAccount.objects.filter(id=account_id, company=company).first()
        if account is None:
            return Response({"detail": "cuenta no encontrada"}, status=status.HTTP_404_NOT_FOUND)
        return Response(_account_payload(account), status=status.HTTP_200_OK)


class SaleView(APIView):
    permission_classes = [rbac_permission("comisariato.sell")]

    def post(self, request):
        company = getattr(request, "company", None)
        if company is None or getattr(request, "branch", None) is None:
            return Response(
                {"detail": "X-Company-Id y X-Branch-Id requeridos"}, status=status.HTTP_400_BAD_REQUEST
            )
        s = SaleSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data

        account = CustomerCreditAccount.objects.filter(id=v["account_id"], company=company).first()
        if account is None:
            return Response({"detail": "cuenta no encontrada"}, status=status.HTTP_404_NOT_FOUND)

        try:
            result = sell_on_credit(
                request=request, actor=request.user, account=account,
                warehouse_id=v["warehouse_id"], lines=v["lines"], reference_code=v["reference_code"],
                currency=v.get("currency") or "NIO", is_fiscal=v["is_fiscal"],
            )
        except ComisariatoError as exc:
            code = str(exc)
            http = status.HTTP_422_UNPROCESSABLE_ENTITY if code == "COMISARIATO_CREDIT_LIMIT_EXCEEDED" else status.HTTP_400_BAD_REQUEST
            return Response({"detail": code}, status=http)
        return Response(result, status=status.HTTP_201_CREATED)


class AccountListUpsertView(AccountListView, AccountUpsertView):
    """GET lista (comisariato.read) + POST upsert (comisariato.account.manage)."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [rbac_permission("comisariato.account.manage")()]
        return [rbac_permission("comisariato.read")()]


# --- Cobrador-Pagador (CO-PA): cobro INTERNO negociado, fuera del documento legal --------------
# El CO-PA hace converger 2 empresas (finca + comisariato) y 3 relaciones: (1) nómina real,
# (2) préstamo personal (Credit intra-finca), (3) comisariato (relación de empresas, CXC). El
# cobro NUNCA toca la planilla legal auditada — es lógica interna apoyada en portfolio + relación.

class CobrarYPagarView(APIView):
    """POST → cobro NEGOCIADO + pago del neto (CO-PA).

    El pagador decide cuánto abonar a cada deuda interna (comisariato/préstamo) al pagar; el
    resto se entrega en efectivo. Gateado por `nomina.payment.register`. Idempotente por
    `idempotency_key`. Errores de dominio (abono > saldo, neto negativo, sobrepago) → 422.
    """

    permission_classes = [rbac_permission("nomina.payment.register")]

    def post(self, request, period_id: int, sheet_id: int, entry_id: int):
        company: OrgUnit = request.company
        period = get_object_or_404(PayrollPeriod, id=period_id, company=company)
        sheet = get_object_or_404(PayrollSheet, id=sheet_id, period=period)
        entry = get_object_or_404(PayrollEntry, id=entry_id, sheet=sheet)

        s = CobrarYPagarSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data

        try:
            result = cobrar_y_pagar(
                request=request,
                actor=request.user,
                entry=entry,
                abono_comisariato=v.get("abono_comisariato", 0),
                abono_prestamo=v.get("abono_prestamo", 0),
                payment_method=v["payment_method"],
                idempotency_key=v.get("idempotency_key") or "",
            )
        except (CobrarPagarError, PayrollPaymentError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response(result, status=status.HTTP_201_CREATED)


class RectificarCobroView(APIView):
    """POST → rectifica un cobro YA aplicado (CO-PA): anula el recibo previo y reemite corregido.

    Para cuando el pagador se equivoca de monto (puso 200 y eran 2000). Reversa los abonos del cobro
    (reversa global del kernel portfolio), anula el pago previo y re-cobra con el monto correcto.
    `motivo` obligatorio. Gateada por `nomina.payment.register`. Errores de dominio → 422.
    """

    permission_classes = [rbac_permission("nomina.payment.register")]

    def post(self, request, period_id: int, sheet_id: int, entry_id: int):
        company: OrgUnit = request.company
        period = get_object_or_404(PayrollPeriod, id=period_id, company=company)
        sheet = get_object_or_404(PayrollSheet, id=sheet_id, period=period)
        entry = get_object_or_404(PayrollEntry, id=entry_id, sheet=sheet)

        s = RectificarCobroSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data

        try:
            result = rectificar_cobro(
                request=request,
                actor=request.user,
                entry=entry,
                abono_comisariato=v.get("abono_comisariato", 0),
                abono_prestamo=v.get("abono_prestamo", 0),
                payment_method=v["payment_method"],
                motivo=v["motivo"],
                idempotency_key=v.get("idempotency_key") or "",
            )
        except (CobrarPagarError, PayrollPaymentError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response(result, status=status.HTTP_201_CREATED)


class DeudasPlanillaView(APIView):
    """GET → saldos de deuda interna (comisariato + préstamo) por entrada del período.

    Lo consume el CO-PA para mostrar la deuda total y pre-cargar el abono negociado.
    """

    permission_classes = [rbac_permission("nomina.payment.read")]

    def get(self, request, period_id: int):
        company: OrgUnit = request.company
        period = get_object_or_404(PayrollPeriod, id=period_id, company=company)
        return Response({"results": deudas_por_planilla(period=period)}, status=status.HTTP_200_OK)
