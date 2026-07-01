from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.HealthView.as_view()),
    path("", views.AlertListView.as_view()),
    path("scan/", views.AlertScanView.as_view()),
    path("<int:alert_id>/ack/", views.AlertAckView.as_view()),
    path("<int:alert_id>/resolve/", views.AlertResolveView.as_view()),
]
