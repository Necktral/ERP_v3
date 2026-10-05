"""
BUG-T1 (bug-hunt de integridad): `post_transfer` debe MEZCLAR el costo promedio
del balance destino, igual que `post_receive`. Antes solo tocaba `avg_cost` del
destino cuando la cantidad resultante era 0 (imposible en una transferencia-
entrada), así que:
  - a bodega vacía dejaba avg_cost=0 → COGS=0 y valorización 0 al despachar;
  - a bodega con stock a otro costo, no promediaba → subvaluación.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.inventarios.models import InventoryItem, StockBalance, Warehouse
from apps.kernels.inventarios.services import post_receive, post_transfer

User = get_user_model()


def _scope():
    from apps.modulos.iam.models import OrgUnit

    t = uuid.uuid4().hex[:8]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H{t}", code=f"H-{t}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, parent=holding, name=f"C{t}", code=f"C-{t}")
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, parent=company, name=f"B{t}", code=f"B-{t}")
    user = User.objects.create_user(username=f"tc_{t}", email=f"tc_{t}@test.local", password="Secret123!")
    request = SimpleNamespace(
        company=company, branch=branch, user=user, META={}, headers={},
        path="/t/tc/", method="POST", request_id=f"req-{t}",
    )
    return company, branch, user, request


def _wh(company, branch, code):
    return Warehouse.objects.create(company=company, branch=branch, name=code, code=f"{code}-{uuid.uuid4().hex[:4]}")


def _avg(company, branch, wh, item) -> Decimal:
    bal = StockBalance.objects.filter(company=company, branch=branch, warehouse=wh, item=item).first()
    return bal.avg_cost if bal else Decimal("0.000000")


@pytest.mark.django_db
def test_transferencia_a_bodega_vacia_lleva_el_costo_de_origen():
    company, branch, user, request = _scope()
    wh_a, wh_b = _wh(company, branch, "A"), _wh(company, branch, "B")
    item = InventoryItem.objects.create(company=company, sku=f"S-{uuid.uuid4().hex[:6]}", name="Item")

    post_receive(request=request, actor=user, warehouse_id=wh_a.id, item_id=item.id,
                 qty=Decimal("10"), unit_cost=Decimal("20.00"), idempotency_key=f"r-{uuid.uuid4().hex}")

    post_transfer(request=request, actor=user, from_warehouse_id=wh_a.id, to_warehouse_id=wh_b.id,
                  item_id=item.id, qty=Decimal("10"), idempotency_key=f"t-{uuid.uuid4().hex}")

    # El destino B, que estaba vacío, debe quedar con el costo de origen (20), no 0.
    assert _avg(company, branch, wh_b, item) == Decimal("20.000000")


@pytest.mark.django_db
def test_transferencia_a_bodega_con_stock_promedia_ponderado():
    company, branch, user, request = _scope()
    wh_a, wh_b = _wh(company, branch, "A"), _wh(company, branch, "B")
    item = InventoryItem.objects.create(company=company, sku=f"S-{uuid.uuid4().hex[:6]}", name="Item")

    # B: 10 @ 5.00 ; A: 10 @ 20.00. Transfiero 10 de A→B.
    post_receive(request=request, actor=user, warehouse_id=wh_b.id, item_id=item.id,
                 qty=Decimal("10"), unit_cost=Decimal("5.00"), idempotency_key=f"rb-{uuid.uuid4().hex}")
    post_receive(request=request, actor=user, warehouse_id=wh_a.id, item_id=item.id,
                 qty=Decimal("10"), unit_cost=Decimal("20.00"), idempotency_key=f"ra-{uuid.uuid4().hex}")

    post_transfer(request=request, actor=user, from_warehouse_id=wh_a.id, to_warehouse_id=wh_b.id,
                  item_id=item.id, qty=Decimal("10"), idempotency_key=f"t-{uuid.uuid4().hex}")

    # Promedio ponderado esperado: (10·5 + 10·20)/20 = 12.50.
    assert _avg(company, branch, wh_b, item) == Decimal("12.500000")
    # El origen conserva su costo (sigue con 20 en las unidades que le quedan; aquí queda en 0 uds → 0).
    assert _avg(company, branch, wh_a, item) == Decimal("0.000000")
