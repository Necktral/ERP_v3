from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.HealthView.as_view()),
    path("recipes/", views.RecipeListCreateView.as_view()),
    path("orders/", views.OrderListCreateView.as_view()),
    path("orders/<int:order_id>/start/", views.OrderStartView.as_view()),
    path("orders/<int:order_id>/close/", views.OrderCloseView.as_view()),
    path("orders/<int:order_id>/cancel/", views.OrderCancelView.as_view()),
]
