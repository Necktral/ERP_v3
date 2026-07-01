"""Invariantes de negocio del BENEFICIO de café (test-negocio, archivo NUEVO).

Ataca tres invariantes del dominio café que los tests felices existentes no
verifican con números no triviales / casos borde:

  1. COSTO ABSORBIDO — conservación: todo el costo kardex del insumo consumido
     queda repartido en el valor del oro producido (qty_oro × avg_cost_oro ==
     input_cost_total). Ni se pierde ni se duplica, incluso con merma fuerte y
     con divisiones que arrastran redondeo.
  2. MERMA — reduce el rinde y encarece el oro exactamente: shrinkage = entrada −
     salida; el costo unitario absorbido = costo_insumo / salida (la merma sube
     el costo/lb del oro).
  3. RECIBO DE ACOPIO (dominio café, módulo financiamiento) — la cantidad cuadra:
     net_lb = gross_lb − tara; la tara por defecto se deriva de la calidad
     (default_tare_pct); el inventario en custodia entra por el neto a costo 0.

Reusa el patrón de helpers de scope/actor/request de los tests vecinos del
mismo módulo (test_beneficio.py) y de financiamiento (test_financing.py).
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.inventarios.models import InventoryItem, StockBalance, StockMovement, UoM
from apps.kernels.inventarios.services import create_warehouse, post_receive
from apps.modulos.beneficio import services as ben
from apps.modulos.beneficio.models import OrderStatus
from apps.modulos.iam.models import OrgUnit

User = get_user_model()
UT = OrgUnit.UnitType


# ---------------------------------------------------------------------------
# Helpers (clonados del estilo de test_beneficio.py)
# ---------------------------------------------------------------------------

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
        path="/test/beneficio/", method="POST", request_id=f"req-{uuid.uuid4().hex[:8]}",
    )


def _setup(req, company, branch, actor, *, pergamino_lb, cost_per_lb,
           expected_yield="50.00", tolerance="50.00"):
    """Bodegas in/out + ítems pergamino/oro + receta + stock de pergamino sembrado.

    tolerance amplio por defecto para que el cierre con merma fuerte NO dispare
    la alerta de rendimiento (queremos probar el cómputo, no la alerta).
    """
    wh_in = create_warehouse(request=req, company=company, branch=branch, actor_user=actor,
                             name="Bodega Pergamino", code=f"BP{uuid.uuid4().hex[:4]}")
    wh_out = create_warehouse(request=req, company=company, branch=branch, actor_user=actor,
                              name="Bodega Oro", code=f"BO{uuid.uuid4().hex[:4]}")
    pergamino = InventoryItem.objects.create(
        company=company, sku=f"PER-{uuid.uuid4().hex[:6]}", name="Café pergamino", uom=UoM.POUND,
    )
    oro = InventoryItem.objects.create(
        company=company, sku=f"ORO-{uuid.uuid4().hex[:6]}", name="Café oro", uom=UoM.POUND,
    )
    post_receive(
        request=req, actor=actor, warehouse_id=wh_in.id, item_id=pergamino.id,
        qty=Decimal(pergamino_lb), unit_cost=Decimal(cost_per_lb),
        idempotency_key=f"seed-{uuid.uuid4().hex}",
    )
    recipe = ben.create_recipe(
        company=company, code=f"PO-{uuid.uuid4().hex[:4]}", name="Pergamino a oro",
        input_item=pergamino, output_item=oro,
        expected_yield_pct=Decimal(expected_yield), yield_tolerance_pct=Decimal(tolerance),
    )
    return wh_in, wh_out, pergamino, oro, recipe


def _stock(company, branch, wh, item):
    bal = StockBalance.objects.filter(company=company, branch=branch, warehouse=wh, item=item).first()
    return (bal.qty_on_hand, bal.avg_cost) if bal else (Decimal("0"), Decimal("0"))


# ===========================================================================
# INVARIANTE 1 — COSTO ABSORBIDO: conservación exacta del costo del insumo
# ===========================================================================

@pytest.mark.django_db
def test_costo_absorbido_conservacion_con_merma_fuerte():
    """Números NO triviales: 777.00 lb pergamino @ 31.37/lb = C$24,374.49 de costo.
    Salida real 432.10 lb (merma de 344.90).  El costo unitario absorbido =
    24374.49 / 432.10 = 56.409372... → 4dp HALF_UP = 56.4094.  Y el VALOR del
    inventario de oro (qty × avg_cost) debe reconstruir el costo del insumo.
    """
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh_in, wh_out, pergamino, oro, recipe = _setup(
        req, company, branch, actor, pergamino_lb="777.00", cost_per_lb="31.37",
    )

    order = ben.create_order(
        company=company, recipe=recipe, input_warehouse=wh_in, output_warehouse=wh_out,
        input_qty=Decimal("777.00"), actor=actor,
    )
    order = ben.start_order(request=req, actor=actor, order=order)

    # Costo del insumo consumido = 777 × 31.37 = 24374.49 (capturado del kardex).
    assert order.input_cost_total == Decimal("24374.490000")

    order = ben.close_order(request=req, actor=actor, order=order, output_qty=Decimal("432.10"))
    assert order.status == OrderStatus.DONE

    # Costo unitario absorbido: 24374.49 / 432.10 = 56.409372... → 4dp HALF_UP.
    assert order.output_unit_cost == Decimal("56.4094")
    assert order.shrinkage_qty == Decimal("344.90")  # 777.00 − 432.10

    # Conservación: el valor del oro en kardex reconstruye el costo del insumo
    # (salvo el residuo de cuantización del costo unitario, < 1 lb × 0.0001).
    qty_out, avg_out = _stock(company, branch, wh_out, oro)
    assert qty_out == Decimal("432.1000")
    valor_oro = (qty_out * avg_out)
    residuo = abs(valor_oro - order.input_cost_total)
    # 432.10 × 0.0001 = 0.04321 máximo de drift por redondear el costo unitario.
    assert residuo <= Decimal("0.05"), (
        f"El costo del insumo NO se conserva en el oro: insumo={order.input_cost_total}, "
        f"valor_oro={valor_oro}, residuo={residuo}"
    )


@pytest.mark.django_db
def test_costo_absorbido_yield_100_sin_merma_es_costo_identico():
    """Sin merma (salida == entrada), el costo/lb del oro == costo/lb del pergamino.
    1000 lb @ 29.20 → 1000 lb de oro, avg_cost del oro == 29.20 exacto."""
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh_in, wh_out, _per, oro, recipe = _setup(
        req, company, branch, actor, pergamino_lb="1000.00", cost_per_lb="29.20",
    )
    order = ben.create_order(
        company=company, recipe=recipe, input_warehouse=wh_in, output_warehouse=wh_out,
        input_qty=Decimal("1000.00"), actor=actor,
    )
    ben.start_order(request=req, actor=actor, order=order)
    order = ben.close_order(request=req, actor=actor, order=order, output_qty=Decimal("1000.00"))

    assert order.yield_pct == Decimal("100.00")
    assert order.shrinkage_qty == Decimal("0.00")
    assert order.output_unit_cost == Decimal("29.2000")
    _qty, avg_out = _stock(company, branch, wh_out, oro)
    assert avg_out == Decimal("29.200000")


# ===========================================================================
# INVARIANTE 2 — MERMA: rinde y costo encarecido cuadran
# ===========================================================================

@pytest.mark.django_db
def test_merma_encarece_oro_y_rinde_cuadra():
    """Caso clásico pergamino→oro ~46%: 2500 lb @ 25.00 → 1150 lb oro.
    yield = 1150/2500 = 46.00%, merma = 1350 lb.
    costo/lb oro = (2500×25) / 1150 = 62500/1150 = 54.3478... → 54.3478."""
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh_in, wh_out, _per, oro, recipe = _setup(
        req, company, branch, actor, pergamino_lb="2500.00", cost_per_lb="25.00",
    )
    order = ben.create_order(
        company=company, recipe=recipe, input_warehouse=wh_in, output_warehouse=wh_out,
        input_qty=Decimal("2500.00"), actor=actor,
    )
    ben.start_order(request=req, actor=actor, order=order)
    order = ben.close_order(request=req, actor=actor, order=order, output_qty=Decimal("1150.00"))

    assert order.input_cost_total == Decimal("62500.000000")
    assert order.yield_pct == Decimal("46.00")
    assert order.shrinkage_qty == Decimal("1350.00")
    assert order.output_unit_cost == Decimal("54.3478")  # 62500/1150 HALF_UP a 4dp
    # El oro encarecido > costo del pergamino (la merma lo subió).
    assert order.output_unit_cost > Decimal("25.00")


@pytest.mark.django_db
def test_merma_reduce_stock_insumo_a_cero_y_solo_sale_el_oro():
    """El insumo sale COMPLETO de la bodega (queda 0) y solo entra el oro real:
    no aparece 'café fantasma' por la merma."""
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh_in, wh_out, pergamino, oro, recipe = _setup(
        req, company, branch, actor, pergamino_lb="900.00", cost_per_lb="30.00",
    )
    order = ben.create_order(
        company=company, recipe=recipe, input_warehouse=wh_in, output_warehouse=wh_out,
        input_qty=Decimal("900.00"), actor=actor,
    )
    ben.start_order(request=req, actor=actor, order=order)
    ben.close_order(request=req, actor=actor, order=order, output_qty=Decimal("400.00"))

    qty_in, _ = _stock(company, branch, wh_in, pergamino)
    qty_out, _ = _stock(company, branch, wh_out, oro)
    assert qty_in == Decimal("0.0000")        # insumo consumido completo
    assert qty_out == Decimal("400.0000")     # solo el oro REAL (la merma no genera stock)


# ===========================================================================
# INVARIANTE — IDEMPOTENCIA: re-cerrar la misma orden no duplica producción
# ===========================================================================

@pytest.mark.django_db
def test_recerrar_orden_done_no_duplica_oro_ni_movimiento():
    """Cerrar una orden ya DONE debe rechazarse (BEN_ORDER_STATE) y NO crear un
    segundo movimiento de recepción en el kardex (idempotencia del cierre)."""
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh_in, wh_out, _per, oro, recipe = _setup(
        req, company, branch, actor, pergamino_lb="500.00", cost_per_lb="20.00",
    )
    order = ben.create_order(
        company=company, recipe=recipe, input_warehouse=wh_in, output_warehouse=wh_out,
        input_qty=Decimal("500.00"), actor=actor,
    )
    ben.start_order(request=req, actor=actor, order=order)
    order = ben.close_order(request=req, actor=actor, order=order, output_qty=Decimal("250.00"))

    recv_movs_before = StockMovement.objects.filter(
        source_module="BENEFICIO", source_type="ProcessingOrder", source_id=str(order.pk),
        movement_type="RECEIVE",
    ).count()
    qty_before, _ = _stock(company, branch, wh_out, oro)

    with pytest.raises(ben.BeneficioError) as exc:
        ben.close_order(request=req, actor=actor, order=order, output_qty=Decimal("250.00"))
    assert exc.value.code == "BEN_ORDER_STATE"

    recv_movs_after = StockMovement.objects.filter(
        source_module="BENEFICIO", source_type="ProcessingOrder", source_id=str(order.pk),
        movement_type="RECEIVE",
    ).count()
    qty_after, _ = _stock(company, branch, wh_out, oro)
    assert recv_movs_after == recv_movs_before  # no se duplicó la recepción
    assert qty_after == qty_before              # el stock de oro no cambió


# ===========================================================================
# INVARIANTE 3 — RECIBO DE ACOPIO (dominio café): cantidad/calidad cuadra
# ===========================================================================

@pytest.mark.django_db
def test_recibo_acopio_neto_y_tara_por_calidad_y_custodia():
    """Recibo de acopio (financiamiento.receive_coffee): la cantidad cuadra.
    Calidad B con default_tare_pct = 2.50%; bruto 4000.00 lb sin tara explícita
    → tara = 4000 × 2.50% = 100.00, neto = 3900.00.  El inventario de custodia
    entra por el NETO con costo 0 (aún es del productor)."""
    pytest.importorskip("apps.modulos.financiamiento.services")
    from apps.modulos.financiamiento import services as fin
    from apps.modulos.parties.models import Party

    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)

    # Setup de acopio (clonado del estilo de test_financing._setup_acopio).
    custody = create_warehouse(request=req, company=company, branch=branch, actor_user=actor,
                               name="Custodia Café", code=f"CU{uuid.uuid4().hex[:4]}")
    own = create_warehouse(request=req, company=company, branch=branch, actor_user=actor,
                           name="Bodega Propia", code=f"PR{uuid.uuid4().hex[:4]}")
    item = InventoryItem.objects.create(
        company=company, sku=f"CAFE-{uuid.uuid4().hex[:6]}", name="Café pergamino húmedo", uom=UoM.POUND,
    )
    row = fin.get_or_create_settings(company=company)
    row.coffee_item = item
    row.custody_warehouse = custody
    row.liquidation_warehouse = own
    row.save()
    quality = fin.create_quality_grade(
        company=company, code=f"B{uuid.uuid4().hex[:3]}", name="Segunda",
        default_tare_pct=Decimal("2.50"),
    )
    party = Party.objects.create(
        company=company, party_type=Party.PartyType.NATURAL, display_name="Productor X",
        national_id=f"001-{uuid.uuid4().hex[:9]}",
    )
    producer = fin.create_producer(company=company, party=party, acopio_code="07-077")

    # Sin tara explícita → la tara se deriva de la calidad (2.50%).
    r = fin.receive_coffee(
        request=req, actor=actor, producer=producer, quality=quality,
        physical_state="HUMEDO", sacks=40, gross_lb=Decimal("4000.00"),
    )
    assert r.tare_lb == Decimal("100.00")   # 4000 × 2.50%
    assert r.net_lb == Decimal("3900.00")   # bruto − tara
    # Conservación del recibo: bruto = neto + tara.
    assert r.gross_lb == r.net_lb + r.tare_lb

    # El inventario de custodia entra por el NETO, a costo 0 (no es nuestro aún).
    bal = StockBalance.objects.filter(company=company, branch=branch, warehouse=custody, item=item).first()
    assert bal is not None
    assert bal.qty_on_hand == Decimal("3900.0000")
    assert bal.avg_cost == Decimal("0.000000")

    # El balance de depósito del productor refleja lo recibido.
    deposit = fin.producer_deposit_balance(producer=producer)
    assert deposit["received_lb"] == "3900.00"


@pytest.mark.django_db
def test_recibo_acopio_tara_explicita_prevalece_sobre_calidad():
    """Si se pasa tara explícita, esa manda (no la de la calidad): bruto 1530.50,
    tara explícita 30.50 → neto 1500.00, aunque la calidad diga 1%."""
    pytest.importorskip("apps.modulos.financiamiento.services")
    from apps.modulos.financiamiento import services as fin
    from apps.modulos.parties.models import Party

    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    custody = create_warehouse(request=req, company=company, branch=branch, actor_user=actor,
                               name="Custodia", code=f"CU{uuid.uuid4().hex[:4]}")
    own = create_warehouse(request=req, company=company, branch=branch, actor_user=actor,
                           name="Propia", code=f"PR{uuid.uuid4().hex[:4]}")
    item = InventoryItem.objects.create(
        company=company, sku=f"CAFE-{uuid.uuid4().hex[:6]}", name="Café", uom=UoM.POUND,
    )
    row = fin.get_or_create_settings(company=company)
    row.coffee_item = item
    row.custody_warehouse = custody
    row.liquidation_warehouse = own
    row.save()
    quality = fin.create_quality_grade(
        company=company, code=f"A{uuid.uuid4().hex[:3]}", name="Primera",
        default_tare_pct=Decimal("1.00"),
    )
    party = Party.objects.create(
        company=company, party_type=Party.PartyType.NATURAL, display_name="Productor Y",
        national_id=f"001-{uuid.uuid4().hex[:9]}",
    )
    producer = fin.create_producer(company=company, party=party, acopio_code="08-088")

    r = fin.receive_coffee(
        request=req, actor=actor, producer=producer, quality=quality,
        physical_state="SECO", sacks=15, gross_lb=Decimal("1530.50"), tare_lb=Decimal("30.50"),
    )
    assert r.tare_lb == Decimal("30.50")   # explícita, NO el 1% de calidad (=15.305)
    assert r.net_lb == Decimal("1500.00")
    assert r.gross_lb == r.net_lb + r.tare_lb
