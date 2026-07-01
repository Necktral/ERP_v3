"""
Portfolio Kernel URLs
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views
from .views_collections import CollectionRemindersView, CollectionsWorkbenchView

router = DefaultRouter()
router.register(r"receivables", views.ReceivableViewSet, basename="receivable")
router.register(r"payables", views.PayableViewSet, basename="payable")
router.register(r"credits", views.CreditViewSet, basename="credit")
router.register(r"allocations", views.PaymentAllocationViewSet, basename="payment-allocation")
router.register(r"interest-accruals", views.InterestAccrualViewSet, basename="interest-accrual")
router.register(r"settings", views.PortfolioSettingsViewSet, basename="portfolio-settings")

app_name = "portfolio"
urlpatterns = [
    # Ola D: cobranza (dunning) — mesa de trabajo + recordatorios formales
    path("collections/workbench/", CollectionsWorkbenchView.as_view()),
    path("collections/reminders/", CollectionRemindersView.as_view()),
    path("", include(router.urls)),
]
