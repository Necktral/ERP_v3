"""Tests de la auto-facturación (pre-tickets de kiosko/tableta).

Cubre: creación con estimado (incluye mayoreo), artículos sin precio, recálculo de
precios al leer, expiración lazy, cancelación idempotente, cobro contado/crédito que
marca CHARGED en la misma transacción, idempotencia del pos_sale con código, scoping
por company y RBAC del permiso sales.pos.self_service.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.kernels.inventarios.models import InventoryItem, UoM
from apps.kernels.inventarios.services import create_warehouse, post_receive
from apps.kernels.payments.services import open_cash_session_for_scope
from apps.modulos.comisariato.models import CustomerSegment
from apps.modulos.comisariato.services import get_or_create_account
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.parties.models import Party
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission
from apps.modulos.ventas.models import SelfServiceStatus, SelfServiceTicket
from apps.modulos.ventas.services import (
    SalesError,
    cancel_self_service_ticket,
    create_self_service_ticket,
    get_self_service_ticket,
    pos_sale,
)

User = get_user_model()
UT = OrgUnit.UnitType

_SS_ALPHABET = set("23456789ABCDEFGHJKMNPQRSTUVWXYZ")


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


def _seed_item(req, company, branch, actor, *, price="100.00", tax="0.15", qty="10", **extra):
    wh = create_warehouse(request=req, company=company, branch=branch, actor_user=actor, name="Bodega", code="W1")
    item = InventoryItem.objects.create(
        company=company, sku=f"SKU{uuid.uuid4().hex[:6]}", name="Aceite 1L", uom=UoM.UNIT,
        barcode=f"75{uuid.uuid4().hex[:10]}",
        sale_price=Decimal(price) if price is not None else None,
        default_tax_rate=Decimal(tax),
        **extra,
    )
    post_receive(
        request=req, actor=actor, warehouse_id=wh.id, item_id=item.id,
        qty=Decimal(qty), unit_cost=Decimal("60"), idempotency_key=f"rcv-{uuid.uuid4().hex}",
    )
    return wh, item


# ---------------------------------------------------------------------------
# Creación desde el kiosko
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_create_ticket_estimates_with_public_catalog_price():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    _wh, item = _seed_item(req, company, branch, actor, price="100.00", tax="0.15")

    res = create_self_service_ticket(
        request=req, actor=actor, lines=[{"inventory_item_id": item.id, "quantity": "2"}]
    )

    assert len(res["code"]) == 6
    assert set(res["code"]) <= _SS_ALPHABET
    assert res["status"] == SelfServiceStatus.OPEN
    # 2 × 100 = 200 + IVA 30 = 230 (estimado informativo).
    assert res["estimated_subtotal"] == "200.00"
    assert res["estimated_tax"] == "30.00"
    assert res["estimated_total"] == "230.00"
    assert res["lines"][0]["unit_price"] == "100.00"
    assert res["lines"][0]["unavailable"] is False

    ticket = SelfServiceTicket.objects.get(company=company, code=res["code"])
    # El pre-ticket NO guarda precios: solo artículo y cantidad.
    assert [ln["inventory_item_id"] for ln in ticket.lines] == [item.id]
    assert Decimal(ticket.lines[0]["quantity"]) == Decimal("2")
    assert "unit_price" not in ticket.lines[0]
    assert ticket.expires_at > timezone.now() + timedelta(hours=7)


@pytest.mark.django_db
def test_create_ticket_applies_wholesale_price_in_estimate():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    _wh, item = _seed_item(
        req, company, branch, actor, price="50.00", tax="0",
        wholesale_price=Decimal("40.00"), wholesale_min_qty=Decimal("6"),
    )

    res = create_self_service_ticket(
        request=req, actor=actor, lines=[{"inventory_item_id": item.id, "quantity": "6"}]
    )
    # 6 uds alcanzan el mínimo de mayoreo: 6 × 40 = 240.
    assert res["estimated_total"] == "240.00"
    assert res["lines"][0]["unit_price"] == "40.00"


@pytest.mark.django_db
def test_create_ticket_rejects_item_without_price():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    _wh, item = _seed_item(req, company, branch, actor, price=None)

    with pytest.raises(SalesError, match="SALES_ITEM_WITHOUT_PRICE"):
        create_self_service_ticket(
            request=req, actor=actor, lines=[{"inventory_item_id": item.id, "quantity": "1"}]
        )
    assert not SelfServiceTicket.objects.filter(company=company).exists()


# ---------------------------------------------------------------------------
# Lectura en caja
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_get_ticket_reresolves_current_price():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    _wh, item = _seed_item(req, company, branch, actor, price="100.00", tax="0")

    res = create_self_service_ticket(
        request=req, actor=actor, lines=[{"inventory_item_id": item.id, "quantity": "1"}]
    )
    assert res["estimated_total"] == "100.00"

    # El precio cambió entre la tableta y la caja: manda el catálogo de HOY.
    item.sale_price = Decimal("120.00")
    item.save(update_fields=["sale_price"])

    loaded = get_self_service_ticket(company=company, code=res["code"])
    assert loaded["estimated_total"] == "120.00"
    assert loaded["lines"][0]["unit_price"] == "120.00"


@pytest.mark.django_db
def test_get_ticket_marks_expired_lazily():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    _wh, item = _seed_item(req, company, branch, actor)

    res = create_self_service_ticket(
        request=req, actor=actor, lines=[{"inventory_item_id": item.id, "quantity": "1"}]
    )
    SelfServiceTicket.objects.filter(company=company, code=res["code"]).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )

    with pytest.raises(SalesError, match="SALES_SELF_SERVICE_EXPIRED"):
        get_self_service_ticket(company=company, code=res["code"])
    ticket = SelfServiceTicket.objects.get(company=company, code=res["code"])
    assert ticket.status == SelfServiceStatus.EXPIRED


@pytest.mark.django_db
def test_get_ticket_is_scoped_by_company():
    _h, company, branch = _scope()
    _h2, company2, _branch2 = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    _wh, item = _seed_item(req, company, branch, actor)

    res = create_self_service_ticket(
        request=req, actor=actor, lines=[{"inventory_item_id": item.id, "quantity": "1"}]
    )
    # Desde OTRA empresa el código no existe.
    with pytest.raises(SalesError, match="SALES_SELF_SERVICE_NOT_FOUND"):
        get_self_service_ticket(company=company2, code=res["code"])


@pytest.mark.django_db
def test_get_unknown_code_not_found():
    _h, company, _branch = _scope()
    with pytest.raises(SalesError, match="SALES_SELF_SERVICE_NOT_FOUND"):
        get_self_service_ticket(company=company, code="ZZZZZZ")


# ---------------------------------------------------------------------------
# Cancelación
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_cancel_is_idempotent_and_blocks_charged():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    _wh, item = _seed_item(req, company, branch, actor)

    res = create_self_service_ticket(
        request=req, actor=actor, lines=[{"inventory_item_id": item.id, "quantity": "1"}]
    )
    out1 = cancel_self_service_ticket(request=req, actor=actor, code=res["code"])
    out2 = cancel_self_service_ticket(request=req, actor=actor, code=res["code"])
    assert out1["already_cancelled"] is False
    assert out2["already_cancelled"] is True

    # Un ticket cancelado ya no se puede cobrar ni leer.
    with pytest.raises(SalesError, match="SALES_SELF_SERVICE_NOT_OPEN"):
        get_self_service_ticket(company=company, code=res["code"])


# ---------------------------------------------------------------------------
# Cobro en caja (pos_sale con self_service_code)
# ---------------------------------------------------------------------------

def _ticket_and_sale_kwargs(req, actor, wh, item, *, code, key="POS-SS-1"):
    return dict(
        request=req, actor=actor, warehouse_id=wh.id,
        lines=[{"inventory_item_id": item.id, "quantity": "2"}],
        payments=[{"method": "CASH", "amount": "230.00"}],
        idempotency_key=key, self_service_code=code,
    )


@pytest.mark.django_db
def test_cash_sale_with_code_marks_ticket_charged():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed_item(req, company, branch, actor, price="100.00", tax="0.15")
    open_cash_session_for_scope(company=company, branch=branch, actor=actor)

    t = create_self_service_ticket(
        request=req, actor=actor, lines=[{"inventory_item_id": item.id, "quantity": "2"}]
    )
    res = pos_sale(**_ticket_and_sale_kwargs(req, actor, wh, item, code=t["code"]))

    ticket = SelfServiceTicket.objects.get(company=company, code=t["code"])
    assert ticket.status == SelfServiceStatus.CHARGED
    assert ticket.charged_doc_id == res["doc_id"]
    assert ticket.charged_at is not None

    # Releerlo en caja ya no procede.
    with pytest.raises(SalesError, match="SALES_SELF_SERVICE_NOT_OPEN"):
        get_self_service_ticket(company=company, code=t["code"])


@pytest.mark.django_db
def test_pos_sale_with_code_is_idempotent():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed_item(req, company, branch, actor, price="100.00", tax="0.15")
    open_cash_session_for_scope(company=company, branch=branch, actor=actor)

    t = create_self_service_ticket(
        request=req, actor=actor, lines=[{"inventory_item_id": item.id, "quantity": "2"}]
    )
    kwargs = _ticket_and_sale_kwargs(req, actor, wh, item, code=t["code"], key="POS-SS-IDEM")
    r1 = pos_sale(**kwargs)
    r2 = pos_sale(**kwargs)  # reintento de red: no truena aunque el ticket ya esté CHARGED

    assert r2["duplicate"] is True
    assert r2["doc_id"] == r1["doc_id"]
    ticket = SelfServiceTicket.objects.get(company=company, code=t["code"])
    assert ticket.status == SelfServiceStatus.CHARGED
    assert ticket.charged_doc_id == r1["doc_id"]


@pytest.mark.django_db
def test_pos_sale_with_already_charged_code_fails_for_new_sale():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed_item(req, company, branch, actor, price="100.00", tax="0.15", qty="20")
    open_cash_session_for_scope(company=company, branch=branch, actor=actor)

    t = create_self_service_ticket(
        request=req, actor=actor, lines=[{"inventory_item_id": item.id, "quantity": "2"}]
    )
    pos_sale(**_ticket_and_sale_kwargs(req, actor, wh, item, code=t["code"], key="POS-SS-A"))

    # OTRA venta (key distinta) con el mismo código → 422 y rollback de la nueva factura.
    with pytest.raises(SalesError, match="SALES_SELF_SERVICE_NOT_OPEN"):
        pos_sale(**_ticket_and_sale_kwargs(req, actor, wh, item, code=t["code"], key="POS-SS-B"))


@pytest.mark.django_db
def test_credit_sale_with_code_marks_ticket_charged():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed_item(req, company, branch, actor, price="100.00", tax="0.15")
    party = Party.objects.create(
        company=company, party_type=Party.PartyType.NATURAL, display_name="Cliente AF"
    )
    get_or_create_account(
        request=req, actor=actor, company=company, party=party,
        segment=CustomerSegment.PUBLIC, credit_limit=Decimal("1000"), credit_days=15,
    )
    t = create_self_service_ticket(
        request=req, actor=actor, lines=[{"inventory_item_id": item.id, "quantity": "2"}]
    )

    res = pos_sale(
        request=req, actor=actor, warehouse_id=wh.id,
        lines=[{"inventory_item_id": item.id, "quantity": "2"}],
        payments=[{"method": "CREDIT"}],
        idempotency_key="POS-SS-CRED", customer_party_id=party.id,
        self_service_code=t["code"],
    )
    assert res["sale_type"] == "CREDIT"
    ticket = SelfServiceTicket.objects.get(company=company, code=t["code"])
    assert ticket.status == SelfServiceStatus.CHARGED
    assert ticket.charged_doc_id == res["doc_id"]


# ---------------------------------------------------------------------------
# HTTP / RBAC
# ---------------------------------------------------------------------------

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


@pytest.mark.django_db
def test_http_kiosk_creates_but_cannot_read_and_cashier_reads():
    _h, company, branch = _scope()
    seeder = _user()
    req = _req(company, branch, seeder)
    _wh, item = _seed_item(req, company, branch, seeder, price="100.00", tax="0")

    payload = {"lines": [{"inventory_item_id": item.id, "quantity": "1"}]}

    # Sin el permiso del kiosko → 403.
    c_noperm, _ = _client(company, branch, perms=["sales.pos.sell"])
    r = c_noperm.post("/api/sales/self-service/", payload, format="json")
    assert r.status_code == 403

    # El kiosko crea (201) pero NO puede leer tickets (eso es de caja).
    c_kiosk, _ = _client(company, branch, perms=["sales.pos.self_service"])
    r = c_kiosk.post("/api/sales/self-service/", payload, format="json")
    assert r.status_code == 201, r.data
    code = r.data["code"]
    r = c_kiosk.get(f"/api/sales/self-service/{code}/")
    assert r.status_code == 403

    # La caja (sell) lo lee con precios re-resueltos.
    r = c_noperm.get(f"/api/sales/self-service/{code}/")
    assert r.status_code == 200
    assert r.data["estimated_total"] == "100.00"

    # Código inexistente → 404 con el código de negocio en el envelope.
    r = c_noperm.get("/api/sales/self-service/AAAAAA/")
    assert r.status_code == 404
    assert r.data["error"]["message"] == "SALES_SELF_SERVICE_NOT_FOUND"
