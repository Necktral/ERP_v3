from __future__ import annotations

from django.urls import path

from .views import (
    AdjustView,
    BalanceView,
    HealthView,
    IssueView,
    ItemDetailView,
    ItemView,
    KardexView,
    LotCreateView,
    LotListView,
    LotStockView,
    ReceiveView,
    StockSummaryView,
    TransferView,
    WarehouseView,
)
from .views_counting import (
    InventoryValuationView,
    PhysicalCountApproveView,
    PhysicalCountCancelView,
    PhysicalCountCaptureView,
    PhysicalCountDetailView,
    PhysicalCountListCreateView,
)
from .views_pricing import (
    PriceListAssignmentDeleteView,
    PriceListAssignmentView,
    PriceListDetailView,
    PriceListItemDeleteView,
    PriceListItemView,
    PriceListListCreateView,
)


urlpatterns = [
    path("health/", HealthView.as_view()),
    # Warehouses: GET=list, POST=create (backward compat con tests y código existente)
    path("warehouses/", WarehouseView.as_view()),
    # Items: GET=list, POST=create (backward compat)
    path("items/", ItemView.as_view()),
    path("items/<int:item_id>/", ItemDetailView.as_view()),
    # Lots
    path("lots/", LotListView.as_view()),
    path("lots/create/", LotCreateView.as_view()),
    # Stock
    path("stock/", StockSummaryView.as_view()),        # paginado, filtros avanzados
    path("balances/", BalanceView.as_view()),           # backward compat: ?warehouse_id=X&item_id=Y
    path("stock/lots/", LotStockView.as_view()),
    path("kardex/", KardexView.as_view()),
    # Movement commands
    path("movements/receive/", ReceiveView.as_view()),
    path("movements/issue/", IssueView.as_view()),
    path("movements/adjust/", AdjustView.as_view()),
    path("transfers/", TransferView.as_view()),
    # Conteo físico (Ola C) + valorización
    path("counts/", PhysicalCountListCreateView.as_view()),
    path("counts/<int:count_id>/", PhysicalCountDetailView.as_view()),
    path("counts/<int:count_id>/capture/", PhysicalCountCaptureView.as_view()),
    path("counts/<int:count_id>/approve/", PhysicalCountApproveView.as_view()),
    path("counts/<int:count_id>/cancel/", PhysicalCountCancelView.as_view()),
    path("valuation/", InventoryValuationView.as_view()),
    # Listas de precios (administración) — §12
    path("pricelists/", PriceListListCreateView.as_view()),
    path("pricelists/<int:pricelist_id>/", PriceListDetailView.as_view()),
    path("pricelists/<int:pricelist_id>/items/", PriceListItemView.as_view()),
    path("pricelists/<int:pricelist_id>/items/<int:line_id>/", PriceListItemDeleteView.as_view()),
    path("pricelists/<int:pricelist_id>/assignments/", PriceListAssignmentView.as_view()),
    path("pricelists/<int:pricelist_id>/assignments/<int:assign_id>/", PriceListAssignmentDeleteView.as_view()),
]
