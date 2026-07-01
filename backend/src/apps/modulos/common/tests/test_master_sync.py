"""Tests de F2 — bajada de maestros (snapshot + cursor/delta + apply gana-central).

Cubre el cursor por **pk** (Permission, append-only) y por **timestamp** (Holiday, capta
updates), y el `apply_master_rows` (upsert por PK, idempotente, gana el central). Robusto a
filas preexistentes (el test DB ya trae feriados sembrados por migración).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.kernels.nomina.models import Holiday, HolidayDateKind, HolidayLegalType
from apps.modulos.common.master_sync import (
    apply_master_rows,
    build_master_snapshot,
    serialize_master_row,
)
from apps.modulos.iam.models import OrgUnit
from apps.modulos.rbac.models import Permission


@pytest.mark.django_db
def test_snapshot_y_delta_cursor_pk():
    a = Permission.objects.create(code="zz.sync.a", is_active=True)
    b = Permission.objects.create(code="zz.sync.b", is_active=True)

    full = build_master_snapshot("rbac.permission")
    pks = {r["id"] for r in full["rows"]}
    assert a.id in pks and b.id in pks
    cursor = full["next_cursor"]  # {pk: max pk} = b.id (las mías son las últimas)

    c = Permission.objects.create(code="zz.sync.c", is_active=True)  # nueva tras el cursor
    delta = build_master_snapshot("rbac.permission", since=cursor)
    assert delta["count"] == 1
    assert delta["rows"][0]["id"] == c.id
    assert delta["rows"][0]["code"] == "zz.sync.c"


@pytest.mark.django_db
def test_delta_cursor_timestamp_capta_nueva_fila():
    cursor = build_master_snapshot("nomina.holiday")["next_cursor"]
    nuevo = Holiday.objects.create(
        name="Feriado de prueba", legal_type=HolidayLegalType.values[0],
        date_kind=HolidayDateKind.values[0], company=None,
    )
    delta = build_master_snapshot("nomina.holiday", since=cursor)
    assert delta["count"] == 1
    assert delta["rows"][0]["id"] == nuevo.id


@pytest.mark.django_db
def test_apply_upsert_por_pk_gana_central_e_idempotente():
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name="C", code="C-1")
    h = Holiday.objects.create(
        name="Día X", legal_type=HolidayLegalType.values[0], date_kind=HolidayDateKind.values[0],
        company=company, premium_rate=Decimal("2.00"), specific_date=date(2026, 7, 19),
    )
    row = serialize_master_row(Holiday, h)
    pk = h.id

    # Simula un nodo sin la fila: se borra y se aplica el snapshot del central.
    h.delete()
    res1 = apply_master_rows("nomina.holiday", [row])
    assert res1 == {"created": 1, "updated": 0}

    restored = Holiday.objects.get(pk=pk)  # misma PK del central
    assert restored.name == "Día X"
    assert restored.premium_rate == Decimal("2.00")      # Decimal round-trip
    assert restored.specific_date == date(2026, 7, 19)   # date round-trip
    assert restored.company_id == company.id             # FK a maestro por id

    # Reaplicar NO duplica (upsert por PK).
    res2 = apply_master_rows("nomina.holiday", [row])
    assert res2 == {"created": 0, "updated": 1}
    assert Holiday.objects.filter(pk=pk).count() == 1

    # Un valor cambiado en el central se sobrescribe en el nodo (gana el central).
    row["name"] = "Día X (corregido)"
    apply_master_rows("nomina.holiday", [row])
    assert Holiday.objects.get(pk=pk).name == "Día X (corregido)"
