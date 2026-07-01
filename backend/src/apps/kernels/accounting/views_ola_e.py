"""Endpoints Ola E — centros de costo, asientos manuales, presupuestos, cierre anual."""
from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modulos.common.pagination import coerce_int_param
from apps.modulos.common.permissions import rbac_permission

from .services import AccountingConflictError
from .services_budgets import (
    approve_budget,
    archive_budget,
    budget_payload,
    budget_vs_actual,
    create_budget,
    get_budget,
    list_budgets,
    upsert_budget_lines,
)
from .services_costcenters import (
    AccountingPlusError,
    AccountingPlusNotFound,
    cost_center_payload,
    create_cost_center,
    create_manual_journal_draft,
    list_cost_centers,
    manual_draft_payload,
    update_cost_center,
)
from .services_yearend import close_fiscal_year, get_year_end_status, reopen_fiscal_year


def _err(exc) -> Response:
    if isinstance(exc, AccountingPlusNotFound):
        return Response({"detail": exc.code}, status=status.HTTP_404_NOT_FOUND)
    if isinstance(exc, AccountingPlusError):
        return Response({"detail": exc.code}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    if isinstance(exc, AccountingConflictError):
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


def _require_company(request) -> Response | None:
    if getattr(request, "company", None) is None:
        return Response({"detail": "X-Company-Id requerido"}, status=status.HTTP_400_BAD_REQUEST)
    return None


# --------------------------------------------------------------- centros de costo

class CostCenterCreateSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=32)
    name = serializers.CharField(max_length=128)


class CostCenterUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128, required=False)
    is_active = serializers.BooleanField(required=False)


class CostCentersView(APIView):
    def get_permissions(self):
        perm = "accounting.cost_center.manage" if self.request.method == "POST" else "accounting.cost_center.read"
        return [rbac_permission(perm)()]

    def get(self, request):
        err = _require_company(request)
        if err:
            return err
        return Response({"results": list_cost_centers(company=request.company)})

    def post(self, request):
        err = _require_company(request)
        if err:
            return err
        s = CostCenterCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            cc = create_cost_center(company=request.company, actor=request.user, **s.validated_data)
        except (AccountingPlusError, AccountingConflictError, ValueError) as exc:
            return _err(exc)
        return Response(cost_center_payload(cc), status=status.HTTP_201_CREATED)


class CostCenterDetailView(APIView):
    permission_classes = [rbac_permission("accounting.cost_center.manage")]

    def patch(self, request, cost_center_id: int):
        err = _require_company(request)
        if err:
            return err
        s = CostCenterUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            cc = update_cost_center(
                company=request.company, actor=request.user,
                cost_center_id=cost_center_id, **s.validated_data,
            )
        except (AccountingPlusError, ValueError) as exc:
            return _err(exc)
        return Response(cost_center_payload(cc))


# --------------------------------------------------------------- asiento manual

class ManualLineSerializer(serializers.Serializer):
    account_code = serializers.CharField(max_length=32)
    side = serializers.ChoiceField(choices=["DEBIT", "CREDIT"])
    amount = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0.01"))
    description = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    cost_center_id = serializers.IntegerField(required=False, allow_null=True)


class ManualJournalSerializer(serializers.Serializer):
    entry_date = serializers.DateField()
    memo = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    lines = ManualLineSerializer(many=True, allow_empty=False)


class ManualJournalView(APIView):
    permission_classes = [rbac_permission("accounting.manual_journal.create")]

    def post(self, request):
        err = _require_company(request)
        if err:
            return err
        s = ManualJournalSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        try:
            draft = create_manual_journal_draft(
                company=request.company, branch=getattr(request, "branch", None),
                actor=request.user, entry_date=v["entry_date"], memo=v["memo"],
                lines=[dict(ln) for ln in v["lines"]],
            )
        except (AccountingPlusError, AccountingConflictError, ValueError) as exc:
            return _err(exc)
        return Response(manual_draft_payload(draft), status=status.HTTP_201_CREATED)


# --------------------------------------------------------------- presupuestos

class BudgetCreateSerializer(serializers.Serializer):
    fiscal_year = serializers.IntegerField(min_value=2000, max_value=2999)
    name = serializers.CharField(max_length=128)
    currency = serializers.CharField(max_length=8, required=False, default="NIO")


class BudgetLineInSerializer(serializers.Serializer):
    account_code = serializers.CharField(max_length=32)
    cost_center_id = serializers.IntegerField(required=False, allow_null=True)
    monthly = serializers.DictField(child=serializers.CharField(), required=False, default=dict)


class BudgetLinesSerializer(serializers.Serializer):
    lines = BudgetLineInSerializer(many=True, allow_empty=False)


