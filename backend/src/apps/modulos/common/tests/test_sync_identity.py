"""Tests de F0 — identidad de sincronización entre nodos.

Cubre el generador de ULID (formato, unicidad, orden monotónico), el código de nodo,
los defaults del mixin `Syncable` (sin DB) y el mapa de identidad `SyncIdentity`
(idempotente, traducción `sync_uid` ↔ PK local, namespacing por modelo).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.modulos.common.sync_identity import (
    ULID_LEN,
    current_node_code,
    is_ulid,
    new_ulid,
    register_identity,
    register_syncable,
    resolve_local_id,
)


# ---------------------------------------------------------------------------
# ULID (sin DB)
# ---------------------------------------------------------------------------

def test_new_ulid_tiene_formato_valido():
    uid = new_ulid()
    assert len(uid) == ULID_LEN == 26
    assert is_ulid(uid)
    # Crockford base32: mayúsculas, sin I L O U
    assert not any(ch in uid for ch in "ILOU")


def test_new_ulid_es_unico_en_masa():
    uids = [new_ulid() for _ in range(5000)]
    assert len(set(uids)) == 5000  # cero colisiones


def test_new_ulid_es_monotonico_y_ordenable():
    # Aunque se generen en el mismo milisegundo, el orden lexicográfico debe reflejar
    # el orden de creación (parte aleatoria que se incrementa).
    uids = [new_ulid() for _ in range(1000)]
    assert uids == sorted(uids)
    assert all(a < b for a, b in zip(uids, uids[1:]))


def test_new_ulid_respeta_timestamp_provisto():
    early = new_ulid(now_ms=1_000_000_000_000)
    later = new_ulid(now_ms=2_000_000_000_000)
    assert early < later  # el prefijo de tiempo ordena


def test_is_ulid_rechaza_invalidos():
    assert not is_ulid("")
    assert not is_ulid("abc")  # muy corto
    assert not is_ulid("a" * 26)  # minúsculas no son Crockford válidas aquí
    assert not is_ulid("I" * 26)  # I no está en el alfabeto
    assert not is_ulid(None)
    assert not is_ulid(123)


# ---------------------------------------------------------------------------
# Código de nodo
# ---------------------------------------------------------------------------

def test_current_node_code_default(settings):
    settings.SYNC_NODE_CODE = ""
    assert current_node_code() == "LOCAL"


def test_current_node_code_configurable(settings):
    settings.SYNC_NODE_CODE = "FINCA-A"
    assert current_node_code() == "FINCA-A"


# ---------------------------------------------------------------------------
# Mixin Syncable — defaults sin tocar la DB
# ---------------------------------------------------------------------------

def test_syncable_mixin_autoasigna_identidad(settings):
    settings.SYNC_NODE_CODE = "NODO-X"
    from apps.kernels.nomina.models import PayrollPayment

    p1 = PayrollPayment()
    p2 = PayrollPayment()
    assert is_ulid(p1.sync_uid)
    assert is_ulid(p2.sync_uid)
    assert p1.sync_uid != p2.sync_uid  # identidad por instancia
    assert p1.origin_node == "NODO-X"


# ---------------------------------------------------------------------------
# Mapa de identidad (con DB)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_register_identity_es_idempotente():
    uid = new_ulid()
    a = register_identity(model_label="nomina.payrollpayment", sync_uid=uid, local_id=7, origin_node="FINCA-A")
    # registrar otra vez NO duplica ni reescribe el local_id (gana la primera escritura)
    b = register_identity(model_label="nomina.payrollpayment", sync_uid=uid, local_id=999, origin_node="OTRO")
    assert a.pk == b.pk
    assert resolve_local_id(model_label="nomina.payrollpayment", sync_uid=uid) == 7


@pytest.mark.django_db
def test_resolve_local_id_desconocido_es_none():
    assert resolve_local_id(model_label="nomina.payrollpayment", sync_uid=new_ulid()) is None


@pytest.mark.django_db
def test_identity_map_namespaced_por_modelo():
    uid = new_ulid()  # mismo sync_uid bajo dos modelos distintos
    register_identity(model_label="nomina.payrollpayment", sync_uid=uid, local_id=10)
    register_identity(model_label="ventas.saleorder", sync_uid=uid, local_id=20)
    assert resolve_local_id(model_label="nomina.payrollpayment", sync_uid=uid) == 10
    assert resolve_local_id(model_label="ventas.saleorder", sync_uid=uid) == 20


@pytest.mark.django_db
def test_register_syncable_usa_meta_label_y_pk():
    uid = new_ulid()
    fake = SimpleNamespace(
        sync_uid=uid,
        pk=42,
        origin_node="FINCA-B",
        _meta=SimpleNamespace(label_lower="nomina.payrollpayment"),
    )
    row = register_syncable(fake)
    assert row.local_id == 42
    assert row.origin_node == "FINCA-B"
    assert resolve_local_id(model_label="nomina.payrollpayment", sync_uid=uid) == 42
