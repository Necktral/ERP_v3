from __future__ import annotations

from django.urls import path

from .views import (
    BranchFiscalConfigView,
    BillingReceivableReconcileView,
    CreditApprovalResolveView,
    DocContingencyResolveView,
    DocContingencyView,
    DocConvertView,
    DocCreditNoteView,
    DocDetailView,
    DocIssueView,
    DocListCreateView,
    DocPaymentsView,
    DocPrintView,
    DocVoidView,
    HealthView,
    OrderSubmitCreditView,
    OrdersView,
    PaymentReverseView,
)

urlpatterns = [
    path("health/", HealthView.as_view()),
    path("fiscal/branch-config/", BranchFiscalConfigView.as_view()),
    path("receivables/reconcile/", BillingReceivableReconcileView.as_view()),
    path("docs/", DocListCreateView.as_view()),
    path("docs/<int:doc_id>/", DocDetailView.as_view()),
    path("docs/<int:doc_id>/issue/", DocIssueView.as_view()),
    path("docs/<int:doc_id>/print/", DocPrintView.as_view()),
    path("docs/<int:doc_id>/contingency/", DocContingencyView.as_view()),
    path("docs/<int:doc_id>/contingency/resolve/", DocContingencyResolveView.as_view()),
    path("docs/<int:doc_id>/void/", DocVoidView.as_view()),
    # Parte 2: abonos, devoluciones (NC vinculada), cotización→factura, pedidos con crédito SoD
    path("docs/<int:doc_id>/payments/", DocPaymentsView.as_view()),
    path("docs/<int:doc_id>/payments/<int:payment_id>/reverse/", PaymentReverseView.as_view()),
    path("docs/<int:doc_id>/credit-note/", DocCreditNoteView.as_view()),
    path("docs/<int:doc_id>/convert/", DocConvertView.as_view()),
    path("orders/", OrdersView.as_view()),
    path("orders/<int:order_id>/submit-credit/", OrderSubmitCreditView.as_view()),
    path("credit-approvals/<int:approval_id>/resolve/", CreditApprovalResolveView.as_view()),
]
