"""API del beneficio. Empresa activa obligatoria; las órdenes mueven stock ⇒ sucursal."""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.kernels.inventarios.models import InventoryItem, Warehouse
from apps.modulos.common.permissions import rbac_permission

from . import services
from .models import ProcessingOrder, TransformationRecipe
from .serializers import (
    OrderCloseSerializer,
    OrderCreateSerializer,
    OrderSerializer,
    RecipeCreateSerializer,
    RecipeSerializer,
)
from .services import BeneficioError


def _company_or_400(request):
    company = getattr(request, "company", None)
    if company is None:
        return None, Response(
            {"detail": "X-Company-Id requerido"}, status=status.HTTP_400_BAD_REQUEST
        )
    return company, None


def _business_error(exc: BeneficioError) -> Response:
    return Response(
        {"error": {"code": exc.code, "message": exc.message}},
        status=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )


class HealthView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response({"ok": True, "module": "beneficio"})


class RecipeListCreateView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [rbac_permission("beneficio.recipe.manage")()]
        return [rbac_permission("beneficio.order.read")()]

    def get(self, request):
        company, err = _company_or_400(request)
        if err:
            return err
        qs = TransformationRecipe.objects.filter(company=company, is_active=True)
        return Response({"results": RecipeSerializer(qs.order_by("code")[:200], many=True).data})

    def post(self, request):
        company, err = _company_or_400(request)
        if err:
            return err
        s = RecipeCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        input_item = get_object_or_404(InventoryItem, pk=v["input_item_id"], company=company)
        output_item = get_object_or_404(InventoryItem, pk=v["output_item_id"], company=company)
        try:
            recipe = services.create_recipe(
                company=company, code=v["code"], name=v["name"],
                input_item=input_item, output_item=output_item,
                expected_yield_pct=v["expected_yield_pct"],
                yield_tolerance_pct=v["yield_tolerance_pct"],
            )
        except BeneficioError as exc:
            return _business_error(exc)
        return Response(RecipeSerializer(recipe).data, status=status.HTTP_201_CREATED)


class OrderListCreateView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [rbac_permission("beneficio.order.create")()]
        return [rbac_permission("beneficio.order.read")()]

    def get(self, request):
        company, err = _company_or_400(request)
        if err:
            return err
        qs = ProcessingOrder.objects.filter(company=company).select_related("recipe")
        status_f = request.query_params.get("status")
        if status_f:
            qs = qs.filter(status=status_f)
        return Response({"results": OrderSerializer(qs.order_by("-id")[:300], many=True).data})

    def post(self, request):
        company, err = _company_or_400(request)
        if err:
            return err
        s = OrderCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        recipe = get_object_or_404(TransformationRecipe, pk=v["recipe_id"], company=company)
        in_wh = get_object_or_404(Warehouse, pk=v["input_warehouse_id"], company=company)
        out_wh = get_object_or_404(Warehouse, pk=v["output_warehouse_id"], company=company)
        try:
            order = services.create_order(
                company=company, recipe=recipe, input_warehouse=in_wh, output_warehouse=out_wh,
                input_qty=v["input_qty"], reference=v["reference"], note=v["note"],
                actor=request.user,
            )
        except BeneficioError as exc:
            return _business_error(exc)
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)


class OrderStartView(APIView):
    permission_classes = [rbac_permission("beneficio.order.process")]

    def post(self, request, order_id: int):
        company, err = _company_or_400(request)
        if err:
            return err
        if getattr(request, "branch", None) is None:
            return Response({"detail": "X-Branch-Id requerido"}, status=status.HTTP_400_BAD_REQUEST)
        order = get_object_or_404(
            ProcessingOrder.objects.select_related("recipe"), pk=order_id, company=company
        )
        try:
            order = services.start_order(request=request, actor=request.user, order=order)
        except BeneficioError as exc:
            return _business_error(exc)
        except ValueError as exc:  # kernel inventarios (stock insuficiente, etc.)
            return Response(
                {"error": {"code": "BEN_KERNEL", "message": str(exc)}},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return Response(OrderSerializer(order).data)


class OrderCloseView(APIView):
    permission_classes = [rbac_permission("beneficio.order.process")]

    def post(self, request, order_id: int):
        company, err = _company_or_400(request)
        if err:
            return err
        if getattr(request, "branch", None) is None:
            return Response({"detail": "X-Branch-Id requerido"}, status=status.HTTP_400_BAD_REQUEST)
        s = OrderCloseSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        order = get_object_or_404(
            ProcessingOrder.objects.select_related("recipe"), pk=order_id, company=company
        )
        try:
            order = services.close_order(
                request=request, actor=request.user, order=order,
                output_qty=s.validated_data["output_qty"],
            )
        except BeneficioError as exc:
            return _business_error(exc)
        except ValueError as exc:
            return Response(
                {"error": {"code": "BEN_KERNEL", "message": str(exc)}},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return Response(OrderSerializer(order).data)


class OrderCancelView(APIView):
    permission_classes = [rbac_permission("beneficio.order.create")]

    def post(self, request, order_id: int):
        company, err = _company_or_400(request)
        if err:
            return err
        order = get_object_or_404(ProcessingOrder, pk=order_id, company=company)
        try:
            order = services.cancel_order(order=order)
        except BeneficioError as exc:
            return _business_error(exc)
        return Response(OrderSerializer(order).data)