class BudgetsView(APIView):
    def get_permissions(self):
        perm = "accounting.budget.manage" if self.request.method == "POST" else "accounting.budget.read"
        return [rbac_permission(perm)()]

    def get(self, request):
        err = _require_company(request)
        if err:
            return err
        fy = request.query_params.get("fiscal_year")
        return Response({"results": list_budgets(
            company=request.company, fiscal_year=coerce_int_param(fy, field="fiscal_year")
        )})

    def post(self, request):
        err = _require_company(request)
        if err:
            return err
        s = BudgetCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            budget = create_budget(company=request.company, actor=request.user, **s.validated_data)
        except (AccountingPlusError, ValueError) as exc:
            return _err(exc)
        return Response(budget_payload(budget), status=status.HTTP_201_CREATED)


class BudgetDetailView(APIView):
    permission_classes = [rbac_permission("accounting.budget.read")]

    def get(self, request, budget_id: int):
        err = _require_company(request)
        if err:
            return err
        try:
            return Response(get_budget(company=request.company, budget_id=budget_id))
        except AccountingPlusError as exc:
            return _err(exc)


class BudgetLinesView(APIView):
    permission_classes = [rbac_permission("accounting.budget.manage")]

    def put(self, request, budget_id: int):
        err = _require_company(request)
        if err:
            return err
        s = BudgetLinesSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            budget = upsert_budget_lines(
                company=request.company, actor=request.user, budget_id=budget_id,
                lines=[dict(ln) for ln in s.validated_data["lines"]],
            )
        except (AccountingPlusError, ValueError) as exc:
            return _err(exc)
        return Response(budget_payload(budget, with_lines=True))


class BudgetApproveView(APIView):
    permission_classes = [rbac_permission("accounting.budget.manage")]

    def post(self, request, budget_id: int):
        err = _require_company(request)
        if err:
            return err
        try:
            budget = approve_budget(company=request.company, actor=request.user, budget_id=budget_id)
        except (AccountingPlusError, ValueError) as exc:
            return _err(exc)
        return Response(budget_payload(budget))


class BudgetArchiveView(APIView):
    permission_classes = [rbac_permission("accounting.budget.manage")]

    def post(self, request, budget_id: int):
        err = _require_company(request)
        if err:
            return err
        try:
            budget = archive_budget(company=request.company, actor=request.user, budget_id=budget_id)
        except AccountingPlusError as exc:
            return _err(exc)
        return Response(budget_payload(budget))


class BudgetVsActualView(APIView):
    permission_classes = [rbac_permission("accounting.budget.read")]

    def get(self, request, budget_id: int):
        err = _require_company(request)
        if err:
            return err
        q = request.query_params
        month_from = coerce_int_param(q.get("month_from"), field="month_from", default=1)
        month_to = coerce_int_param(q.get("month_to"), field="month_to", default=12)
        cost_center_id = coerce_int_param(q.get("cost_center_id"), field="cost_center_id")
        try:
            result = budget_vs_actual(
                company=request.company, budget_id=budget_id,
                month_from=month_from,
                month_to=month_to,
                cost_center_id=cost_center_id,
            )
        except AccountingPlusError as exc:
            return _err(exc)
        return Response(result)


# --------------------------------------------------------------- cierre anual

class YearEndCloseSerializer(serializers.Serializer):
    fiscal_year = serializers.IntegerField(min_value=2000, max_value=2999)
    force = serializers.BooleanField(required=False, default=False)


class YearEndReopenSerializer(serializers.Serializer):
    fiscal_year = serializers.IntegerField(min_value=2000, max_value=2999)
    reason = serializers.CharField(max_length=255)
    force = serializers.BooleanField(required=False, default=False)


class YearEndView(APIView):
    permission_classes = [rbac_permission("accounting.year_end.close")]

    def get(self, request):
        err = _require_company(request)
        if err:
            return err
        fy = request.query_params.get("fiscal_year")
        if not fy:
            return Response({"detail": "fiscal_year requerido"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(get_year_end_status(company=request.company, fiscal_year=coerce_int_param(fy, field="fiscal_year")))


class YearEndCloseView(APIView):
    permission_classes = [rbac_permission("accounting.year_end.close")]

    def post(self, request):
        err = _require_company(request)
        if err:
            return err
        s = YearEndCloseSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        try:
            result = close_fiscal_year(
                company=request.company, actor=request.user,
                fiscal_year=v["fiscal_year"], force=v["force"],
            )
        except (AccountingPlusError, AccountingConflictError, ValueError) as exc:
            return _err(exc)
        return Response(result, status=status.HTTP_200_OK)


class YearEndReopenView(APIView):
    permission_classes = [rbac_permission("accounting.year_end.close")]

    def post(self, request):
        err = _require_company(request)
        if err:
            return err
        s = YearEndReopenSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        try:
            result = reopen_fiscal_year(
                company=request.company, actor=request.user,
                fiscal_year=v["fiscal_year"], reason=v["reason"], force=v["force"],
            )
        except (AccountingPlusError, AccountingConflictError, ValueError) as exc:
            return _err(exc)
        return Response(result, status=status.HTTP_200_OK)
