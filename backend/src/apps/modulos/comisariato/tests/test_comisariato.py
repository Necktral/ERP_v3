"""Tests del vertical comisariato (tienda de la empresa que vende a crédito).

Cubre: venta a crédito sobre facturacion (baja inventario + CxC + factura), enforce de
límite con rollback, idempotencia por reference_code, y HTTP/RBAC. NOTA: la nómina NO cobra
comisariato (prohibido) → el lazo de cobro por planilla se eliminó; la CxC se cobra por otros
medios (caja/portfolio), nunca por la planilla.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.kernels.facturacion.models import BillingDocument, DocStatus
from apps.kernels.inventarios.models import InventoryItem, StockBalance, UoM
from apps.kernels.inventarios.services import create_warehouse, post_receive
from apps.kernels.portfolio.models import Receivable
from apps.modulos.comisariato.models import CustomerSegment
from apps.modulos.comisariato.services import (
    ComisariatoError,
    get_or_create_account,
    sell_on_credit,
)
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.parties.models import Party
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

User = get_user_model()
UT = OrgUnit.UnitType


def _scope():
    t = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=UT.HOLDING, name=f"H{t}", code=f"H-{t}")
    comis = OrgUnit.objects.create(unit_type=UT.COMPANY, parent=holding, name=f"Comis{t}", code=f"K-{t}")
    comis_br = OrgUnit.objects.create(unit_type=UT.BRANCH, parent=comis, name=f"KB{t}", code=f"KB-{t}")
    return holding, comis, comis_br


def _user():
    t = uuid.uuid4().hex[:8]
    return User.objects.create_user(username=f"u_{t}", email=f"u_{t}@t.local", password="pass12345")


def _req(company, branch, user):
    return SimpleNamespace(
        company=company, branch=branch, user=user, META={}, headers={},
        path="/test/comisariato/", method="POST", request_id=f"req-{uuid.uuid4().hex[:8]}",
    )


def _party(company, *, national_id=""):
    t = uuid.uuid4().hex[:6]
    return Party.objects.create(
        company=company, party_type=Party.PartyType.NATURAL,
        display_name=f"Cliente {t}", national_id=national_id,
    )


def _seed_item_stock(req, company, branch, actor, *, qty="10", unit_cost="30"):
    wh = create_warehouse(request=req, company=company, branch=branch, actor_user=actor, name="Bodega", code="W1")
    item = InventoryItem.objects.create(company=company, sku=f"SKU{uuid.uuid4().hex[:6]}", name="Arroz", uom=UoM.UNIT)
    post_receive(
        request=req, actor=actor, warehouse_id=wh.id, item_id=item.id,
        qty=Decimal(qty), unit_cost=Decimal(unit_cost), idempotency_key=f"rcv-{uuid.uuid4().hex}",
    )
    return wh, item


def _account(req, actor, company, party, *, limit="1000", segment=CustomerSegment.EMPLOYEE, collecting=None):
    return get_or_create_account(
        request=req, actor=actor, company=company, party=party, segment=segment,
        credit_limit=Decimal(limit), collecting_company=collecting,
    )


def _stock_on_hand(company, branch, wh, item):
    bal = StockBalance.objects.filter(company=company, branch=branch, warehouse=wh, item=item).first()
    return bal.qty_on_hand if bal else Decimal("0.0000")


# ---------------------------------------------------------------------------
# Venta a crédito
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_sell_on_credit_creates_receivable_and_decrements_stock():
    _h, comis, comis_br = _scope()
    actor = _user()
    req = _req(comis, comis_br, actor)
    wh, item = _seed_item_stock(req, comis, comis_br, actor, qty="10", unit_cost="30")
    party = _party(comis, national_id="001-111")
    account = _account(req, actor, comis, party, limit="1000")

    res = sell_on_credit(
        request=req, actor=actor, account=account, warehouse_id=wh.id,
        lines=[{"description": "Arroz 2u", "quantity": "2", "unit_price": "50", "tax_rate": "0",
                "inventory_item_id": item.id}],
        reference_code="VTA-001",
    )

    assert res["status"] == DocStatus.ISSUED
    assert res["duplicate"] is False
    assert res["total"] == "100.00"
    assert res["available_after"] == "900.00"

    rec = Receivable.objects.get(company=comis, reference_type="BILLING_DOC", reference_id=res["doc_id"])
    assert rec.party_id == party.id
    assert rec.principal_amount == Decimal("100.00")
    assert _stock_on_hand(comis, comis_br, wh, item) == Decimal("8.0000")
    # Vencimiento real: la cuenta default tiene 30 días de crédito.
    assert rec.due_date == rec.issue_date + timedelta(days=30)


@pytest.mark.django_db
def test_receivable_due_date_uses_account_credit_days():
    """A2: due_date = emisión + credit_days de la cuenta (antes vencía el mismo día)."""
    _h, comis, comis_br = _scope()
    actor = _user()
    req = _req(comis, comis_br, actor)
    wh, item = _seed_item_stock(req, comis, comis_br, actor)
    party = _party(comis)
    account = get_or_create_account(
        request=req, actor=actor, company=comis, party=party,
        segment=CustomerSegment.PUBLIC, credit_limit=Decimal("500"), credit_days=15,
    )
    assert account.credit_days == 15

    res = sell_on_credit(
        request=req, actor=actor, account=account, warehouse_id=wh.id,
        lines=[{"description": "Arroz", "quantity": "1", "unit_price": "50", "tax_rate": "0",
                "inventory_item_id": item.id}],
        reference_code="VTA-DD-15",
    )
    rec = Receivable.objects.get(company=comis, reference_type="BILLING_DOC", reference_id=res["doc_id"])
    assert rec.due_date == rec.issue_date + timedelta(days=15)
    assert rec.credit_days == 15


@pytest.mark.django_db
def test_credit_limit_exceeded_rolls_back_everything():
    _h, comis, comis_br = _scope()
    actor = _user()
    req = _req(comis, comis_br, actor)
    wh, item = _seed_item_stock(req, comis, comis_br, actor, qty="10", unit_cost="30")
    party = _party(comis, national_id="001-222")
    account = _account(req, actor, comis, party, limit="50")  # tope menor al total (100)

    with pytest.raises(ComisariatoError, match="COMISARIATO_CREDIT_LIMIT_EXCEEDED"):
        sell_on_credit(
            request=req, actor=actor, account=account, warehouse_id=wh.id,
            lines=[{"description": "Arroz 2u", "quantity": "2", "unit_price": "50", "inventory_item_id": item.id}],
            reference_code="VTA-LIM",
        )

    # Rollback total: sin documento emitido, sin CxC, stock intacto.
    assert not BillingDocument.objects.filter(company=comis, source_id="VTA-LIM").exists()
    assert Receivable.objects.filter(company=comis, party=party).count() == 0
    assert _stock_on_hand(comis, comis_br, wh, item) == Decimal("10.0000")


@pytest.mark.django_db
def test_none_limit_is_unlimited_credit():
    """C-01: credit_limit=None = sin tope (ilimitado) → la venta grande pasa."""
    _h, comis, comis_br = _scope()
    actor = _user()
    req = _req(comis, comis_br, actor)
    wh, item = _seed_item_stock(req, comis, comis_br, actor, qty="100", unit_cost="30")
    party = _party(comis, national_id="001-NONE")
    account = get_or_create_account(
        request=req, actor=actor, company=comis, party=party,
        segment=CustomerSegment.EMPLOYEE, credit_limit=None,
    )
    assert account.credit_limit is None
    res = sell_on_credit(
        request=req, actor=actor, account=account, warehouse_id=wh.id,
        lines=[{"description": "Mucho", "quantity": "50", "unit_price": "50", "inventory_item_id": item.id}],
        reference_code="VTA-NONE",
    )
    assert res["status"] == DocStatus.ISSUED
    assert res["available_after"] is None  # sin tope


@pytest.mark.django_db
def test_zero_limit_means_no_credit():
    """C-01: credit_limit=0 = sin crédito → cualquier venta a crédito se rechaza."""
    _h, comis, comis_br = _scope()
    actor = _user()
    req = _req(comis, comis_br, actor)
    wh, item = _seed_item_stock(req, comis, comis_br, actor, qty="10", unit_cost="30")
    party = _party(comis, national_id="001-ZERO")
    account = get_or_create_account(
        request=req, actor=actor, company=comis, party=party,
        segment=CustomerSegment.PUBLIC, credit_limit=Decimal("0.00"),
    )
    with pytest.raises(ComisariatoError, match="COMISARIATO_CREDIT_LIMIT_EXCEEDED"):
        sell_on_credit(
            request=req, actor=actor, account=account, warehouse_id=wh.id,
            lines=[{"description": "Algo", "quantity": "1", "unit_price": "50", "inventory_item_id": item.id}],
            reference_code="VTA-ZERO",
        )


@pytest.mark.django_db
def test_sale_is_idempotent_by_reference_code():
    _h, comis, comis_br = _scope()
    actor = _user()
    req = _req(comis, comis_br, actor)
    wh, item = _seed_item_stock(req, comis, comis_br, actor, qty="10", unit_cost="30")
    party = _party(comis, national_id="001-333")
    account = _account(req, actor, comis, party, limit="1000")
    line = {"description": "Arroz", "quantity": "2", "unit_price": "50", "inventory_item_id": item.id}

    r1 = sell_on_credit(request=req, actor=actor, account=account, warehouse_id=wh.id, lines=[line], reference_code="VTA-DUP")
    r2 = sell_on_credit(request=req, actor=actor, account=account, warehouse_id=wh.id, lines=[line], reference_code="VTA-DUP")

    assert r1["doc_id"] == r2["doc_id"]
    assert r2["duplicate"] is True
    assert Receivable.objects.filter(company=comis, reference_type="BILLING_DOC", reference_id=r1["doc_id"]).count() == 1
    assert _stock_on_hand(comis, comis_br, wh, item) == Decimal("8.0000")  # se despachó una sola vez


# NOTA: la nómina NO cobra comisariato (prohibido). Se quitaron los tests del lazo de cobro por
# planilla (apply_store_credit_deductions): el comisariato cobra su CxC por otros medios, no por
# la planilla. El neto del trabajador es su neto legal completo.


# ---------------------------------------------------------------------------
# HTTP + RBAC
# ---------------------------------------------------------------------------

def _client(user, company, branch, perms: list[str]) -> APIClient:
    UserMembership.objects.get_or_create(user=user, org_unit=company, defaults={"is_active": True})
    UserMembership.objects.get_or_create(user=user, org_unit=branch, defaults={"is_active": True})
    role = Role.objects.create(name=f"r_{uuid.uuid4().hex[:8]}", is_active=True)
    for code in perms:
        perm, _ = Permission.objects.get_or_create(code=code, defaults={"description": code, "is_active": True})
        RolePermission.objects.get_or_create(role=role, permission=perm)
    RoleAssignment.objects.create(user=user, role=role, org_unit=company, is_active=True)
    RoleAssignment.objects.create(user=user, role=role, org_unit=branch, is_active=True)
    c = APIClient()
    login = c.post(
        "/api/auth/login/", {"username": user.username, "password": "pass12345"},
        format="json", HTTP_X_AUTH_TRANSPORT="header",
    )
    assert login.status_code == 200, login.data
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data.get('access')}")
    c.defaults["HTTP_X_AUTH_TRANSPORT"] = "header"
    c.defaults["HTTP_X_COMPANY_ID"] = str(company.id)
    c.defaults["HTTP_X_BRANCH_ID"] = str(branch.id)
    return c


@pytest.mark.django_db
def test_sale_endpoint_forbidden_without_perm():
    _h, comis, comis_br = _scope()
    actor = _user()
    req = _req(comis, comis_br, actor)
    wh, item = _seed_item_stock(req, comis, comis_br, actor)
    party = _party(comis, national_id="003-000")
    account = _account(req, actor, comis, party, limit="1000")

    api = _client(_user(), comis, comis_br, ["comisariato.read"])  # sin comisariato.sell
    r = api.post(
        "/api/comisariato/sales/",
        {"account_id": account.id, "warehouse_id": wh.id, "reference_code": "VTA-HTTP-F",
         "lines": [{"description": "Arroz", "quantity": "1", "unit_price": "50", "inventory_item_id": item.id}]},
        format="json",
    )
    assert r.status_code == 403


@pytest.mark.django_db
def test_sale_endpoint_and_account_detail_http():
    _h, comis, comis_br = _scope()
    actor = _user()
    req = _req(comis, comis_br, actor)
    wh, item = _seed_item_stock(req, comis, comis_br, actor, qty="10", unit_cost="30")
    party = _party(comis, national_id="003-111")
    account = _account(req, actor, comis, party, limit="1000")

    api = _client(_user(), comis, comis_br, ["comisariato.sell", "comisariato.read"])
    r = api.post(
        "/api/comisariato/sales/",
        {"account_id": account.id, "warehouse_id": wh.id, "reference_code": "VTA-HTTP",
         "lines": [{"description": "Arroz", "quantity": "2", "unit_price": "50", "inventory_item_id": item.id}]},
        format="json",
    )
    assert r.status_code == 201, r.data
    assert r.data["status"] == DocStatus.ISSUED

    r2 = api.get(f"/api/comisariato/accounts/{account.id}/")
    assert r2.status_code == 200, r2.data
    assert r2.data["available"] == "900.00"
    assert r2.data["outstanding"] == "100.00"
