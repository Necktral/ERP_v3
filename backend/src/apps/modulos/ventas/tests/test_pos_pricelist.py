"""Regresión POS con listas de precios: el cliente con lista asignada compra al precio
de SU lista (resuelto en servidor), y sin lista el flujo queda exactamente como antes."""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.facturacion.models import BillingDocument
from apps.kernels.inventarios.models import (
    InventoryItem,
    PriceList,
    PriceListAssignment,
    PriceListItem,
    UoM,
)
from apps.kernels.inventarios.services import create_warehouse, post_receive
from apps.kernels.payments.services import open_cash_session_for_scope
from apps.modulos.iam.models import OrgUnit
from apps.modulos.parties.models import Party
from apps.modulos.ventas.services import pos_sale

User = get_user_model()
UT = OrgUnit.UnitType


def _scope():
    t = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=UT.HOLDING, name=f"H{t}", code=f"H-{t}")
    company = OrgUnit.objects.create(unit_type=UT.COMPANY, parent=holding, name=f"C{t}", code=f"C-{t}")
    branch = OrgUnit.objects.create(unit_type=UT.BRANCH, parent=company, name=f"B{t}", code=f"B-{t}")
    return holding, company, branch


def _user():
    t = uuid.uuid4().hex[:8]
    return User.objects.create_user(username=f"u_{t}", email=f"u_{t}@t.local", password="pass12345")


def _req(company, branch, user):
    return SimpleNamespace(
        company=company, branch=branch, user=user, META={}, headers={},
        path="/test/ventas/", method="POST", request_id=f"req-{uuid.uuid4().hex[:8]}",
    )


def _seed(req, company, branch, actor):
    wh = create_warehouse(request=req, company=company, branch=branch, actor_user=actor,
                          name="Bodega", code="W1")
    item = InventoryItem.objects.create(
        company=company, sku=f"SKU{uuid.uuid4().hex[:6]}", name="Aceite 1L", uom=UoM.UNIT,
        sale_price=Decimal("100.00"), default_tax_rate=Decimal("0.00"),
    )
    post_receive(request=req, actor=actor, warehouse_id=wh.id, item_id=item.id,
                 qty=Decimal("50"), unit_cost=Decimal("60"),
                 idempotency_key=f"rcv-{uuid.uuid4().hex}")
    open_cash_session_for_scope(company=company, branch=branch, actor=actor,
                                opening_amount=Decimal("500.00"))
    return wh, item


@pytest.mark.django_db
def test_pos_sale_usa_precio_de_lista_del_cliente():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed(req, company, branch, actor)
    cliente = Party.objects.create(company=company, party_type=Party.PartyType.NATURAL,
                                   display_name="Cliente VIP")
    pl = PriceList.objects.create(company=company, name="VIP", currency="NIO")
    PriceListItem.objects.create(pricelist=pl, item=item, min_qty=Decimal("0"), price=Decimal("80.00"))
    PriceListAssignment.objects.create(company=company, pricelist=pl, party=cliente)

    out = pos_sale(
        request=req, actor=actor, warehouse_id=wh.id,
        lines=[{"inventory_item_id": item.id, "quantity": "2"}],
        payments=[{"method": "CASH", "amount": "160.00"}],  # 2 × 80 (precio de lista)
        idempotency_key=f"pos-{uuid.uuid4().hex}",
        customer_party_id=cliente.id,
    )
    doc = BillingDocument.objects.get(pk=out["doc_id"])
    assert doc.total == Decimal("160.00")


@pytest.mark.django_db
def test_pos_sale_sin_lista_conserva_precio_base():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed(req, company, branch, actor)

    out = pos_sale(
        request=req, actor=actor, warehouse_id=wh.id,
        lines=[{"inventory_item_id": item.id, "quantity": "1"}],
        payments=[{"method": "CASH", "amount": "100.00"}],  # precio base intacto
        idempotency_key=f"pos-{uuid.uuid4().hex}",
    )
    doc = BillingDocument.objects.get(pk=out["doc_id"])
    assert doc.total == Decimal("100.00")
