"""
U8 (oleada 1) — certificación del kernel inventarios:

- La idempotency_key NO puede reutilizarse con otro payload (warehouse, qty,
  lote): debe conflictuar, nunca "matchear" en falso ni duplicar movimiento.
- El replay exacto es idempotente (mismo movimiento, balance intacto).
- post_transfer cruzado concurrente (A→B y B→A) no se deadlockea: el lock de
  bodegas en orden determinista serializa y el stock se conserva.
"""
from __future__ import annotations

import threading
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.inventarios.models import InventoryItem, StockBalance, StockMovement, Warehouse
from apps.kernels.inventarios.services import (
    InventoryConflictError,
    post_receive,
    post_transfer,
)
from apps.modulos.iam.models import OrgUnit

User = get_user_model()


def _scope():
    t = uuid.uuid4().hex[:8]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H{t}", code=f"H-{t}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, parent=holding, name=f"C{t}", code=f"C-{t}")
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, parent=company, name=f"B{t}", code=f"B-{t}")
    user = User.objects.create_user(username=f"u8_{t}", email=f"u8_{t}@test.local", password="Secret123!")
    request = SimpleNamespace(
        company=company, branch=branch, user=user, META={}, headers={},
        path="/t/u8/", method="POST", request_id=f"req-{t}",
    )
    return company, branch, user, request


def _wh(company, branch, code):
    return Warehouse.objects.create(company=company, branch=branch, name=code, code=f"{code}-{uuid.uuid4().hex[:4]}")


def _item(company):
    return InventoryItem.objects.create(company=company, sku=f"SKU-{uuid.uuid4().hex[:6]}", name="Item U8")


def _qty(company, branch, wh, item) -> Decimal:
    bal = StockBalance.objects.filter(company=company, branch=branch, warehouse=wh, item=item).first()
    return bal.qty_on_hand if bal else Decimal("0.0000")


def _receive(request, user, wh, item, key, *, qty="10", cost="2.50", **kw):
    return post_receive(
        request=request, actor=user, warehouse_id=wh.id, item_id=item.id,
        qty=Decimal(qty), unit_cost=Decimal(cost), idempotency_key=key, **kw,
    )


# ---------------------------------------------------------------------------
# Idempotencia: replay exacto OK, payload distinto conflictúa
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_receive_replay_exacto_es_idempotente_y_no_duplica():
    company, branch, user, request = _scope()
    wh, item = _wh(company, branch, "A"), _item(company)
    key = f"u8-{uuid.uuid4().hex}"

    first = _receive(request, user, wh, item, key)
    second = _receive(request, user, wh, item, key)

    assert second.movement_id == first.movement_id
    assert StockMovement.objects.filter(company=company, idempotency_key=key).count() == 1
    assert _qty(company, branch, wh, item) == Decimal("10.0000")


@pytest.mark.django_db
def test_receive_key_reusada_con_otro_warehouse_conflictua():
    company, branch, user, request = _scope()
    wh_a, wh_b, item = _wh(company, branch, "A"), _wh(company, branch, "B"), _item(company)
    key = f"u8-{uuid.uuid4().hex}"

    _receive(request, user, wh_a, item, key)
    with pytest.raises(InventoryConflictError):
        _receive(request, user, wh_b, item, key)
    # El conflicto no debe haber tocado stock de B.
    assert _qty(company, branch, wh_b, item) == Decimal("0.0000")


@pytest.mark.django_db
def test_receive_key_reusada_con_otra_cantidad_conflictua():
    company, branch, user, request = _scope()
    wh, item = _wh(company, branch, "A"), _item(company)
    key = f"u8-{uuid.uuid4().hex}"

    _receive(request, user, wh, item, key, qty="10")
    with pytest.raises(InventoryConflictError):
        _receive(request, user, wh, item, key, qty="99")
    assert _qty(company, branch, wh, item) == Decimal("10.0000")


@pytest.mark.django_db
def test_receive_key_reusada_con_otro_lote_conflictua():
    """Replay del mismo key con OTRO lote debe conflictuar, no matchear en falso."""
    company, branch, user, request = _scope()
    wh, item = _wh(company, branch, "A"), _item(company)
    item.track_lots = True
    item.save(update_fields=["track_lots"])
    key = f"u8-{uuid.uuid4().hex}"

    _receive(request, user, wh, item, key, lot_number=f"L1-{uuid.uuid4().hex[:4]}")
    with pytest.raises(InventoryConflictError):
        _receive(request, user, wh, item, key, lot_number=f"L2-{uuid.uuid4().hex[:4]}")


@pytest.mark.django_db
def test_transfer_key_reusada_con_direccion_invertida_conflictua():
    company, branch, user, request = _scope()
    wh_a, wh_b, item = _wh(company, branch, "A"), _wh(company, branch, "B"), _item(company)
    _receive(request, user, wh_a, item, f"seed-a-{uuid.uuid4().hex}", qty="50")
    _receive(request, user, wh_b, item, f"seed-b-{uuid.uuid4().hex}", qty="50")
    key = f"u8-tr-{uuid.uuid4().hex}"

    post_transfer(
        request=request, actor=user, from_warehouse_id=wh_a.id, to_warehouse_id=wh_b.id,
        item_id=item.id, qty=Decimal("5"), idempotency_key=key,
    )
    with pytest.raises(InventoryConflictError):
        post_transfer(
            request=request, actor=user, from_warehouse_id=wh_b.id, to_warehouse_id=wh_a.id,
            item_id=item.id, qty=Decimal("5"), idempotency_key=key,
        )


# ---------------------------------------------------------------------------
# Concurrencia: transferencias cruzadas no se deadlockean
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_transfer_cruzado_concurrente_sin_deadlock_y_stock_conservado():
    """A→B y B→A a la vez: el lock de bodegas en orden determinista (ids
    ordenados) serializa ambas transacciones — ninguna muere por deadlock y la
    suma de stock se conserva."""
    from django.db import connection as db_conn

    company, branch, user, request = _scope()
    wh_a, wh_b, item = _wh(company, branch, "A"), _wh(company, branch, "B"), _item(company)
    _receive(request, user, wh_a, item, f"seed-a-{uuid.uuid4().hex}", qty="100")
    _receive(request, user, wh_b, item, f"seed-b-{uuid.uuid4().hex}", qty="100")

    barrier = threading.Barrier(2, timeout=10)
    errors: list[str] = []
    errors_lock = threading.Lock()

    def transferir(from_wh, to_wh):
        try:
            barrier.wait()  # maximiza el solape de las dos transacciones
            post_transfer(
                request=request, actor=user, from_warehouse_id=from_wh.id,
                to_warehouse_id=to_wh.id, item_id=item.id, qty=Decimal("10"),
                idempotency_key=f"u8-x-{uuid.uuid4().hex}",
            )
        except Exception as exc:  # deadlock u otro error: se registra, no se oculta
            with errors_lock:
                errors.append(f"{from_wh.code}->{to_wh.code}: {exc!r}")
        finally:
            db_conn.close()  # cada hilo cierra SU conexión (thread-local)

    threads = [
        threading.Thread(target=transferir, args=(wh_a, wh_b)),
        threading.Thread(target=transferir, args=(wh_b, wh_a)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"transferencias cruzadas fallaron: {errors}"
    qty_a, qty_b = _qty(company, branch, wh_a, item), _qty(company, branch, wh_b, item)
    assert qty_a == Decimal("100.0000"), qty_a  # -10 +10
    assert qty_b == Decimal("100.0000"), qty_b
    assert qty_a + qty_b == Decimal("200.0000")
