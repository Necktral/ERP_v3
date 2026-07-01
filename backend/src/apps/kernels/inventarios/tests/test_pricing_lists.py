"""Tests del resolver de listas de precios (pricelists de Odoo, aterrizado).

Fija la precedencia completa: party > segmento > mayoreo > precio base; los tramos por
cantidad dentro de una lista; el filtro por moneda; y que listas/asignaciones inactivas
no aplican.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from apps.kernels.inventarios.models import (
    InventoryItem,
    PriceList,
    PriceListAssignment,
    PriceListItem,
    UoM,
)
from apps.kernels.inventarios.pricing import resolve_sale_price
from apps.modulos.iam.models import OrgUnit
from apps.modulos.parties.models import Party

UT = OrgUnit.UnitType


def _scope():
    t = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=UT.HOLDING, name=f"H{t}", code=f"H-{t}")
    company = OrgUnit.objects.create(unit_type=UT.COMPANY, parent=holding, name=f"C{t}", code=f"C-{t}")
    return holding, company


def _item(company, *, sale="100.00", wholesale=None, wholesale_min=None):
    return InventoryItem.objects.create(
        company=company, sku=f"S{uuid.uuid4().hex[:6]}", name="Aceite", uom=UoM.UNIT,
        sale_price=Decimal(sale),
        wholesale_price=Decimal(wholesale) if wholesale else None,
        wholesale_min_qty=Decimal(wholesale_min) if wholesale_min else None,
    )


def _party(company, name="Cliente"):
    return Party.objects.create(company=company, party_type=Party.PartyType.NATURAL, display_name=name)


def _lista(company, item, *, name="VIP", currency="NIO", tramos=(("0", "80.00"),),
           party=None, segment=""):
    pl = PriceList.objects.create(company=company, name=name, currency=currency)
    for min_qty, price in tramos:
        PriceListItem.objects.create(pricelist=pl, item=item, min_qty=Decimal(min_qty), price=Decimal(price))
    PriceListAssignment.objects.create(
        company=company, pricelist=pl, party=party, segment=segment,
    )
    return pl


@pytest.mark.django_db
def test_precedencia_party_sobre_segmento_sobre_mayoreo_sobre_base():
    _h, company = _scope()
    item = _item(company, sale="100.00", wholesale="90.00", wholesale_min="10")
    cliente = _party(company)
    _lista(company, item, name="SEG-EMP", tramos=(("0", "85.00"),), segment="EMPLOYEE")
    _lista(company, item, name="VIP", tramos=(("0", "80.00"),), party=cliente)

    # party gana a todo
    assert resolve_sale_price(company=company, item=item, qty=Decimal("1"),
                              party=cliente, segment="EMPLOYEE") == Decimal("80.00")
    # sin party: segmento gana a mayoreo y base (incluso con qty de mayoreo)
    assert resolve_sale_price(company=company, item=item, qty=Decimal("20"),
                              segment="EMPLOYEE") == Decimal("85.00")
    # sin listas aplicables: mayoreo por cantidad
    assert resolve_sale_price(company=company, item=item, qty=Decimal("10")) == Decimal("90.00")
    # base
    assert resolve_sale_price(company=company, item=item, qty=Decimal("1")) == Decimal("100.00")


@pytest.mark.django_db
def test_tramos_por_cantidad_gana_el_mayor_min_qty_alcanzado():
    _h, company = _scope()
    item = _item(company)
    cliente = _party(company)
    _lista(company, item, party=cliente,
           tramos=(("0", "95.00"), ("10", "88.00"), ("50", "82.00")))
    def price(q: str) -> Decimal:
        resolved = resolve_sale_price(company=company, item=item, qty=Decimal(q), party=cliente)
        assert resolved is not None
        return resolved

    assert price("1") == Decimal("95.00")
    assert price("10") == Decimal("88.00")
    assert price("49") == Decimal("88.00")
    assert price("50") == Decimal("82.00")


@pytest.mark.django_db
def test_moneda_filtra_listas():
    _h, company = _scope()
    item = _item(company, sale="100.00")
    cliente = _party(company)
    _lista(company, item, name="USD-VIP", currency="USD", tramos=(("0", "2.50"),), party=cliente)
    # Venta NIO: la lista USD NO aplica → cae al precio base.
    assert resolve_sale_price(company=company, item=item, qty=Decimal("1"),
                              party=cliente, currency="NIO") == Decimal("100.00")
    assert resolve_sale_price(company=company, item=item, qty=Decimal("1"),
                              party=cliente, currency="USD") == Decimal("2.50")


@pytest.mark.django_db
def test_lista_inactiva_o_asignacion_inactiva_no_aplica():
    _h, company = _scope()
    item = _item(company, sale="100.00")
    cliente = _party(company)
    pl = _lista(company, item, party=cliente, tramos=(("0", "70.00"),))
    pl.is_active = False
    pl.save(update_fields=["is_active"])
    assert resolve_sale_price(company=company, item=item, qty=Decimal("1"),
                              party=cliente) == Decimal("100.00")

    pl.is_active = True
    pl.save(update_fields=["is_active"])
    asg = pl.assignments.get()
    asg.is_active = False
    asg.save(update_fields=["is_active"])
    assert resolve_sale_price(company=company, item=item, qty=Decimal("1"),
                              party=cliente) == Decimal("100.00")


@pytest.mark.django_db
def test_item_sin_precio_en_lista_cae_a_la_siguiente_capa():
    _h, company = _scope()
    item = _item(company, sale="100.00")
    otro_item = _item(company, sale="40.00")
    cliente = _party(company)
    _lista(company, otro_item, party=cliente, tramos=(("0", "30.00"),))  # lista SIN este ítem
    assert resolve_sale_price(company=company, item=item, qty=Decimal("1"),
                              party=cliente) == Decimal("100.00")
