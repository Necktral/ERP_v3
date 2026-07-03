"""
Golden tests de fidelidad de líneas (oleada 1).

Fijan byte-a-byte los valores computados de las líneas y los totales del
documento ANTES del refactor a bulk_create (services.py: create_draft y
create_order). Si el refactor cambia un solo centavo, un orden o un campo,
esto truena. NO ablandar: son el contrato del cálculo de venta.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.facturacion.models import BillingLine, SalesOrderLine
from apps.kernels.facturacion.services import create_draft, create_order
from apps.modulos.iam.models import OrgUnit


def _build_scope():
    token = uuid.uuid4().hex[:8]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H {token}", code=f"H-{token}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, parent=holding, name=f"C {token}", code=f"C-{token}")
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, parent=company, name=f"B {token}", code=f"B-{token}")
    User = get_user_model()
    user = User.objects.create_user(username=f"golden_{token}", email=f"g_{token}@example.com", password="Secret123!")
    request = SimpleNamespace(
        company=company,
        branch=branch,
        user=user,
        META={},
        headers={},
        path="/test/billing/",
        method="POST",
        request_id=f"req-{token}",
    )
    return company, branch, user, request


# Tres líneas con variedad: descuento, tasa 15%, exenta, y cantidades con decimales.
LINEAS = [
    {"description": "Linea A", "quantity": "2", "unit_price": "100.00", "tax_rate": "0.15"},
    {"description": "Linea B", "quantity": "3.5", "unit_price": "7.33", "tax_rate": "0.15", "discount_pct": "0.10"},
    {"description": "Linea C", "quantity": "1", "unit_price": "0.99"},
]

# Valores esperados por línea: (gross, discount, subtotal, tax, total).
GOLDEN_LINEAS = [
    ("200.00", "0.00", "200.00", "30.00", "230.00"),
    ("25.66", "2.57", "23.09", "3.46", "26.55"),
    ("0.99", "0.00", "0.99", "0.00", "0.99"),
]
GOLDEN_DOC = {
    "subtotal": "224.08",  # bruto 226.65 - descuento 2.57
    "discount_total": "2.57",
    "tax_total": "33.46",
    "total": "257.54",
}


@pytest.mark.django_db
def test_golden_create_draft_lineas_y_totales_exactos():
    _, _, user, request = _build_scope()

    out = create_draft(
        request=request,
        actor=user,
        doc_type="INVOICE",
        series="A",
        currency="NIO",
        customer_name="Cliente Golden",
        customer_ref="G-001",
        is_fiscal=False,
        lines=LINEAS,
        idempotency_key=f"golden-{uuid.uuid4().hex}",
    )

    lines = list(BillingLine.objects.filter(doc_id=out.doc_id).order_by("id"))
    assert [ln.description for ln in lines] == ["Linea A", "Linea B", "Linea C"]

    for ln, (gross, disc, sub, tax, total) in zip(lines, GOLDEN_LINEAS):
        assert ln.line_gross == Decimal(gross), ln.description
        assert ln.discount_amount == Decimal(disc), ln.description
        assert ln.line_subtotal == Decimal(sub), ln.description
        assert ln.line_tax == Decimal(tax), ln.description
        assert ln.line_total == Decimal(total), ln.description

    doc = lines[0].doc
    assert doc.subtotal == Decimal(GOLDEN_DOC["subtotal"])
    assert doc.discount_total == Decimal(GOLDEN_DOC["discount_total"])
    assert doc.tax_total == Decimal(GOLDEN_DOC["tax_total"])
    assert doc.total == Decimal(GOLDEN_DOC["total"])

    # Identidad de sync: cada línea nace con su propio ULID (bulk_create debe
    # seguir aplicando los defaults de Syncable).
    uids = {ln.sync_uid for ln in lines}
    assert len(uids) == 3 and all(uids)


@pytest.mark.django_db
def test_golden_create_order_lineas_y_totales_exactos():
    _, _, user, request = _build_scope()

    out = create_order(
        request=request,
        actor=user,
        customer_name="Cliente Golden",
        customer_ref="G-002",
        currency="NIO",
        lines=LINEAS,
    )

    order_id = out["order_id"] if isinstance(out, dict) else out.order_id
    lines = list(SalesOrderLine.objects.filter(order_id=order_id).order_by("id"))
    assert [ln.description for ln in lines] == ["Linea A", "Linea B", "Linea C"]

    for ln, (_gross, _disc, sub, tax, total) in zip(lines, GOLDEN_LINEAS):
        assert ln.line_subtotal == Decimal(sub), ln.description
        assert ln.line_tax == Decimal(tax), ln.description
        assert ln.line_total == Decimal(total), ln.description

    order = lines[0].order
    assert order.subtotal == Decimal(GOLDEN_DOC["subtotal"])
    assert order.tax_total == Decimal(GOLDEN_DOC["tax_total"])
    assert order.total == Decimal(GOLDEN_DOC["total"])

    uids = {ln.sync_uid for ln in lines}
    assert len(uids) == 3 and all(uids)
