"""PR-3: cableado Billing → portfolio CxC.

Una venta a crédito emitida crea una CxC (Receivable) en portfolio, auditada e idempotente.
El contado / consumidor final (credit_status NONE) NO crea cartera. Respeta ownership:
Billing emite el documento; portfolio posee el saldo.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.kernels.facturacion.models import BillingDocument, CreditStatus
from apps.kernels.facturacion.services import create_draft, issue_doc
from apps.kernels.facturacion.services import reconcile_issued_credit_documents_receivables
from apps.kernels.portfolio.models import Receivable
from apps.kernels.portfolio.services import (
    BILLING_RECEIVABLE_CONSUMER,
    link_billing_document_to_receivable,
)
from apps.modulos.audit.models import AuditEvent
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.integration.models import InboxEvent, OutboxEvent
from apps.modulos.parties.models import Party
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

User = get_user_model()


def _scope():
    t = uuid.uuid4().hex[:8]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H{t}", code=f"H-{t}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, parent=holding, name=f"C{t}", code=f"C-{t}")
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, parent=company, name=f"B{t}", code=f"B-{t}")
    return company, branch


def _user():
    t = uuid.uuid4().hex[:8]
    return User.objects.create_user(username=f"u_{t}", email=f"u_{t}@test.local", password="Secret123!")


def _request(company, branch, user):
    return SimpleNamespace(
        company=company, branch=branch, user=user, META={}, headers={},
        path="/test/billing/", method="POST", request_id=f"req-{uuid.uuid4().hex[:8]}",
    )


def _party(company):
    t = uuid.uuid4().hex[:8]
    return Party.objects.create(
        company=company, party_type=Party.PartyType.JURIDICAL, display_name=f"Cliente {t}", tax_id=f"RUC-{t}",
    )


def _draft(req, actor, *, customer_party_id=None):
    return create_draft(
        request=req, actor=actor, doc_type="INVOICE", series="A", currency="NIO",
        customer_name="Cliente Demo", customer_ref="C-001", is_fiscal=False,
        customer_party_id=customer_party_id,
        lines=[{"description": "Servicio", "quantity": "1", "unit_price": "100", "tax_rate": "0.15"}],
        idempotency_key=f"draft-{uuid.uuid4().hex}",
    )


def _make_credit(doc_id):
    doc = BillingDocument.objects.get(id=doc_id)
    doc.credit_status = CreditStatus.APPROVED
    doc.save(update_fields=["credit_status"])


def _issue(req, actor, doc_id):
    return issue_doc(request=req, actor=actor, doc_id=doc_id, idempotency_key=f"i-{uuid.uuid4().hex}")


def _receivables_for(company, doc_id):
    return Receivable.objects.filter(company=company, reference_type="BILLING_DOC", reference_id=doc_id)


def _api_client(company, branch, *, permission_codes):
    user = _user()
    UserMembership.objects.create(user=user, org_unit=company, is_active=True)
    UserMembership.objects.create(user=user, org_unit=branch, is_active=True)
    role = Role.objects.create(name=f"reconcile_{uuid.uuid4().hex[:8]}", is_active=True)
    for code in permission_codes:
        permission, _ = Permission.objects.get_or_create(
            code=code, defaults={"description": code, "is_active": True}
        )
        RolePermission.objects.create(role=role, permission=permission)
    RoleAssignment.objects.create(user=user, role=role, org_unit=company, is_active=True)
    RoleAssignment.objects.create(user=user, role=role, org_unit=branch, is_active=True)
    client = APIClient()
    login = client.post("/api/auth/login/", {"username": user.username, "password": "Secret123!"}, format="json")
    assert login.status_code == 200, login.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    client.defaults["HTTP_X_COMPANY_ID"] = str(company.id)
    client.defaults["HTTP_X_BRANCH_ID"] = str(branch.id)
    return client


@pytest.mark.django_db
def test_credit_issue_creates_receivable_and_audit():
    company, branch = _scope()
    actor = _user()
    req = _request(company, branch, actor)
    party = _party(company)
    draft = _draft(req, actor, customer_party_id=party.id)
    _make_credit(draft.doc_id)

    _issue(req, actor, draft.doc_id)

    rec = _receivables_for(company, draft.doc_id).first()
    assert rec is not None
    assert rec.party_id == party.id
    assert str(rec.principal_amount) == "115.00"
    assert AuditEvent.objects.filter(
        event_type="PORTFOLIO_RECEIVABLE_CREATED", subject_id=str(rec.obligation_id)
    ).exists()


@pytest.mark.django_db
def test_cash_issue_does_not_create_receivable():
    company, branch = _scope()
    actor = _user()
    req = _request(company, branch, actor)
    draft = _draft(req, actor)  # credit_status NONE (contado), sin party

    _issue(req, actor, draft.doc_id)

    assert not _receivables_for(company, draft.doc_id).exists()


@pytest.mark.django_db
def test_receivable_link_is_idempotent():
    company, branch = _scope()
    actor = _user()
    req = _request(company, branch, actor)
    party = _party(company)
    draft = _draft(req, actor, customer_party_id=party.id)
    _make_credit(draft.doc_id)
    _issue(req, actor, draft.doc_id)

    assert _receivables_for(company, draft.doc_id).count() == 1

    # Reprocesar el mismo evento no duplica la CxC.
    issued = (
        OutboxEvent.objects.filter(
            source_module="BILLING", event_type="DocumentIssued", payload__data__doc_id=draft.doc_id
        )
        .order_by("-id")
        .first()
    )
    result = link_billing_document_to_receivable(outbox_event=issued, actor_user=actor)
    assert result["status"] == "EXISTS"
    assert _receivables_for(company, draft.doc_id).count() == 1


# ---------------------------------------------------------------------------
# U12 (oleada 5) — doble-CxC bajo CONCURRENCIA
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_link_concurrente_del_mismo_evento_no_crea_doble_cxc():
    """U12: dos consumidores del MISMO evento de venta a crédito, a la vez,
    deben producir UNA sola CxC (el chequeo filter-first tiene ventana de
    carrera; el árbitro debe serializar)."""
    import threading

    from django.db import connection as db_conn

    company, branch = _scope()
    actor = _user()
    req = _request(company, branch, actor)
    party = _party(company)
    draft = _draft(req, actor, customer_party_id=party.id)
    _make_credit(draft.doc_id)
    _issue(req, actor, draft.doc_id)

    event = (
        OutboxEvent.objects.filter(source_module="BILLING", event_type="DocumentIssued", company=company)
        .order_by("-id").first()
    )
    assert event is not None

    barrier = threading.Barrier(2, timeout=10)
    errores: list[str] = []
    lock = threading.Lock()

    def consumir():
        try:
            barrier.wait()
            link_billing_document_to_receivable(outbox_event=event, actor_user=actor)
        except Exception as exc:  # noqa: BLE001 — un error de dominio limpio es aceptable; el doble-CxC no
            with lock:
                errores.append(repr(exc))
        finally:
            db_conn.close()

    threads = [threading.Thread(target=consumir) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    cxc = _receivables_for(company, draft.doc_id).count()
    assert cxc == 1, f"doble-CxC bajo concurrencia: {cxc} receivables para el mismo doc (errores: {errores})"


@pytest.mark.django_db
def test_fault_during_issue_is_durable_and_reconciles_after_accounting_sent(monkeypatch):
    from apps.kernels.accounting.services import dispatch_accounting_outbox_events
    from apps.kernels.portfolio import services as portfolio_services

    company, branch = _scope()
    actor = _user()
    req = _request(company, branch, actor)
    party = _party(company)
    draft = _draft(req, actor, customer_party_id=party.id)
    _make_credit(draft.doc_id)
    original = portfolio_services.link_billing_document_to_receivable

    def _fault(**_kwargs):
        raise RuntimeError("portfolio unavailable")

    monkeypatch.setattr(portfolio_services, "link_billing_document_to_receivable", _fault)
    _issue(req, actor, draft.doc_id)
    issued = OutboxEvent.objects.get(
        source_module="BILLING", event_type="DocumentIssued", payload__data__doc_id=draft.doc_id
    )
    inbox = InboxEvent.objects.get(event_id=issued.event_id, consumer=BILLING_RECEIVABLE_CONSUMER)
    assert inbox.status == InboxEvent.Status.FAILED
    assert "portfolio unavailable" in inbox.last_error
    assert not _receivables_for(company, draft.doc_id).exists()

    monkeypatch.setattr(portfolio_services, "link_billing_document_to_receivable", original)
    dispatch_accounting_outbox_events(source_module="BILLING")
    issued.refresh_from_db()
    assert issued.status == OutboxEvent.Status.SENT

    summary = reconcile_issued_credit_documents_receivables(company=company, branch=branch, actor_user=actor, request=req)
    assert summary["repaired"] == 1
    assert _receivables_for(company, draft.doc_id).count() == 1
    inbox.refresh_from_db()
    assert inbox.status == InboxEvent.Status.PROCESSED
    again = reconcile_issued_credit_documents_receivables(company=company, branch=branch, actor_user=actor, request=req)
    assert again["repaired"] == 0
    assert again["existing"] == 1
    assert _receivables_for(company, draft.doc_id).count() == 1


@pytest.mark.django_db
def test_reconciler_ignores_cash_other_branch_and_tampered_snapshot(monkeypatch):
    from apps.kernels.portfolio import services as portfolio_services

    company, branch = _scope()
    other_branch = OrgUnit.objects.create(
        unit_type=OrgUnit.UnitType.BRANCH, parent=company, name="Other", code=f"O-{uuid.uuid4().hex[:6]}"
    )
    actor = _user()

    cash_req = _request(company, branch, actor)
    cash = _draft(cash_req, actor)
    _issue(cash_req, actor, cash.doc_id)

    original = portfolio_services.link_billing_document_to_receivable
    monkeypatch.setattr(
        portfolio_services,
        "link_billing_document_to_receivable",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    party = _party(company)
    other_req = _request(company, other_branch, actor)
    other = _draft(other_req, actor, customer_party_id=party.id)
    _make_credit(other.doc_id)
    _issue(other_req, actor, other.doc_id)
    same_branch = _draft(cash_req, actor, customer_party_id=party.id)
    _make_credit(same_branch.doc_id)
    _issue(cash_req, actor, same_branch.doc_id)
    monkeypatch.setattr(portfolio_services, "link_billing_document_to_receivable", original)

    event = OutboxEvent.objects.get(payload__data__doc_id=same_branch.doc_id, event_type="DocumentIssued")
    payload = event.payload
    payload["data"]["total"] = "999999.00"
    event.payload = payload
    event.save(update_fields=["payload"])

    summary = reconcile_issued_credit_documents_receivables(company=company, branch=branch, actor_user=actor, request=cash_req)
    assert summary["repaired"] == 0
    assert not _receivables_for(company, other.doc_id).exists()
    assert not _receivables_for(company, same_branch.doc_id).exists()


@pytest.mark.django_db
def test_reconcile_api_requires_dedicated_permission_and_audits():
    company, branch = _scope()
    denied = _api_client(company, branch, permission_codes=[])
    assert denied.post("/api/billing/receivables/reconcile/", {}, format="json").status_code == 403

    allowed = _api_client(company, branch, permission_codes=["portfolio.receivable.reconcile"])
    response = allowed.post("/api/billing/receivables/reconcile/", {"limit": 25}, format="json")
    assert response.status_code == 200, response.data
    assert response.data["ok"] is True
    assert AuditEvent.objects.filter(
        event_type="PORTFOLIO_BILLING_RECEIVABLES_RECONCILED", subject_id=str(branch.id)
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_reconciler_concurrent_creates_exactly_one_receivable(monkeypatch):
    import threading
    from django.db import connection as db_conn
    from apps.kernels.portfolio import services as portfolio_services

    company, branch = _scope()
    actor = _user()
    req = _request(company, branch, actor)
    party = _party(company)
    draft = _draft(req, actor, customer_party_id=party.id)
    _make_credit(draft.doc_id)
    original = portfolio_services.link_billing_document_to_receivable
    monkeypatch.setattr(
        portfolio_services,
        "link_billing_document_to_receivable",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    _issue(req, actor, draft.doc_id)
    monkeypatch.setattr(portfolio_services, "link_billing_document_to_receivable", original)

    barrier = threading.Barrier(2, timeout=10)
    errors = []

    def _run():
        try:
            barrier.wait()
            reconcile_issued_credit_documents_receivables(company=company, branch=branch, actor_user=actor, request=req)
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
        finally:
            db_conn.close()

    threads = [threading.Thread(target=_run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, errors
    assert _receivables_for(company, draft.doc_id).count() == 1
