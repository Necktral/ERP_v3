"""Pago de CxP a proveedores desde caja (Ola D)."""
from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.kernels.payments.services import PaymentsDomainError
from apps.kernels.portfolio.services import PortfolioDomainError
from apps.modulos.common.permissions import rbac_permission

from .serializers import PayPayableSerializer
from .services import ProcurementError
from .views_orders import _proc_error_response, _require_branch
from .services_payments import pay_payable


class PayPayableView(APIView):
    """Pago de una CxP en caja (efectivo de la sesión o transferencia/cheque/tarjeta)."""

    permission_classes = [rbac_permission("procurement.payable.pay")]

    def post(self, request):
        branch_error = _require_branch(request)
        if branch_error is not None:
            return branch_error
        s = PayPayableSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        try:
            result = pay_payable(
                request=request, actor=request.user,
                payable_id=v["payable_id"], amount=v["amount"],
                method=v["method"], idempotency_key=v["idempotency_key"],
            )
        except ProcurementError as exc:
            return _proc_error_response(exc)
        except PortfolioDomainError as exc:
            return Response({"detail": exc.code}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except PaymentsDomainError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(result, status=status.HTTP_201_CREATED)
