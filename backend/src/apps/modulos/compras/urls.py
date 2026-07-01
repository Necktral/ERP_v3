from __future__ import annotations

from django.urls import path

from .views import (
    HealthView,
    PurchaseDocDetailView,
    PurchaseDocListCreateView,
    PurchaseDocPostView,
    PurchaseDocVoidView,
)
from .views_orders import (
    PurchaseOrderApproveView,
    PurchaseOrderCancelView,
    PurchaseOrderCloseView,
    PurchaseOrderDetailView,
    PurchaseOrderInvoiceView,
    PurchaseOrderListCreateView,
    PurchaseOrderReceiveView,
    PurchaseOrderSendView,
    PurchaseOrderSubmitView,
    ReorderCreateOrdersView,
    ReorderSuggestionsView,
    SupplierPricesView,
)
from .views_payments import PayPayableView
from .views_requisitions import (
    RequisitionApproveView,
    RequisitionConvertView,
    RequisitionDetailView,
    RequisitionListCreateView,
    RequisitionRejectView,
    RequisitionSubmitView,
)

urlpatterns = [
    path("health/", HealthView.as_view()),
    path("docs/", PurchaseDocListCreateView.as_view()),
    path("docs/<int:doc_id>/", PurchaseDocDetailView.as_view()),
    path("docs/<int:doc_id>/post/", PurchaseDocPostView.as_view()),
    path("docs/<int:doc_id>/void/", PurchaseDocVoidView.as_view()),
    # Ola B: órdenes de compra formales
    path("orders/", PurchaseOrderListCreateView.as_view()),
    path("orders/<int:order_id>/", PurchaseOrderDetailView.as_view()),
    path("orders/<int:order_id>/submit/", PurchaseOrderSubmitView.as_view()),
    path("orders/<int:order_id>/approve/", PurchaseOrderApproveView.as_view()),
    path("orders/<int:order_id>/send/", PurchaseOrderSendView.as_view()),
    path("orders/<int:order_id>/receive/", PurchaseOrderReceiveView.as_view()),
    path("orders/<int:order_id>/invoice/", PurchaseOrderInvoiceView.as_view()),
    path("orders/<int:order_id>/close/", PurchaseOrderCloseView.as_view()),
    path("orders/<int:order_id>/cancel/", PurchaseOrderCancelView.as_view()),
    # Ola B: requisiciones
    path("requisitions/", RequisitionListCreateView.as_view()),
    path("requisitions/<int:req_id>/", RequisitionDetailView.as_view()),
    path("requisitions/<int:req_id>/submit/", RequisitionSubmitView.as_view()),
    path("requisitions/<int:req_id>/approve/", RequisitionApproveView.as_view()),
    path("requisitions/<int:req_id>/reject/", RequisitionRejectView.as_view()),
    path("requisitions/<int:req_id>/convert/", RequisitionConvertView.as_view()),
    # Ola D: pago de CxP al proveedor desde caja
    path("pay-payable/", PayPayableView.as_view()),
    # Ola B: reorden y precios por proveedor
    path("reorder-suggestions/", ReorderSuggestionsView.as_view()),
    path("reorder-suggestions/create-orders/", ReorderCreateOrdersView.as_view()),
    path("supplier-prices/", SupplierPricesView.as_view()),
]
