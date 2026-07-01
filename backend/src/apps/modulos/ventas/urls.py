from __future__ import annotations

from django.urls import path

from .views import (
    CollectReceivableView,
    CreditAccountSummaryView,
    HealthView,
    PosOverrideGrantView,
    PosReportView,
    PosSaleView,
    SelfServiceCancelView,
    SelfServiceCreateView,
    SelfServiceDetailView,
)

urlpatterns = [
    path("health/", HealthView.as_view()),
    path("pos-sale/", PosSaleView.as_view()),
    path("pos-override/", PosOverrideGrantView.as_view()),
    path("collect-receivable/", CollectReceivableView.as_view()),
    path("pos-report/", PosReportView.as_view()),
    path("credit-account/<int:party_id>/", CreditAccountSummaryView.as_view()),
    path("self-service/", SelfServiceCreateView.as_view()),
    path("self-service/<str:code>/", SelfServiceDetailView.as_view()),
    path("self-service/<str:code>/cancel/", SelfServiceCancelView.as_view()),
]
