"""HUECO 1 (POS-422) — venta sin existencias debe responder 422 de dominio.

Antes, vender un ítem sin stock suficiente propagaba el ValueError tipado del kernel
de inventario (InsufficientStockError) como un 500 con traceback crudo. El fix en
ventas/services.py (~369-374) lo traduce a `SalesError("SALES_INSUFFICIENT_STOCK")`,
con rollback del borrador recién creado (atomic). Estos tests blindan ese contrato a
nivel de servicio y de HTTP.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.kernels.facturacion.models import BillingDocument, DocStatus
from apps.kernels.inventarios.models import InventoryItem, StockBalance, UoM
from apps.kernels.inventarios.services import create_warehouse, post_receive
from apps.kernels.payments.services import open_cash_session_for_scope
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission
from apps.modulos.ventas.services import SalesError, pos_sale

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
        path="/test/sales/", method="POST", request_id=f"req-{uuid.uuid4().hex[:8]}",
    )


def _seed_item(req, company, branch, actor, *, price="100.00", tax="0.15", qty="10"):
    wh = create_warehouse(request=req, company=company, branch=branch, actor_user=actor, name="Bodega", code="W1")
    item = InventoryItem.objects.create(
        company=company, sku=f"SKU{uuid.uuid4().hex[:6]}", name="Aceite 1L", uom=UoM.UNIT,
        barcode=f"75{uuid.uuid4().hex[:10]}",
        sale_price=Decimal(price) if price is not None else None,
        default_tax_rate=Decimal(tax),
    )
    if qty is not None and Decimal(qty) > 0:
        post_receive(
            request=req, actor=actor, warehouse_id=wh.id, item_id=item.id,
            qty=Decimal(qty), unit_cost=Decimal("60"), idempotency_key=f"rcv-{uuid.uuid4().hex}",
        )
    return wh, item


def _open_session(company, branch, actor, *, opening="500.00"):
    return open_cash_session_for_scope(
        company=company, branch=branch, actor=actor, opening_amount=Decimal(opening)
    )


def _stock(company, branch, wh, item):
    bal = StockBalance.objects.filter(company=company, branch=branch, warehouse=wh, item=item).first()
    return bal.qty_on_hand if bal else Decimal("0.0000")


def _client(company, branch, perms):
    username = f"u_{uuid.uuid4().hex[:10]}"
    user = User.objects.create_user(username=username, email=f"{username}@t.local", password="x")
    UserMembership.objects.create(user=user, org_unit=company, is_active=True)
    UserMembership.objects.create(user=user, org_unit=branch, is_active=True)

    role = Role.objects.create(name=f"r_{uuid.uuid4().hex[:8]}", is_active=True)
    for p in perms:
        perm, _ = Permission.objects.get_or_create(code=p, defaults={"description": p, "is_active": True})
        RolePermission.objects.get_or_create(role=role, permission=perm)
    RoleAssignment.objects.create(user=user, role=role, org_unit=company, is_active=True)
    RoleAssignment.objects.create(user=user, role=role, org_unit=branch, is_active=True)

    c = APIClient()
    login = c.post("/api/auth/login/", {"username": username, "password": "x"}, format="json")
    assert login.status_code == 200
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    c.defaults["HTTP_X_COMPANY_ID"] = str(company.id)
    c.defaults["HTTP_X_BRANCH_ID"] = str(branch.id)
    return c, user


# ---------------------------------------------------------------------------
# Servicio
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_sale_with_zero_stock_raises_domain_error_not_500():
    """Sin existencias en absoluto: el servicio lanza SALES_INSUFFICIENT_STOCK."""
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed_item(req, company, branch, actor, price="100.00", tax="0", qty="0")
    _open_session(company, branch, actor)

    with pytest.raises(SalesError, match="SALES_INSUFFICIENT_STOCK"):
        pos_sale(
            request=req, actor=actor, warehouse_id=wh.id,
            lines=[{"inventory_item_id": item.id, "quantity": "1"}],
            payments=[{"method": "CASH", "amount": "100.00"}],
            idempotency_key="POS-NOSTOCK",
        )


@pytest.mark.django_db
def test_sale_exceeding_available_stock_raises_domain_error():
    """Hay 3 unidades pero se piden 5: debe ser error de dominio, no 500."""
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed_item(req, company, branch, actor, price="100.00", tax="0", qty="3")
    _open_session(company, branch, actor)

    with pytest.raises(SalesError, match="SALES_INSUFFICIENT_STOCK"):
        pos_sale(
            request=req, actor=actor, warehouse_id=wh.id,
            lines=[{"inventory_item_id": item.id, "quantity": "5"}],
            payments=[{"method": "CASH", "amount": "500.00"}],
            idempotency_key="POS-OVERSELL",
        )


@pytest.mark.django_db
def test_insufficient_stock_rolls_back_no_doc_no_stock_change():
    """El borrador recién creado se descarta (atomic): ni documento emitido ni stock tocado."""
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed_item(req, company, branch, actor, price="100.00", tax="0", qty="2")
    _open_session(company, branch, actor)

    with pytest.raises(SalesError, match="SALES_INSUFFICIENT_STOCK"):
        pos_sale(
            request=req, actor=actor, warehouse_id=wh.id,
            lines=[{"inventory_item_id": item.id, "quantity": "9"}],
            payments=[{"method": "CASH", "amount": "900.00"}],
            idempotency_key="POS-RB",
        )

    # Rollback total: ningún documento emitido y stock intacto en 2.
    assert not BillingDocument.objects.filter(company=company, status=DocStatus.ISSUED).exists()
    assert _stock(company, branch, wh, item) == Decimal("2.0000")


@pytest.mark.django_db
def test_sale_at_exact_available_stock_succeeds():
    """Control positivo: pedir exactamente lo disponible NO debe disparar el guard."""
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed_item(req, company, branch, actor, price="100.00", tax="0", qty="4")
    _open_session(company, branch, actor)

    res = pos_sale(
        request=req, actor=actor, warehouse_id=wh.id,
        lines=[{"inventory_item_id": item.id, "quantity": "4"}],
        payments=[{"method": "CASH", "amount": "400.00"}],
        idempotency_key="POS-EXACT",
    )
    assert res["total"] == "400.00"
    assert _stock(company, branch, wh, item) == Decimal("0.0000")


# ---------------------------------------------------------------------------
# HTTP: el contrato visible al frontend es 422, nunca 500
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_http_insufficient_stock_returns_422_with_envelope():
    _h, company, branch = _scope()
    seeder = _user()
    req = _req(company, branch, seeder)
    wh, item = _seed_item(req, company, branch, seeder, price="100.00", tax="0", qty="1")

    c_seller, seller = _client(company, branch, perms=["sales.pos.sell"])
    open_cash_session_for_scope(company=company, branch=branch, actor=seller)

    r = c_seller.post("/api/sales/pos-sale/", {
        "warehouse_id": wh.id, "idempotency_key": "H-NOSTOCK",
        "lines": [{"inventory_item_id": item.id, "quantity": "5"}],
        "payments": [{"method": "CASH", "amount": "500.00"}],
    }, format="json")

    assert r.status_code == 422, r.data
    assert r.data["error"]["message"] == "SALES_INSUFFICIENT_STOCK"


# ---------------------------------------------------------------------------
# BUG ABIERTO 1 (revisión 2026-06-22): ValueError C1 en inventarios/services.py
# (post_issue) por venta sin stock, registrado en diagnostics como POST
# /api/sales/pos-sale/ → 500 (occurrence=2). Causa raíz: el kernel lanzaba
# `raise ValueError("stock insuficiente")` (bare) y el POS no lo traducía → 500.
# Reparado: post_issue ahora lanza `InsufficientStockError` (subclase TIPADA de
# ValueError) y pos_sale lo captura → 422. Estos tests pinnean el diagnóstico para
# que nunca vuelva a escapar un ValueError crudo del kernel al endpoint del POS.
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_kernel_signals_insufficient_stock_as_typed_error_not_bare_valueerror():
    """El kernel debe señalar la falta de stock con la excepción TIPADA, no un
    ValueError genérico: así el POS puede distinguirla y devolver 422 en vez de 500
    (que es lo que el diagnóstico registró el 2026-06-22 en post_issue)."""
    from apps.kernels.inventarios.services import InsufficientStockError, post_issue

    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed_item(req, company, branch, actor, price="100.00", tax="0", qty="1")

    with pytest.raises(InsufficientStockError):
        post_issue(
            request=req, actor=actor, warehouse_id=wh.id, item_id=item.id,
            qty=Decimal("5"), idempotency_key=f"issue-{uuid.uuid4().hex}",
        )


@pytest.mark.django_db
def test_http_insufficient_stock_never_returns_500():
    """Regresión directa del ErrorEvent C1 (post_issue ValueError → 500): el POST a
    pos-sale sin stock NO debe responder 500 bajo ninguna circunstancia."""
    _h, company, branch = _scope()
    seeder = _user()
    req = _req(company, branch, seeder)
    wh, item = _seed_item(req, company, branch, seeder, price="100.00", tax="0", qty="0")

    c_seller, seller = _client(company, branch, perms=["sales.pos.sell"])
    open_cash_session_for_scope(company=company, branch=branch, actor=seller)

    r = c_seller.post("/api/sales/pos-sale/", {
        "warehouse_id": wh.id, "idempotency_key": "H-NO-500",
        "lines": [{"inventory_item_id": item.id, "quantity": "3"}],
        "payments": [{"method": "CASH", "amount": "300.00"}],
    }, format="json")

    assert r.status_code != 500, r.data
    assert r.status_code == 422, r.data
    assert r.data["error"]["message"] == "SALES_INSUFFICIENT_STOCK"
