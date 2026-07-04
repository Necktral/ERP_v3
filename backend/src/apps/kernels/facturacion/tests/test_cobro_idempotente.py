"""
BILL-1 (bug-hunt de integridad): `create_payment` con `idempotency_key` es
idempotente — un doble-submit (doble clic) con la misma clave NO duplica el
abono. Antes no aceptaba clave y no tenía backstop de BD, así que el segundo
POST creaba otro BillingPayment e inflaba `amount_paid`.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.facturacion.models import BillingDocument, BillingPayment, DocType
from apps.kernels.facturacion.services import create_draft, create_payment, issue_doc
from apps.modulos.iam.models import OrgUnit

User = get_user_model()


def _scope():
    t = uuid.uuid4().hex[:8]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H{t}", code=f"H-{t}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, parent=holding, name=f"C{t}", code=f"C-{t}")
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, parent=company, name=f"B{t}", code=f"B-{t}")
    user = User.objects.create_user(username=f"ci_{t}", email=f"ci_{t}@test.local", password="Secret123!")
    request = SimpleNamespace(
        company=company, branch=branch, user=user, META={}, headers={},
        path="/t/billing/", method="POST", request_id=f"req-{t}", data={},
    )
    return company, branch, user, request


@pytest.mark.django_db
def test_cobro_con_misma_clave_no_duplica():
    company, branch, user, request = _scope()
    draft = create_draft(
        request=request, actor=user, doc_type=DocType.INVOICE, series="A", currency="NIO",
        customer_name="Cliente", customer_ref="C-1", is_fiscal=False,
        lines=[{"description": "P", "quantity": "1", "unit_price": "1000", "tax_rate": "0.15"}],
        idempotency_key=f"d-{uuid.uuid4().hex}",
    )
    issue_doc(request=request, actor=user, doc_id=draft.doc_id, idempotency_key=f"i-{uuid.uuid4().hex}")

    key = f"pay-{uuid.uuid4().hex}"
    r1 = create_payment(request=request, actor=user, doc_id=draft.doc_id,
                        payment_method="CASH", amount=Decimal("500.00"), idempotency_key=key)
    r2 = create_payment(request=request, actor=user, doc_id=draft.doc_id,
                        payment_method="CASH", amount=Decimal("500.00"), idempotency_key=key)

    assert r1.payment_id == r2.payment_id, "el replay creó un pago nuevo"
    assert BillingPayment.objects.filter(doc_id=draft.doc_id).count() == 1
    doc = BillingDocument.objects.get(id=draft.doc_id)
    assert doc.amount_paid == Decimal("500.00"), f"amount_paid duplicado: {doc.amount_paid}"
