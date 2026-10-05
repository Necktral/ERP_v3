"""
BUG-T2 (bug-hunt de integridad): anular (`void_doc`) una factura que YA produjo
efectos (despachó inventario, generó CxC o recibió abonos) debe RECHAZARSE y
forzar el uso de Nota de Crédito (que sí reingresa stock y ajusta cartera). Antes
solo revertía el asiento GL, dejando el kardex y la cartera divergentes de la
contabilidad.

Decisión de negocio (usuario): void solo para documentos SIN efectos.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.facturacion.models import BillingDocument, CreditStatus, DocStatus, DocType
from apps.kernels.facturacion.services import BillingError, create_draft, issue_doc, void_doc
from apps.kernels.inventarios.models import InventoryItem, Warehouse
from apps.kernels.inventarios.services import post_receive
from apps.modulos.iam.models import OrgUnit

User = get_user_model()


def _scope():
    t = uuid.uuid4().hex[:8]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H{t}", code=f"H-{t}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, parent=holding, name=f"C{t}", code=f"C-{t}")
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, parent=company, name=f"B{t}", code=f"B-{t}")
    user = User.objects.create_user(username=f"vd_{t}", email=f"vd_{t}@test.local", password="Secret123!")
    request = SimpleNamespace(
        company=company, branch=branch, user=user, META={}, headers={},
        path="/t/billing/", method="POST", request_id=f"req-{t}", data={},
    )
    return company, branch, user, request


def _draft(request, actor, *, with_item=None, wh=None):
    linea = {"description": "Producto", "quantity": "5", "unit_price": "100", "tax_rate": "0.15"}
    if with_item is not None:
        linea["inventory_item_id"] = with_item.id
        linea["warehouse_id"] = wh.id
    return create_draft(
        request=request, actor=actor, doc_type=DocType.INVOICE, series="A", currency="NIO",
        customer_name="Cliente Demo", customer_ref="C-001", is_fiscal=False,
        lines=[linea], idempotency_key=f"d-{uuid.uuid4().hex}",
    )


@pytest.mark.django_db
def test_void_bloqueado_si_despacho_inventario():
    company, branch, user, request = _scope()
    wh = Warehouse.objects.create(company=company, branch=branch, name="Main", code=f"W{uuid.uuid4().hex[:5]}")
    item = InventoryItem.objects.create(company=company, sku=f"S-{uuid.uuid4().hex[:6]}", name="Item")
    post_receive(request=request, actor=user, warehouse_id=wh.id, item_id=item.id,
                 qty=Decimal("100"), unit_cost=Decimal("12.00"), idempotency_key=f"r-{uuid.uuid4().hex}")

    draft = _draft(request, user, with_item=item, wh=wh)
    issue_doc(request=request, actor=user, doc_id=draft.doc_id, apply_inventory=True,
              idempotency_key=f"i-{uuid.uuid4().hex}")

    with pytest.raises(BillingError):
        void_doc(request=request, actor=user, doc_id=draft.doc_id, reason="error de captura")

    # Sigue ISSUED (no se anuló): la vía correcta es la nota de crédito.
    assert BillingDocument.objects.get(id=draft.doc_id).status == DocStatus.ISSUED


@pytest.mark.django_db
def test_void_bloqueado_si_genero_cxc():
    from apps.modulos.parties.models import Party

    company, branch, user, request = _scope()
    party = Party.objects.create(
        company=company, party_type=Party.PartyType.JURIDICAL,
        display_name="Cliente Crédito", tax_id=f"RUC-{uuid.uuid4().hex[:8]}",
    )
    draft = create_draft(
        request=request, actor=user, doc_type=DocType.INVOICE, series="A", currency="NIO",
        customer_name="Cliente Crédito", customer_ref="C-CR", is_fiscal=False,
        customer_party_id=party.id,
        lines=[{"description": "Producto", "quantity": "5", "unit_price": "100", "tax_rate": "0.15"}],
        idempotency_key=f"d-{uuid.uuid4().hex}",
    )
    # Venta a crédito → issue crea la CxC en portfolio.
    doc = BillingDocument.objects.get(id=draft.doc_id)
    doc.credit_status = CreditStatus.APPROVED
    doc.save(update_fields=["credit_status"])
    issue_doc(request=request, actor=user, doc_id=draft.doc_id, idempotency_key=f"i-{uuid.uuid4().hex}")

    from apps.kernels.portfolio.models import Receivable
    assert Receivable.objects.filter(company=company, reference_type="BILLING_DOC", reference_id=draft.doc_id).exists()

    with pytest.raises(BillingError):
        void_doc(request=request, actor=user, doc_id=draft.doc_id, reason="error")
    assert BillingDocument.objects.get(id=draft.doc_id).status == DocStatus.ISSUED


@pytest.mark.django_db
def test_void_bloqueado_si_tiene_abonos():
    company, branch, user, request = _scope()
    draft = _draft(request, user)
    issue_doc(request=request, actor=user, doc_id=draft.doc_id, idempotency_key=f"i-{uuid.uuid4().hex}")
    doc = BillingDocument.objects.get(id=draft.doc_id)
    doc.amount_paid = Decimal("50.00")
    doc.save(update_fields=["amount_paid"])

    with pytest.raises(BillingError):
        void_doc(request=request, actor=user, doc_id=draft.doc_id, reason="error")


@pytest.mark.django_db
def test_void_permitido_sin_efectos():
    """Control: una factura de contado SIN inventario, SIN CxC y SIN abonos sí se anula."""
    company, branch, user, request = _scope()
    draft = _draft(request, user)  # contado (credit_status NONE), sin inventory_item
    issue_doc(request=request, actor=user, doc_id=draft.doc_id, idempotency_key=f"i-{uuid.uuid4().hex}")

    out = void_doc(request=request, actor=user, doc_id=draft.doc_id, reason="error de captura")
    assert out.get("ok") is True
    assert BillingDocument.objects.get(id=draft.doc_id).status == DocStatus.VOIDED
