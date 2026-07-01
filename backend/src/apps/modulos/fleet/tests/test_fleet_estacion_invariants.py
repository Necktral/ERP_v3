"""Invariantes de negocio de FLEET (costos por activo) + ESTACIÓN (tanques).

Archivo NUEVO. Ataca invariantes que los tests felices existentes dejan flojos:

FLEET — asset_cost_summary (services_costs.asset_cost_summary):
  * cost_per_unit y consumption con VALORES EXACTOS (el test vecino solo verifica
    `is not None`).  cost/km = (fuel+maint+gastos)/Σdistancia; consumo = Σdist/Σlitros.
  * Una work order CANCELLED no debe sumar al costo (se excluye).
  * Sin distancia/litros, los ratios son None (sin dividir por cero).

ESTACIÓN — tanque (tank_service + record_dispense):
  * CONSERVACIÓN: nivel = Σ recepciones − Σ despachos (+ ajustes) tras N operaciones.
  * Hook ADITIVO en record_dispense descuenta LITROS CANÓNICOS (galón→litro),
    no el volumen 'entered'.
  * Hook NO-OP sin tanque del producto: el despacho NO falla y NO descuenta.
  * Hook descuenta SOLO del tanque del producto despachado (no toca otro producto).

Reusa el patrón de fixtures de los tests vecinos (test_fleet_costs.py, test_tanks.py).
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.modulos.estacion_servicios.models import (
    FuelProduct,
    FuelShift,
    FuelShiftStatus,
    FuelTank,
    FuelTankMovement,
)
from apps.modulos.estacion_servicios.models import GALLON_TO_LITER
from apps.modulos.estacion_servicios.services import record_dispense
from apps.modulos.estacion_servicios.tank_service import (
    adjust_tank,
    apply_dispense_to_tank,
    create_tank,
    receive_fuel,
)
from apps.modulos.fleet.models import AssetType, FleetAsset, MaintenanceWorkOrder, MeterBasis
from apps.modulos.fleet.services_costs import (
    asset_cost_summary,
    record_expense,
    record_fuel_log,
    record_work_order,
)
from apps.modulos.iam.models import OrgUnit

User = get_user_model()
UT = OrgUnit.UnitType


# ---------------------------------------------------------------------------
# Helpers (estilo de test_fleet_costs.py / test_tanks.py)
# ---------------------------------------------------------------------------

def _mk_company():
    s = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=UT.HOLDING, name=f"H_{s}")
    return OrgUnit.objects.create(unit_type=UT.COMPANY, name=f"C_{s}", parent=holding)


def _mk_org():
    s = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=UT.HOLDING, name=f"H_{s}")
    company = OrgUnit.objects.create(unit_type=UT.COMPANY, name=f"C_{s}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=UT.BRANCH, name=f"B_{s}", parent=company)
    return company, branch


def _mk_user():
    u = f"fl_{uuid.uuid4().hex[:8]}"
    return User.objects.create_user(username=u, email=f"{u}@t.local", password="pass12345")


def _mk_asset(company, odo="1000", basis=MeterBasis.ODOMETER_KM):
    return FleetAsset.objects.create(
        company=company, asset_type=AssetType.choices[0][0], code=f"A{uuid.uuid4().hex[:4]}",
        name="Camión", meter_basis=basis, current_odometer_km=Decimal(odo),
    )


def _tank(company, branch, actor, product=FuelProduct.DIESEL, capacity="20000"):
    return create_tank(
        company=company, branch=branch, actor=actor, code=f"T{uuid.uuid4().hex[:4]}",
        product=product, capacity_l=Decimal(capacity),
    )


# ===========================================================================
# FLEET — COSTO/KM: valores EXACTOS (no solo "is not None")
# ===========================================================================

@pytest.mark.django_db
def test_cost_per_km_y_consumo_exactos():
    """Datos conocidos:
      - Carga 1: 60 L @ 1.25 = 75.00, lectura 1000 (distancia 0, base = odómetro).
      - Carga 2: 45 L @ 1.30 = 58.50, lectura 1450 → distancia 450.
      - Mantenimiento: 250 + 480 = 730.00.
      - Gasto (llantas): 1200.00.
    Totales: fuel = 133.50, maint = 730.00, gastos = 1200.00, grand = 2063.50.
    Litros = 105.00, distancia = 450.00.
    cost/km = 2063.50 / 450 = 4.585... → 4.59 (2dp).
    consumo = 450 / 105 = 4.2857... → 4.29 km/L (2dp)."""
    company = _mk_company()
    actor = _mk_user()
    asset = _mk_asset(company, odo="1000")

    record_fuel_log(company=company, actor=actor, asset_id=asset.id,
                    liters=Decimal("60"), unit_cost=Decimal("1.25"), meter_reading=Decimal("1000"))
    record_fuel_log(company=company, actor=actor, asset_id=asset.id,
                    liters=Decimal("45"), unit_cost=Decimal("1.30"), meter_reading=Decimal("1450"))
    record_work_order(company=company, actor=actor, asset_id=asset.id, description="Frenos",
                      labor_cost=Decimal("250"), parts_cost=Decimal("480"))
    record_expense(company=company, actor=actor, asset_id=asset.id, category="TIRES",
                   amount=Decimal("1200"))

    s = asset_cost_summary(company=company, asset_id=asset.id)
    assert s["fuel_total"] == "133.50"
    assert s["maintenance_total"] == "730.00"
    assert s["expense_total"] == "1200.00"
    assert s["grand_total"] == "2063.50"
    assert s["liters_total"] == "105.00"
    assert s["distance_total"] == "450.00"
    # 2063.50 / 450 = 4.58555... → 4.59
    assert s["cost_per_unit"] == "4.59"
    # 450 / 105 = 4.28571... → 4.29
    assert s["consumption"] == "4.29"
    assert s["cost_per_unit_label"] == "Costo/km"
    assert s["consumption_label"] == "km/L"


@pytest.mark.django_db
def test_work_order_cancelada_no_suma_al_costo():
    """Una WO CANCELLED se EXCLUYE del resumen; una DONE sí cuenta."""
    company = _mk_company()
    actor = _mk_user()
    asset = _mk_asset(company)
    record_work_order(company=company, actor=actor, asset_id=asset.id, description="Aceite",
                      labor_cost=Decimal("100"), parts_cost=Decimal("50"))  # DONE → cuenta
    record_work_order(company=company, actor=actor, asset_id=asset.id, description="Cancelada",
                      labor_cost=Decimal("9999"), parts_cost=Decimal("9999"),
                      status=MaintenanceWorkOrder.Status.CANCELLED)
    s = asset_cost_summary(company=company, asset_id=asset.id)
    assert s["maintenance_total"] == "150.00"  # solo la DONE; la cancelada NO entra
    assert s["grand_total"] == "150.00"


@pytest.mark.django_db
def test_cost_per_km_none_sin_distancia_pero_consumo_cero():
    """Carga SIN lectura de medidor → distancia 0.  El contrato del servicio:
    - cost_per_unit = None cuando NO hay distancia (no divide por cero).
    - consumption = 0.00 (Σdist/Σlitros = 0/40) porque SÍ hay litros (> 0).
    Verifica que no explota y respeta el guard `distance_total > 0` / `liters_total > 0`."""
    company = _mk_company()
    actor = _mk_user()
    asset = _mk_asset(company)
    # Combustible SIN lectura de medidor → distance_since_last = None (no agrega distancia).
    record_fuel_log(company=company, actor=actor, asset_id=asset.id,
                    liters=Decimal("40"), unit_cost=Decimal("1.50"))
    s = asset_cost_summary(company=company, asset_id=asset.id)
    assert s["distance_total"] == "0.00"
    assert s["cost_per_unit"] is None      # sin km → costo/km None (guard distance>0)
    assert s["consumption"] == "0.00"      # litros>0, distancia 0 → 0/40 = 0.00
    assert s["liters_total"] == "40.00"


@pytest.mark.django_db
def test_horometro_cambia_etiquetas_a_hora():
    """Un activo por horómetro reporta Costo/hora y h/L, no km."""
    company = _mk_company()
    actor = _mk_user()
    asset = FleetAsset.objects.create(
        company=company, asset_type=AssetType.choices[0][0], code=f"A{uuid.uuid4().hex[:4]}",
        name="Tractor", meter_basis=MeterBasis.HOURMETER, current_hourmeter=Decimal("500"),
    )
    record_fuel_log(company=company, actor=actor, asset_id=asset.id,
                    liters=Decimal("20"), unit_cost=Decimal("2.00"), meter_reading=Decimal("500"))
    record_fuel_log(company=company, actor=actor, asset_id=asset.id,
                    liters=Decimal("20"), unit_cost=Decimal("2.00"), meter_reading=Decimal("540"))
    s = asset_cost_summary(company=company, asset_id=asset.id)
    assert s["cost_per_unit_label"] == "Costo/hora"
    assert s["consumption_label"] == "h/L"
    assert s["distance_total"] == "40.00"  # 540 − 500 horas


# ===========================================================================
# ESTACIÓN — CONSERVACIÓN del nivel del tanque tras N operaciones
# ===========================================================================

@pytest.mark.django_db
def test_nivel_tanque_conservacion_multiples_operaciones():
    """nivel = Σ recepciones − Σ despachos + ajustes, conservado tras varias ops.
    Recepciones: 5000 + 3000 = 8000.  Despachos (vía hook): 150 + 220.5 = 370.5.
    Ajuste: −12.75 (merma).  Nivel final = 8000 − 370.5 − 12.75 = 7616.75."""
    company, branch = _mk_org()
    actor = _mk_user()
    tank = _tank(company, branch, actor, product=FuelProduct.DIESEL, capacity="20000")

    receive_fuel(company=company, actor=actor, tank_id=tank.id, liters=Decimal("5000"))
    receive_fuel(company=company, actor=actor, tank_id=tank.id, liters=Decimal("3000"))
    apply_dispense_to_tank(company=company, branch=branch, product=FuelProduct.DIESEL,
                           liters=Decimal("150"), dispense=None, actor=actor)
    apply_dispense_to_tank(company=company, branch=branch, product=FuelProduct.DIESEL,
                           liters=Decimal("220.5"), dispense=None, actor=actor)
    adjust_tank(company=company, actor=actor, tank_id=tank.id, liters=Decimal("-12.75"),
                reason="Merma evaporación")

    tank.refresh_from_db()
    assert tank.current_volume_l == Decimal("7616.7500")

    # Conservación auditada: nivel == suma firmada de todos los movimientos.
    suma = sum((m.liters for m in tank.movements.all()), Decimal("0"))
    assert Decimal(tank.current_volume_l) == suma
    # Los despachos quedan como movimientos negativos.
    assert tank.movements.filter(kind=FuelTankMovement.Kind.DISPENSE).count() == 2


@pytest.mark.django_db
def test_record_dispense_galones_descuenta_litros_canonicos():
    """Despacho de 10 GALONES: el tanque debe descontar los LITROS canónicos
    (10 × 3.785411784 = 37.85411784 → 4dp = 37.8541), NO los 10 'entered'.
    Nivel: 1000 − 37.8541 = 962.1459."""
    company, branch = _mk_org()
    actor = _mk_user()
    tank = _tank(company, branch, actor, product=FuelProduct.DIESEL, capacity="5000")
    receive_fuel(company=company, actor=actor, tank_id=tank.id, liters=Decimal("1000"))
    shift = FuelShift.objects.create(company=company, branch=branch,
                                     status=FuelShiftStatus.OPEN, opened_by=actor)

    litros_canon = (Decimal("10") * GALLON_TO_LITER).quantize(Decimal("0.0001"))
    assert litros_canon == Decimal("37.8541")  # sanity del contrato de conversión

    record_dispense(
        company=company, branch=branch, shift=shift, actor_user=actor,
        product=FuelProduct.DIESEL, volume_entered=Decimal("10"), volume_uom="GALLON",
        unit_price_entered=Decimal("130.00"), unit_price_uom="PER_GALLON",
    )
    tank.refresh_from_db()
    assert tank.current_volume_l == Decimal("962.1459")  # 1000 − 37.8541
    mv = tank.movements.filter(kind=FuelTankMovement.Kind.DISPENSE).first()
    assert mv is not None
    assert mv.liters == Decimal("-37.8541")  # descuenta litros, no galones


@pytest.mark.django_db
def test_record_dispense_sin_tanque_no_falla_ni_descuenta():
    """Camino NO-OP: sin tanque del producto, record_dispense SÍ registra la venta
    (FuelDispense) pero NO crea movimiento de tanque ni rompe."""
    company, branch = _mk_org()
    actor = _mk_user()
    # NO se crea ningún tanque.
    shift = FuelShift.objects.create(company=company, branch=branch,
                                     status=FuelShiftStatus.OPEN, opened_by=actor)
    d = record_dispense(
        company=company, branch=branch, shift=shift, actor_user=actor,
        product=FuelProduct.GASOLINE, volume_entered=Decimal("25"), volume_uom="LITER",
        unit_price_entered=Decimal("48.50"), unit_price_uom="PER_LITER",
    )
    assert d.id is not None
    assert d.liters == Decimal("25.0000")
    # No hay ningún tanque ni movimiento de tanque en toda la empresa.
    assert FuelTank.objects.filter(company=company).count() == 0
    assert FuelTankMovement.objects.filter(tank__company=company).count() == 0


@pytest.mark.django_db
def test_hook_descuenta_solo_el_tanque_del_producto_despachado():
    """Con un tanque DIESEL y otro GASOLINE en la misma sucursal, despachar
    DIESEL descuenta SOLO del DIESEL; el GASOLINE no se toca."""
    company, branch = _mk_org()
    actor = _mk_user()
    t_diesel = _tank(company, branch, actor, product=FuelProduct.DIESEL, capacity="10000")
    t_gas = _tank(company, branch, actor, product=FuelProduct.GASOLINE, capacity="10000")
    receive_fuel(company=company, actor=actor, tank_id=t_diesel.id, liters=Decimal("4000"))
    receive_fuel(company=company, actor=actor, tank_id=t_gas.id, liters=Decimal("3000"))

    apply_dispense_to_tank(company=company, branch=branch, product=FuelProduct.DIESEL,
                           liters=Decimal("500"), dispense=None, actor=actor)

    t_diesel.refresh_from_db()
    t_gas.refresh_from_db()
    assert t_diesel.current_volume_l == Decimal("3500.0000")  # descontó
    assert t_gas.current_volume_l == Decimal("3000.0000")     # intacto
    assert t_gas.movements.filter(kind=FuelTankMovement.Kind.DISPENSE).count() == 0


@pytest.mark.django_db
def test_hook_noop_no_descuenta_tanque_de_otra_sucursal():
    """Multi-sucursal: el tanque está en branch A; un despacho en branch B (sin
    tanque) es NO-OP y NO descuenta el tanque de A (no hay fuga entre sucursales)."""
    company, branch_a = _mk_org()
    branch_b = OrgUnit.objects.create(unit_type=UT.BRANCH, name=f"BB_{uuid.uuid4().hex[:4]}",
                                      parent=company)
    actor = _mk_user()
    tank_a = _tank(company, branch_a, actor, product=FuelProduct.DIESEL, capacity="10000")
    receive_fuel(company=company, actor=actor, tank_id=tank_a.id, liters=Decimal("2000"))

    mv = apply_dispense_to_tank(company=company, branch=branch_b, product=FuelProduct.DIESEL,
                                liters=Decimal("100"), dispense=None, actor=actor)
    assert mv is None  # sin tanque en branch B → no-op
    tank_a.refresh_from_db()
    assert tank_a.current_volume_l == Decimal("2000.0000")  # el de A NO se tocó
