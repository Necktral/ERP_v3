"""Endpoints de conciliación bancaria — Ola D (kernel payments)."""
from __future__ import annotations

from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modulos.common.permissions import rbac_permission

from .models import BankAccount, BankStatement
from .reconciliation import (
    account_payload,
    create_bank_account,
    create_bank_statement,
    exclude_line,
    match_line,
    reconcile_statement,
    statement_payload,
    suggest_matches,
    unmatch_line,
)
from .services import PaymentsDomainError


class BankAccountCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    bank_name = serializers.CharField(max_length=120)
    account_number = serializers.CharField(max_length=64)
    currency = serializers.CharField(max_length=8, required=False, default="NIO")


class StatementLineInSerializer(serializers.Serializer):
    line_date = serializers.DateField()
    description = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    reference = serializers.CharField(max_length=96, required=False, allow_blank=True, default="")
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)


class StatementCreateSerializer(serializers.Serializer):
    bank_account_id = serializers.IntegerField(min_value=1)
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    opening_balance = serializers.DecimalField(max_digits=18, decimal_places=2)
    closing_balance = serializers.DecimalField(max_digits=18, decimal_places=2)
    lines = StatementLineInSerializer(many=True, allow_empty=False)


class MatchSerializer(serializers.Serializer):
    payment_id = serializers.UUIDField()


class ExcludeSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


_NOT_FOUND = frozenset({
    "PAYMENTS_BANK_ACCOUNT_NOT_FOUND",
    "PAYMENTS_STATEMENT_NOT_FOUND",
    "PAYMENTS_STATEMENT_LINE_NOT_FOUND",
    "PAYMENTS_INTENT_NOT_FOUND",
})


def _bank_error_response(exc: PaymentsDomainError) -> Response:
    code = str(exc)
    http = status.HTTP_404_NOT_FOUND if code in _NOT_FOUND else status.HTTP_422_UNPROCESSABLE_ENTITY
    return Response({"detail": code}, status=http)


def _require_company(request) -> Response | None:
    if getattr(request, "company", None) is None:
        return Response({"detail": "X-Company-Id requerido"}, status=status.HTTP_400_BAD_REQUEST)
    return None


class BankAccountListCreateView(APIView):
    """GET cuentas bancarias (bank.read) + POST crear (bank.manage)."""

    def get_permissions(self):
        perm = "payments.bank.manage" if self.request.method == "POST" else "payments.bank.read"
        return [rbac_permission(perm)()]

    def get(self, request):
        err = _require_company(request)
        if err is not None:
            return err
        accounts = BankAccount.objects.filter(company=request.company).order_by("bank_name", "name")
        return Response({"results": [account_payload(a) for a in accounts]})

    def post(self, request):
        err = _require_company(request)
        if err is not None:
            return err
        s = BankAccountCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            account = create_bank_account(company=request.company, actor=request.user, **s.validated_data)
        except PaymentsDomainError as exc:
            return _bank_error_response(exc)
        return Response(account_payload(account), status=status.HTTP_201_CREATED)


class BankStatementListCreateView(APIView):
    """GET extractos (bank.read) + POST cargar extracto con líneas (bank.manage)."""

    def get_permissions(self):
        perm = "payments.bank.manage" if self.request.method == "POST" else "payments.bank.read"
        return [rbac_permission(perm)()]

    def get(self, request):
        err = _require_company(request)
        if err is not None:
            return err
        qs = (
            BankStatement.objects.filter(company=request.company)
            .select_related("bank_account")
            .order_by("-period_end", "-id")[:100]
        )
        return Response({"results": [statement_payload(st, with_lines=False) for st in qs]})

    def post(self, request):
        err = _require_company(request)
        if err is not None:
            return err
        s = StatementCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        try:
            statement = create_bank_statement(
                company=request.company, actor=request.user,
                bank_account_id=v["bank_account_id"],
                period_start=v["period_start"], period_end=v["period_end"],
                opening_balance=v["opening_balance"], closing_balance=v["closing_balance"],
                lines=v["lines"],
            )
        except PaymentsDomainError as exc:
            return _bank_error_response(exc)
        return Response(statement_payload(statement), status=status.HTTP_201_CREATED)


class BankStatementDetailView(APIView):
    permission_classes = [rbac_permission("payments.bank.read")]

    def get(self, request, statement_id: int):
        err = _require_company(request)
        if err is not None:
            return err
        statement = (
            BankStatement.objects.filter(company=request.company, id=statement_id)
            .select_related("bank_account")
            .first()
        )
        if statement is None:
            return Response({"detail": "PAYMENTS_STATEMENT_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        return Response(statement_payload(statement))


class BankStatementSuggestView(APIView):
    permission_classes = [rbac_permission("payments.bank.reconcile")]

    def get(self, request, statement_id: int):
        err = _require_company(request)
        if err is not None:
            return err
        try:
            suggestions = suggest_matches(company=request.company, statement_id=statement_id)
        except PaymentsDomainError as exc:
            return _bank_error_response(exc)
        return Response({"results": suggestions})


class _LineActionView(APIView):
    permission_classes = [rbac_permission("payments.bank.reconcile")]


class BankLineMatchView(_LineActionView):
    def post(self, request, statement_id: int, line_id: int):
        err = _require_company(request)
        if err is not None:
            return err
        s = MatchSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            line = match_line(
                company=request.company, actor=request.user,
                statement_id=statement_id, line_id=line_id,
                payment_id=s.validated_data["payment_id"],
            )
        except PaymentsDomainError as exc:
            return _bank_error_response(exc)
        return Response(line)


class BankLineUnmatchView(_LineActionView):
    def post(self, request, statement_id: int, line_id: int):
        err = _require_company(request)
        if err is not None:
            return err
        try:
            line = unmatch_line(
                company=request.company, actor=request.user,
                statement_id=statement_id, line_id=line_id,
            )
        except PaymentsDomainError as exc:
            return _bank_error_response(exc)
        return Response(line)


class BankLineExcludeView(_LineActionView):
    def post(self, request, statement_id: int, line_id: int):
        err = _require_company(request)
        if err is not None:
            return err
        s = ExcludeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            line = exclude_line(
                company=request.company, actor=request.user,
                statement_id=statement_id, line_id=line_id,
                reason=s.validated_data["reason"],
            )
        except PaymentsDomainError as exc:
            return _bank_error_response(exc)
        return Response(line)


class BankStatementReconcileView(_LineActionView):
    def post(self, request, statement_id: int):
        err = _require_company(request)
        if err is not None:
            return err
        try:
            statement = reconcile_statement(
                company=request.company, actor=request.user, statement_id=statement_id
            )
        except PaymentsDomainError as exc:
            return _bank_error_response(exc)
        return Response(statement_payload(statement))
