from __future__ import annotations

from django.urls import path

from .views import (
    AccountDetailView,
    AccountListUpsertView,
    CobrarYPagarView,
    DeudasPlanillaView,
    HealthView,
    RectificarCobroView,
    SaleView,
)

app_name = "comisariato"

# IMPORTANTE: el DOCUMENTO legal de la planilla NO refleja comisariato ni préstamos (prohibido
# por el INSS). El cobro de esas deudas internas es lógica de empresa y vive ACÁ (módulo
# comisariato), fuera del kernel nómina: el Cobrador-Pagador (CO-PA) abona al pagar. Multi-empresa:
# el comisariato es otra compañía (relación CXC declarada); el préstamo es un Credit en la finca.
urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("accounts/", AccountListUpsertView.as_view(), name="account-upsert"),
    path("accounts/<int:account_id>/", AccountDetailView.as_view(), name="account-detail"),
    path("sales/", SaleView.as_view(), name="sale"),
    # Cobro NEGOCIADO + pago del neto (CO-PA): abona deudas internas y paga el efectivo.
    path(
        "payroll/cobrar-y-pagar/<int:period_id>/<int:sheet_id>/<int:entry_id>/",
        CobrarYPagarView.as_view(),
        name="cobrar-y-pagar",
    ),
    # Rectificar un cobro YA aplicado: anula el recibo previo y reemite con el monto correcto.
    path(
        "payroll/rectificar/<int:period_id>/<int:sheet_id>/<int:entry_id>/",
        RectificarCobroView.as_view(),
        name="rectificar-cobro",
    ),
    # Saldos de deuda (comisariato + préstamo) por entrada del período, para el CO-PA.
    path("payroll/deudas/<int:period_id>/", DeudasPlanillaView.as_view(), name="deudas-planilla"),
]
