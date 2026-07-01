"""Tests del orquestador de venta POS (A3 del programa de completitud).

Cubre: contado con efectivo (factura emitida + stock abajo + movimiento en sesión de
caja), validación de pagos vs total con rollback, precio de catálogo obligatorio y
override con permiso, crédito delegado al motor C-01 (CxC con vencimiento), e
idempotencia de la venta completa.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.kernels.facturacion.models import BillingDocument, DocStatus, PaymentStatus
from apps.kernels.inventarios.models import InventoryItem, StockBalance, UoM
from apps.kernels.inventarios.services import create_warehouse, post_receive
from apps.kernels.payments.models import CashMovement
from apps.kernels.payments.services import open_cash_session_for_scope
from apps.kernels.portfolio.models import Receivable
from apps.modulos.comisariato.models import CustomerSegment
from apps.modulos.comisariato.services import get_or_create_account
from apps.modulos.ventas.services import SalesError, pos_sale
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.parties.models import Party
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

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


# ---------------------------------------------------------------------------
# Contado
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_cash_sale_issues_invoice_decrements_stock_and_hits_cash_session():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed_item(req, company, branch, actor, price="100.00", tax="0.15", qty="10")
    session = _open_session(company, branch, actor)

    # 2 × 100 × 1.15 = 230.00 — el precio sale del catálogo, la caja no lo manda.
    res = pos_sale(
        request=req, actor=actor, warehouse_id=wh.id,
        lines=[{"inventory_item_id": item.id, "quantity": "2"}],
        payments=[{"method": "CASH", "amount": "230.00"}],
        idempotency_key="POS-001",
    )

    assert res["sale_type"] == "CASH"
    assert res["duplicate"] is False
    assert res["total"] == "230.00"
    assert res["payment_status"] == PaymentStatus.PAID
    assert res["cash_session_id"] == session.id

    doc = BillingDocument.objects.get(id=res["doc_id"])
    assert doc.status == DocStatus.ISSUED
    assert doc.number  # numeración fiscal asignada
    assert _stock(company, branch, wh, item) == Decimal("8.0000")

    mov = CashMovement.objects.get(id=res["cash_movement_id"])
    assert mov.session_id == session.id
    assert mov.movement_type == CashMovement.MovementType.INCOME
    assert mov.amount == Decimal("230.00")


@pytest.mark.django_db
def test_cash_sale_without_open_session_rolls_back():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed_item(req, company, branch, actor)

    with pytest.raises(SalesError, match="SALES_NO_OPEN_CASH_SESSION"):
        pos_sale(
            request=req, actor=actor, warehouse_id=wh.id,
            lines=[{"inventory_item_id": item.id, "quantity": "1"}],
            payments=[{"method": "CASH", "amount": "115.00"}],
            idempotency_key="POS-NOSESSION",
        )

    # Rollback total: ni documento ni inventario tocado.
    assert not BillingDocument.objects.filter(company=company, status=DocStatus.ISSUED).exists()
    assert _stock(company, branch, wh, item) == Decimal("10.0000")


@pytest.mark.django_db
def test_payments_must_match_total():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed_item(req, company, branch, actor)
    _open_session(company, branch, actor)

    with pytest.raises(SalesError, match="SALES_PAYMENTS_MISMATCH"):
        pos_sale(
            request=req, actor=actor, warehouse_id=wh.id,
            lines=[{"inventory_item_id": item.id, "quantity": "1"}],
            payments=[{"method": "CASH", "amount": "100.00"}],  # total real: 115.00
            idempotency_key="POS-MISMATCH",
        )
    assert _stock(company, branch, wh, item) == Decimal("10.0000")


@pytest.mark.django_db
def test_split_payment_cash_plus_transfer():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed_item(req, company, branch, actor)
    session = _open_session(company, branch, actor)

    res = pos_sale(
        request=req, actor=actor, warehouse_id=wh.id,
        lines=[{"inventory_item_id": item.id, "quantity": "2"}],
        payments=[{"method": "CASH", "amount": "100.00"}, {"method": "TRANSFER", "amount": "130.00"}],
        idempotency_key="POS-SPLIT",
    )
    assert res["payment_status"] == PaymentStatus.PAID
    # Solo la porción en efectivo entra a la sesión de caja.
    mov = CashMovement.objects.get(id=res["cash_movement_id"])
    assert mov.amount == Decimal("100.00")
    assert mov.session_id == session.id


# ---------------------------------------------------------------------------
# Precio de catálogo / override
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_item_without_price_is_rejected():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed_item(req, company, branch, actor, price=None)
    _open_session(company, branch, actor)

    with pytest.raises(SalesError, match="SALES_ITEM_WITHOUT_PRICE"):
        pos_sale(
            request=req, actor=actor, warehouse_id=wh.id,
            lines=[{"inventory_item_id": item.id, "quantity": "1"}],
            payments=[{"method": "CASH", "amount": "10.00"}],
            idempotency_key="POS-NOPRICE",
        )


@pytest.mark.django_db
def test_price_override_requires_permission_flag():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed_item(req, company, branch, actor, price="100.00")
    _open_session(company, branch, actor)

    with pytest.raises(SalesError, match="SALES_PRICE_OVERRIDE_FORBIDDEN"):
        pos_sale(
            request=req, actor=actor, warehouse_id=wh.id,
            lines=[{"inventory_item_id": item.id, "quantity": "1", "unit_price": "80.00"}],
            payments=[{"method": "CASH", "amount": "92.00"}],
            idempotency_key="POS-OVR-NO",
        )

    res = pos_sale(
        request=req, actor=actor, warehouse_id=wh.id,
        lines=[{"inventory_item_id": item.id, "quantity": "1", "unit_price": "80.00"}],
        payments=[{"method": "CASH", "amount": "92.00"}],
        idempotency_key="POS-OVR-SI",
        allow_price_override=True,
    )
    assert res["total"] == "92.00"


# ---------------------------------------------------------------------------
# Crédito (delegado al motor C-01)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_credit_sale_creates_receivable_with_due_date():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed_item(req, company, branch, actor)
    party = Party.objects.create(
        company=company, party_type=Party.PartyType.NATURAL, display_name="Rosa POS"
    )
    get_or_create_account(
        request=req, actor=actor, company=company, party=party,
        segment=CustomerSegment.PUBLIC, credit_limit=Decimal("1000"), credit_days=15,
    )

    res = pos_sale(
        request=req, actor=actor, warehouse_id=wh.id,
        lines=[{"inventory_item_id": item.id, "quantity": "2"}],
        payments=[{"method": "CREDIT"}],
        idempotency_key="POS-CRED-1",
        customer_party_id=party.id,
    )
    assert res["sale_type"] == "CREDIT"
    assert res["receivable_id"] is not None
    assert res["available_after"] == "770.00"  # 1000 − 230

    rec = Receivable.objects.get(company=company, reference_type="BILLING_DOC", reference_id=res["doc_id"])
    assert rec.due_date == rec.issue_date + timedelta(days=15)
    assert _stock(company, branch, wh, item) == Decimal("8.0000")


@pytest.mark.django_db
def test_credit_sale_without_account_is_rejected():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed_item(req, company, branch, actor)
    party = Party.objects.create(
        company=company, party_type=Party.PartyType.NATURAL, display_name="Sin Cuenta"
    )

    with pytest.raises(SalesError, match="SALES_NO_CREDIT_ACCOUNT"):
        pos_sale(
            request=req, actor=actor, warehouse_id=wh.id,
            lines=[{"inventory_item_id": item.id, "quantity": "1"}],
            payments=[{"method": "CREDIT"}],
            idempotency_key="POS-CRED-NOACC",
            customer_party_id=party.id,
        )


# ---------------------------------------------------------------------------
# Idempotencia
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_pos_sale_is_idempotent_by_key():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed_item(req, company, branch, actor)
    _open_session(company, branch, actor)

    kwargs = dict(
        request=req, actor=actor, warehouse_id=wh.id,
        lines=[{"inventory_item_id": item.id, "quantity": "2"}],
        payments=[{"method": "CASH", "amount": "230.00"}],
        idempotency_key="POS-IDEM",
    )
    r1 = pos_sale(**kwargs)
    r2 = pos_sale(**kwargs)

    assert r1["duplicate"] is False
    assert r2["duplicate"] is True
    assert r2["doc_id"] == r1["doc_id"]
    # No re-despacha ni re-cobra.
    assert _stock(company, branch, wh, item) == Decimal("8.0000")
    assert CashMovement.objects.filter(reference=f"pos-sale:{r1['doc_id']}").count() == 1


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
def test_http_requires_sell_permission_and_detects_override_permission():
    _h, company, branch = _scope()
    seeder = _user()
    req = _req(company, branch, seeder)
    wh, item = _seed_item(req, company, branch, seeder, price="100.00", tax="0")

    # Sin permiso de venta → 403.
    c_noperm, _ = _client(company, branch, perms=["billing.doc.read"])
    r = c_noperm.post("/api/sales/pos-sale/", {
        "warehouse_id": wh.id, "idempotency_key": "H-1",
        "lines": [{"inventory_item_id": item.id, "quantity": "1"}],
        "payments": [{"method": "CASH", "amount": "100.00"}],
    }, format="json")
    assert r.status_code == 403

    # Con venta pero SIN override → 422 al cambiar el precio.
    c_seller, seller = _client(company, branch, perms=["sales.pos.sell"])
    open_cash_session_for_scope(company=company, branch=branch, actor=seller)
    r = c_seller.post("/api/sales/pos-sale/", {
        "warehouse_id": wh.id, "idempotency_key": "H-2",
        "lines": [{"inventory_item_id": item.id, "quantity": "1", "unit_price": "55.00"}],
        "payments": [{"method": "CASH", "amount": "55.00"}],
    }, format="json")
    assert r.status_code == 422
    assert r.data["error"]["message"] == "SALES_PRICE_OVERRIDE_FORBIDDEN"

    # Venta normal a precio de catálogo → 201.
    r = c_seller.post("/api/sales/pos-sale/", {
        "warehouse_id": wh.id, "idempotency_key": "H-3",
        "lines": [{"inventory_item_id": item.id, "quantity": "1"}],
        "payments": [{"method": "CASH", "amount": "100.00"}],
    }, format="json")
    assert r.status_code == 201, r.data
    assert r.data["payment_status"] == PaymentStatus.PAID


# ---------------------------------------------------------------------------
# Cobro de CxC en caja (F5)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_collect_receivable_in_cash_applies_and_hits_session():
    from apps.modulos.ventas.services import collect_receivable

    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed_item(req, company, branch, actor)
    party = Party.objects.create(
        company=company, party_type=Party.PartyType.NATURAL, display_name="Abonador"
    )
    get_or_create_account(
        request=req, actor=actor, company=company, party=party,
        segment=CustomerSegment.PUBLIC, credit_limit=Decimal("1000"), credit_days=30,
    )
    res = pos_sale(
        request=req, actor=actor, warehouse_id=wh.id,
        lines=[{"inventory_item_id": item.id, "quantity": "2"}],  # total 230.00
        payments=[{"method": "CREDIT"}],
        idempotency_key="POS-COBRO-1",
        customer_party_id=party.id,
    )
    rec = Receivable.objects.get(company=company, reference_type="BILLING_DOC", reference_id=res["doc_id"])
    session = _open_session(company, branch, actor)

    out = collect_receivable(
        request=req, actor=actor, receivable_id=rec.id,
        amount=Decimal("100.00"), method="CASH", idempotency_key="COBRO-1",
    )
    assert out["outstanding_after"] == "130.00"
    assert out["cash_movement_id"] is not None

    mov = CashMovement.objects.get(id=out["cash_movement_id"])
    assert mov.session_id == session.id
    assert mov.amount == Decimal("100.00")

    # El abono también se refleja en la factura de origen.
    doc = BillingDocument.objects.get(id=res["doc_id"])
    assert doc.payment_status == PaymentStatus.PARTIAL
    assert doc.amount_paid == Decimal("100.00")

    # Cobrar el resto deja la CxC saldada y la factura PAID.
    out2 = collect_receivable(
        request=req, actor=actor, receivable_id=rec.id,
        amount=Decimal("130.00"), method="CASH", idempotency_key="COBRO-2",
    )
    assert out2["outstanding_after"] == "0.00"
    doc.refresh_from_db()
    assert doc.payment_status == PaymentStatus.PAID


@pytest.mark.django_db
def test_collect_receivable_validates_amount_and_state():
    from apps.modulos.ventas.services import collect_receivable

    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed_item(req, company, branch, actor)
    party = Party.objects.create(
        company=company, party_type=Party.PartyType.NATURAL, display_name="Validado"
    )
    get_or_create_account(
        request=req, actor=actor, company=company, party=party,
        segment=CustomerSegment.PUBLIC, credit_limit=Decimal("1000"),
    )
    res = pos_sale(
        request=req, actor=actor, warehouse_id=wh.id,
        lines=[{"inventory_item_id": item.id, "quantity": "1"}],  # total 115.00
        payments=[{"method": "CREDIT"}],
        idempotency_key="POS-COBRO-VAL",
        customer_party_id=party.id,
    )
    rec = Receivable.objects.get(company=company, reference_type="BILLING_DOC", reference_id=res["doc_id"])
    _open_session(company, branch, actor)

    with pytest.raises(SalesError, match="SALES_AMOUNT_EXCEEDS_OUTSTANDING"):
        collect_receivable(
            request=req, actor=actor, receivable_id=rec.id,
            amount=Decimal("999.00"), method="CASH", idempotency_key="COBRO-EX",
        )

    with pytest.raises(SalesError, match="SALES_RECEIVABLE_NOT_FOUND"):
        collect_receivable(
            request=req, actor=actor, receivable_id=999999,
            amount=Decimal("10.00"), method="CASH", idempotency_key="COBRO-NF",
        )


# ---------------------------------------------------------------------------
# Mayoreo (P1) y corte de ventas (P2)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_wholesale_price_applies_automatically_at_min_qty():
    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed_item(req, company, branch, actor, price="100.00", tax="0", qty="50")
    item.wholesale_price = Decimal("80.00")
    item.wholesale_min_qty = Decimal("10")
    item.save(update_fields=["wholesale_price", "wholesale_min_qty"])
    _open_session(company, branch, actor)

    # 5 unidades < mínimo → precio normal (500).
    res = pos_sale(
        request=req, actor=actor, warehouse_id=wh.id,
        lines=[{"inventory_item_id": item.id, "quantity": "5"}],
        payments=[{"method": "CASH", "amount": "500.00"}],
        idempotency_key="POS-MAY-5",
    )
    assert res["total"] == "500.00"

    # 10 unidades ≥ mínimo → mayoreo automático (800), SIN permiso especial.
    res = pos_sale(
        request=req, actor=actor, warehouse_id=wh.id,
        lines=[{"inventory_item_id": item.id, "quantity": "10"}],
        payments=[{"method": "CASH", "amount": "800.00"}],
        idempotency_key="POS-MAY-10",
    )
    assert res["total"] == "800.00"

    # Mandar el precio de mayoreo explícito cuando aplica NO exige override.
    res = pos_sale(
        request=req, actor=actor, warehouse_id=wh.id,
        lines=[{"inventory_item_id": item.id, "quantity": "12", "unit_price": "80.00"}],
        payments=[{"method": "CASH", "amount": "960.00"}],
        idempotency_key="POS-MAY-12",
    )
    assert res["total"] == "960.00"


@pytest.mark.django_db
def test_pos_daily_report_totals_methods_and_profit():
    from apps.modulos.ventas.services import pos_daily_report
    from django.utils import timezone as djtz

    _h, company, branch = _scope()
    actor = _user()
    req = _req(company, branch, actor)
    wh, item = _seed_item(req, company, branch, actor, price="100.00", tax="0", qty="20")  # costo 60
    _open_session(company, branch, actor)

    pos_sale(
        request=req, actor=actor, warehouse_id=wh.id,
        lines=[{"inventory_item_id": item.id, "quantity": "2"}],
        payments=[{"method": "CASH", "amount": "200.00"}],
        idempotency_key="POS-REP-1",
    )
    pos_sale(
        request=req, actor=actor, warehouse_id=wh.id,
        lines=[{"inventory_item_id": item.id, "quantity": "1"}],
        payments=[{"method": "TRANSFER", "amount": "100.00"}],
        idempotency_key="POS-REP-2",
    )

    rep = pos_daily_report(company=company, branch=branch, day=djtz.localdate())
    assert rep["sales"]["count"] == 2
    assert rep["sales"]["total"] == "300.00"
    methods = {m["method"]: m["amount"] for m in rep["payments_by_method"]}
    assert methods["CASH"] == "200.00"
    assert methods["TRANSFER"] == "100.00"
    # Utilidad bruta: ingreso 300 − costo (3 × 60) = 120.
    assert rep["cost_of_goods"] == "180.00"
    assert rep["gross_profit"] == "120.00"
    assert rep["top_products"][0]["qty"] in ("3.0000", "3")
    assert rep["by_cashier"][0]["count"] == 2
