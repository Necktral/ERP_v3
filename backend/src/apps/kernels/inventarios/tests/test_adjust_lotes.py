"""
BUG-T4 (bug-hunt de integridad): un ajuste / conteo físico de un ítem con lotes
debe mantener el invariante Σ LotBalance == StockBalance. Antes `post_adjust`
movía solo `StockBalance` y dejaba los `LotBalance` intactos → la suma de lotes
divergía del saldo total y rompía la selección FEFO/FIFO y el costeo por lote.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.db.models import Sum

from apps.kernels.inventarios.models import (
    InventoryClass,
    InventoryItem,
    LotBalance,
    StockBalance,
    Warehouse,
)
from apps.kernels.inventarios.services import post_adjust, post_receive
from apps.modulos.iam.models import OrgUnit

User = get_user_model()


def _scope():
    t = uuid.uuid4().hex[:8]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H{t}", code=f"H-{t}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, parent=holding, name=f"C{t}", code=f"C-{t}")
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, parent=company, name=f"B{t}", code=f"B-{t}")
    user = User.objects.create_user(username=f"al_{t}", email=f"al_{t}@test.local", password="Secret123!")
    request = SimpleNamespace(
        company=company, branch=branch, user=user, META={}, headers={},
        path="/t/al/", method="POST", request_id=f"req-{t}",
    )
    return company, branch, user, request


def _lot_item(company):
    return InventoryItem.objects.create(
        company=company, sku=f"S-{uuid.uuid4().hex[:6]}", name="Loteado",
        track_lots=True, inventory_class=InventoryClass.FIFO,
    )


def _stock(company, branch, wh, item) -> Decimal:
    bal = StockBalance.objects.filter(company=company, branch=branch, warehouse=wh, item=item).first()
    return bal.qty_on_hand if bal else Decimal("0.0000")


def _sum_lots(company, branch, wh, item) -> Decimal:
    agg = LotBalance.objects.filter(company=company, branch=branch, warehouse=wh, item=item).aggregate(s=Sum("qty_on_hand"))
    return agg["s"] or Decimal("0.0000")


@pytest.mark.django_db
def test_ajuste_baja_mantiene_suma_de_lotes_igual_al_saldo():
    company, branch, user, request = _scope()
    wh = Warehouse.objects.create(company=company, branch=branch, name="Main", code=f"W{uuid.uuid4().hex[:5]}")
    item = _lot_item(company)

    # Dos lotes: L1 60, L2 40 (StockBalance 100, Σ lotes 100).
    post_receive(request=request, actor=user, warehouse_id=wh.id, item_id=item.id,
                 qty=Decimal("60"), unit_cost=Decimal("10"), lot_number="L1",
                 idempotency_key=f"r1-{uuid.uuid4().hex}")
    post_receive(request=request, actor=user, warehouse_id=wh.id, item_id=item.id,
                 qty=Decimal("40"), unit_cost=Decimal("10"), lot_number="L2",
                 idempotency_key=f"r2-{uuid.uuid4().hex}")
    assert _stock(company, branch, wh, item) == Decimal("100.0000")
    assert _sum_lots(company, branch, wh, item) == Decimal("100.0000")

    # Conteo físico: solo hay 90 (merma de 10).
    post_adjust(request=request, actor=user, warehouse_id=wh.id, item_id=item.id,
                new_qty_on_hand=Decimal("90"), idempotency_key=f"a-{uuid.uuid4().hex}",
                note="conteo físico")

    assert _stock(company, branch, wh, item) == Decimal("90.0000")
    # El invariante DEBE sostenerse: la suma de lotes = saldo total.
    assert _sum_lots(company, branch, wh, item) == Decimal("90.0000")


@pytest.mark.django_db
def test_ajuste_a_lote_explicito_mueve_ese_lote():
    company, branch, user, request = _scope()
    wh = Warehouse.objects.create(company=company, branch=branch, name="Main", code=f"W{uuid.uuid4().hex[:5]}")
    item = _lot_item(company)
    from apps.kernels.inventarios.models import ItemLot

    post_receive(request=request, actor=user, warehouse_id=wh.id, item_id=item.id,
                 qty=Decimal("50"), unit_cost=Decimal("10"), lot_number="L1",
                 idempotency_key=f"r-{uuid.uuid4().hex}")
    lot = ItemLot.objects.get(company=company, item=item, lot_number="L1")

    # Ajuste a lote explícito: subir a 60 (delta +10 sobre L1).
    post_adjust(request=request, actor=user, warehouse_id=wh.id, item_id=item.id,
                new_qty_on_hand=Decimal("60"), lot_id=lot.id, idempotency_key=f"a-{uuid.uuid4().hex}")

    assert _stock(company, branch, wh, item) == Decimal("60.0000")
    assert _sum_lots(company, branch, wh, item) == Decimal("60.0000")
