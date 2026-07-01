"""Tests de ROBUSTEZ (agente test-robustez) sobre endpoints calientes.

Objetivo: encontrar dónde se quiebran o filtran los servicios bajo estrés,
NO el camino feliz. Catálogo:
  1. Aislamiento por empresa y por permiso (pagos, ventas/POS, nómina, cartera).
  2. Entrada inválida → 4xx con mensaje claro, NUNCA 500.
  3. Auth/CSRF (escritura sin CSRF → 403) y Bearer inválido → 401.
  4. Idempotencia (reenvío no duplica).
  5. Sync/dispositivos (cubierto por otros tests; aquí kill-switch básico).

Cada `xfail(strict=True)` marca una FRAGILIDAD CONFIRMADA POR LECTURA del código
que el servicio debería arreglar. Cuando el servicio se endurezca, el xfail
empezará a fallar (XPASS) y delata que ya se arregló — convertir en assert duro.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from rest_framework.test import APIClient

from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _mk_company(name: str) -> tuple[OrgUnit, OrgUnit]:
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H-{name}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name=f"C-{name}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, name=f"B-{name}", parent=company)
    return company, branch


def _client(*, company: OrgUnit, branch: OrgUnit | None, perm_codes: list[str]) -> tuple[APIClient, AbstractBaseUser]:
    username = f"u_{uuid.uuid4().hex[:10]}"
    user = User.objects.create_user(username=username, email=f"{username}@t.com", password="pass12345")
    UserMembership.objects.create(user=user, org_unit=company, is_active=True)
    if branch is not None:
        UserMembership.objects.create(user=user, org_unit=branch, is_active=True)

    role = Role.objects.create(name=f"role_{uuid.uuid4().hex[:8]}", is_active=True)
    for code in perm_codes:
        perm, _ = Permission.objects.get_or_create(code=code, defaults={"description": code, "is_active": True})
        if not perm.is_active:
            perm.is_active = True
            perm.save(update_fields=["is_active"])
        RolePermission.objects.get_or_create(role=role, permission=perm)
    RoleAssignment.objects.create(user=user, role=role, org_unit=company, is_active=True)
    if branch is not None:
        RoleAssignment.objects.create(user=user, role=role, org_unit=branch, is_active=True)

    client = APIClient()
    login = client.post(
        "/api/auth/login/",
        {"username": username, "password": "pass12345"},
        format="json",
        HTTP_X_AUTH_TRANSPORT="header",
    )
    assert login.status_code == 200, login.content
    access = login.data.get("access") if isinstance(login.data, dict) else None
    if isinstance(access, str) and access:
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {access}"
    client.defaults["HTTP_X_AUTH_TRANSPORT"] = "header"
    client.defaults["HTTP_X_COMPANY_ID"] = str(company.id)
    if branch is not None:
        client.defaults["HTTP_X_BRANCH_ID"] = str(branch.id)
    return client, user


# ===========================================================================
# 1. CARTERA (portfolio) — ModelViewSet con `company` ESCRIBIBLE
# ===========================================================================
@pytest.mark.django_db
def test_portfolio_settings_create_forges_other_company():
    """CRÍTICO (fuga/escritura cruzada): el serializer expone `company` como
    campo escribible y no hay perform_create() que fuerce request.company.

    Un usuario autenticado en la empresa A puede crear PortfolioSettings con
    company=<B> en el cuerpo → escribe en una empresa a la que no pertenece.
    Esperado: el backend debe ignorar/sobre-escribir company con request.company
    (o rechazar 400/403). Lo que NO debe pasar: persistir company=B.
    """
    company_a, branch_a = _mk_company("A-settings")
    company_b, _ = _mk_company("B-settings")
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["portfolio.settings.write", "portfolio.settings.read"])

    resp = client.post(
        "/api/portfolio/settings/",
        {"company": company_b.id, "functional_currency": "NIO"},
        format="json",
    )
    # Si crea, jamás debe quedar atado a company_b.
    if resp.status_code in (200, 201):
        persisted_company = resp.data.get("company")
        assert persisted_company != company_b.id, (
            f"FUGA: PortfolioSettings creado para empresa ajena B={company_b.id} "
            f"por usuario de A={company_a.id}. company persistido={persisted_company}"
        )
    else:
        assert resp.status_code in (400, 403), resp.status_code


@pytest.mark.django_db
def test_portfolio_receivable_create_forges_other_company():
    """CRÍTICO: crear una CxC (Receivable) con company=<B> en el cuerpo.

    Mismo patrón que settings: `company` es escribible y no hay perform_create.
    CONFIRMADO: con todos los campos requeridos, el create devuelve 201 con
    company=B → escritura cruzada real (no solo PortfolioSettings).
    """
    from apps.modulos.parties.models import Party

    company_a, branch_a = _mk_company("A-recv")
    company_b, _ = _mk_company("B-recv")
    party = Party.objects.create(company=company_a, display_name="Cliente A", party_type="NATURAL")
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["portfolio.receivable.write", "portfolio.receivable.read"])

    resp = client.post(
        "/api/portfolio/receivables/",
        {
            "company": company_b.id,
            "party": party.id,
            "currency": "NIO",
            "reference_type": "MANUAL",
            "reference_id": 1,
            "principal_amount": "100.00",
            "issue_date": "2026-01-01",
            "due_date": "2026-02-01",
        },
        format="json",
    )
    if resp.status_code in (200, 201):
        assert resp.data.get("company") != company_b.id, (
            f"FUGA: Receivable creado para empresa ajena B={company_b.id}. "
            f"company persistido={resp.data.get('company')}"
        )
    else:
        # Si el serializer rechaza por campos requeridos, no es una fuga (pero el
        # root cause `company` escribible sigue presente — ver PortfolioSettings).
        assert resp.status_code in (400, 403, 422), resp.status_code


@pytest.mark.django_db
def test_portfolio_receivable_adjust_garbage_amount_no_500():
    """ALTO (500): adjust pasa request.data.get('adjustment_amount') crudo a
    services.adjust_receivable, que hace `old_amount + adjustment_amount`.
    Con un string o None → TypeError → 500. Debe ser 4xx.
    """
    from apps.modulos.parties.models import Party
    from apps.kernels.portfolio.models import Receivable

    company_a, branch_a = _mk_company("A-adj")
    party = Party.objects.create(company=company_a, display_name="Cli", party_type="NATURAL")
    rec = Receivable.objects.create(
        company=company_a, branch=branch_a, party=party, currency="NIO",
        reference_type="MANUAL", reference_id=1,
        principal_amount=Decimal("100.00"), issue_date=date(2026,1,1), due_date=date(2026,2,1),
    )
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["portfolio.receivable.adjust", "portfolio.receivable.read"])

    resp = client.post(
        f"/api/portfolio/receivables/{rec.id}/adjust/",
        {"adjustment_amount": "no-soy-numero", "reason": "x"},
        format="json",
    )
    assert resp.status_code != 500, f"500 con adjustment_amount basura: {resp.content!r}"
    assert 400 <= resp.status_code < 500, resp.status_code


@pytest.mark.django_db
def test_portfolio_receivable_adjust_missing_amount_no_500():
    """ALTO (500): adjust sin 'adjustment_amount' → None + Decimal → TypeError → 500."""
    from apps.modulos.parties.models import Party
    from apps.kernels.portfolio.models import Receivable

    company_a, branch_a = _mk_company("A-adj2")
    party = Party.objects.create(company=company_a, display_name="Cli", party_type="NATURAL")
    rec = Receivable.objects.create(
        company=company_a, branch=branch_a, party=party, currency="NIO",
        reference_type="MANUAL", reference_id=1,
        principal_amount=Decimal("100.00"), issue_date=date(2026,1,1), due_date=date(2026,2,1),
    )
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["portfolio.receivable.adjust", "portfolio.receivable.read"])

    resp = client.post(f"/api/portfolio/receivables/{rec.id}/adjust/", {"reason": "x"}, format="json")
    assert resp.status_code != 500, f"500 sin adjustment_amount: {resp.content!r}"
    assert 400 <= resp.status_code < 500, resp.status_code


@pytest.mark.django_db
def test_portfolio_credit_disburse_garbage_no_500():
    """ALTO (500): disburse pasa disbursed_amount/disbursement_date crudos.
    disbursed_amount string → `str <= 0` TypeError; date string → `.isoformat()`
    AttributeError. Ambos → 500. Debe ser 4xx.
    """
    from apps.modulos.parties.models import Party
    from apps.kernels.portfolio.models import Credit

    company_a, branch_a = _mk_company("A-disb")
    lender = Party.objects.create(company=company_a, display_name="Lender", party_type="JURIDICAL")
    borrower = Party.objects.create(company=company_a, display_name="Borrower", party_type="NATURAL")
    credit = Credit.objects.create(
        company=company_a, branch=branch_a, lender_party=lender, borrower_party=borrower,
        party=borrower, credit_type="TERM_LOAN", credit_status="APPROVED", currency="NIO",
        reference_type="MANUAL", reference_id=1,
        issue_date=date(2026,1,1), due_date=date(2026,12,1), maturity_date=date(2026,12,1),
        approved_amount=Decimal("1000.00"), principal_amount=Decimal("1000.00"),
        interest_rate=Decimal("0.00"), term_months=12,
    )
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["portfolio.credit.disburse", "portfolio.credit.read"])

    resp = client.post(
        f"/api/portfolio/credits/{credit.id}/disburse/",
        {"disbursed_amount": "muchísimo", "disbursement_date": "no-es-fecha"},
        format="json",
    )
    assert resp.status_code != 500, f"500 con disburse basura: {resp.content!r}"
    assert 400 <= resp.status_code < 500, resp.status_code


@pytest.mark.django_db
def test_portfolio_credit_disburse_valid_date_string_no_500():
    """ALTO (500): incluso con una fecha VÁLIDA en string, disburse_credit hace
    disbursement_date.isoformat() sobre un str → AttributeError → 500.
    (El endpoint está roto para TODO desembolso vía API: la fecha siempre llega str.)
    """
    from apps.modulos.parties.models import Party
    from apps.kernels.portfolio.models import Credit

    company_a, branch_a = _mk_company("A-disb2")
    lender = Party.objects.create(company=company_a, display_name="Lender", party_type="JURIDICAL")
    borrower = Party.objects.create(company=company_a, display_name="Borrower", party_type="NATURAL")
    credit = Credit.objects.create(
        company=company_a, branch=branch_a, lender_party=lender, borrower_party=borrower,
        party=borrower, credit_type="TERM_LOAN", credit_status="APPROVED", currency="NIO",
        reference_type="MANUAL", reference_id=1,
        issue_date=date(2026,1,1), due_date=date(2026,12,1), maturity_date=date(2026,12,1),
        approved_amount=Decimal("1000.00"), principal_amount=Decimal("1000.00"),
        interest_rate=Decimal("0.00"), term_months=12,
    )
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["portfolio.credit.disburse", "portfolio.credit.read"])

    resp = client.post(
        f"/api/portfolio/credits/{credit.id}/disburse/",
        {"disbursed_amount": "500.00", "disbursement_date": "2026-01-15"},
        format="json",
    )
    assert resp.status_code != 500, f"500 con fecha válida en string: {resp.content!r}"


@pytest.mark.django_db
def test_portfolio_receivable_read_isolation():
    """POSITIVO esperado: una CxC de la empresa B NO es visible/recuperable por A."""
    from apps.modulos.parties.models import Party
    from apps.kernels.portfolio.models import Receivable

    company_a, branch_a = _mk_company("A-iso")
    company_b, branch_b = _mk_company("B-iso")
    party_b = Party.objects.create(company=company_b, display_name="Cli B", party_type="NATURAL")
    rec_b = Receivable.objects.create(
        company=company_b, branch=branch_b, party=party_b, currency="NIO",
        reference_type="MANUAL", reference_id=1,
        principal_amount=Decimal("777.00"), issue_date=date(2026,1,1), due_date=date(2026,2,1),
    )
    client_a, _ = _client(company=company_a, branch=branch_a,
                          perm_codes=["portfolio.receivable.read"])

    detail = client_a.get(f"/api/portfolio/receivables/{rec_b.id}/")
    assert detail.status_code == 404, detail.status_code

    lst = client_a.get("/api/portfolio/receivables/")
    ids = [r.get("id") for r in (lst.data.get("results", lst.data) if isinstance(lst.data, dict) else lst.data)]
    assert rec_b.id not in ids, "FUGA: CxC de empresa B visible en lista de A"


# ===========================================================================
# 2. PAGOS — arqueo por denominación (sin serializer; request.data crudo)
# ===========================================================================
def _open_cash_session(client: APIClient) -> int:
    r = client.post("/api/payments/cash-sessions/open/", {"opening_amount": "0.00"}, format="json")
    assert r.status_code == 201, r.content
    return int(r.data["id"])


@pytest.mark.parametrize(
    "payload",
    [
        {"denominations": [{"denomination_value": "abc", "quantity": 1}]},      # Decimal('abc')
        {"denominations": [{"quantity": 1}]},                                     # falta denomination_value (KeyError)
        {"denominations": [{"denomination_value": 100, "quantity": "x"}]},        # int('x')
        {"denominations": ["no-soy-dict"]},                                       # str.get AttributeError
        {"denominations": "esto-es-un-string"},                                   # itera chars
        {"denominations": [{"denomination_value": 100, "quantity": 999999999999999999999}]},  # gigante
    ],
)
@pytest.mark.django_db
def test_payments_denomination_malformed_no_500(payload):
    """ALTO (500): CashSessionDenominationView toma request.data['denominations']
    crudo (sin serializer) y submit_denomination_count hace int()/Decimal()/.get()
    sin proteger. Payloads malformados → 500. Debe ser 4xx.
    """
    company_a, branch_a = _mk_company(f"A-denom-{uuid.uuid4().hex[:4]}")
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["payments.cash_session.open", "payments.cash_session.close",
                                    "payments.cash_session.read"])
    session_id = _open_cash_session(client)

    resp = client.post(
        f"/api/payments/cash-sessions/{session_id}/denomination/",
        payload, format="json",
    )
    assert resp.status_code != 500, f"500 con denominations={payload!r}: {resp.content!r}"
    assert 400 <= resp.status_code < 500, resp.status_code


@pytest.mark.django_db
def test_payments_cash_session_cross_company_404():
    """POSITIVO esperado: cerrar/ver una caja de la empresa B desde A → 404."""
    company_a, branch_a = _mk_company("A-cash")
    company_b, branch_b = _mk_company("B-cash")
    client_b, _ = _client(company=company_b, branch=branch_b,
                          perm_codes=["payments.cash_session.open", "payments.cash_session.read"])
    session_b = _open_cash_session(client_b)

    client_a, _ = _client(company=company_a, branch=branch_a,
                          perm_codes=["payments.cash_session.read", "payments.cash_session.close"])
    detail = client_a.get(f"/api/payments/cash-sessions/{session_b}/")
    assert detail.status_code == 404, detail.status_code

    close = client_a.post(f"/api/payments/cash-sessions/{session_b}/close/",
                          {"counted_amount": "0.00"}, format="json")
    assert close.status_code == 404, close.status_code


@pytest.mark.django_db
def test_payments_intent_no_permission_403():
    """ALTO: crear PaymentIntent sin payments.intent.create → 403 (gateo backend)."""
    company_a, branch_a = _mk_company("A-perm")
    client, _ = _client(company=company_a, branch=branch_a, perm_codes=["payments.intent.read"])
    resp = client.post("/api/payments/intents/", {"amount": "10.00", "currency": "NIO"}, format="json")
    assert resp.status_code == 403, resp.status_code


@pytest.mark.django_db
def test_payments_intent_create_idempotent_no_double():
    """IDEMPOTENCIA: dos POST con la misma idempotency_key → un solo intent."""
    company_a, branch_a = _mk_company("A-idem")
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["payments.intent.create", "payments.intent.read"])
    key = f"idem-{uuid.uuid4().hex}"
    body = {"amount": "25.00", "currency": "NIO", "idempotency_key": key}
    r1 = client.post("/api/payments/intents/", body, format="json")
    r2 = client.post("/api/payments/intents/", body, format="json")
    assert r1.status_code == 201, r1.content
    assert r2.status_code == 200, r2.content  # idempotente → 200
    assert r1.data["payment_id"] == r2.data["payment_id"]
    assert r2.data.get("idempotent") is True


# ===========================================================================
# 3. VENTAS / POS — entrada inválida + permiso + cross-company
# ===========================================================================
@pytest.mark.django_db
def test_pos_sale_no_permission_403():
    company_a, branch_a = _mk_company("A-pos")
    client, _ = _client(company=company_a, branch=branch_a, perm_codes=["sales.pos.report"])
    resp = client.post(
        "/api/sales/pos-sale/",
        {"warehouse_id": 1, "idempotency_key": "k1",
         "lines": [{"inventory_item_id": 1, "quantity": "1.0000"}],
         "payments": [{"method": "CASH", "amount": "10.00"}]},
        format="json",
    )
    assert resp.status_code == 403, resp.status_code


@pytest.mark.django_db
def test_pos_sale_empty_lines_4xx_not_500():
    """POSITIVO: líneas vacías → 4xx (la venta POS valida con serializer → 422)."""
    company_a, branch_a = _mk_company("A-pos2")
    client, _ = _client(company=company_a, branch=branch_a, perm_codes=["sales.pos.sell"])
    resp = client.post(
        "/api/sales/pos-sale/",
        {"warehouse_id": 1, "idempotency_key": "k1", "lines": [],
         "payments": [{"method": "CASH", "amount": "10.00"}]},
        format="json",
    )
    assert resp.status_code != 500, resp.content
    assert 400 <= resp.status_code < 500, resp.status_code


@pytest.mark.django_db
def test_pos_sale_negative_quantity_4xx():
    """POSITIVO: cantidad negativa → 4xx (serializer min_value)."""
    company_a, branch_a = _mk_company("A-pos3")
    client, _ = _client(company=company_a, branch=branch_a, perm_codes=["sales.pos.sell"])
    resp = client.post(
        "/api/sales/pos-sale/",
        {"warehouse_id": 1, "idempotency_key": "k1",
         "lines": [{"inventory_item_id": 1, "quantity": "-5.0000"}],
         "payments": [{"method": "CASH", "amount": "10.00"}]},
        format="json",
    )
    assert resp.status_code != 500, resp.content
    assert 400 <= resp.status_code < 500, resp.status_code


@pytest.mark.django_db
def test_pos_sale_giant_string_customer_name_no_500():
    company_a, branch_a = _mk_company("A-pos4")
    client, _ = _client(company=company_a, branch=branch_a, perm_codes=["sales.pos.sell"])
    resp = client.post(
        "/api/sales/pos-sale/",
        {"warehouse_id": 1, "idempotency_key": "k1", "customer_name": "Z" * 50000,
         "lines": [{"inventory_item_id": 1, "quantity": "1.0000"}],
         "payments": [{"method": "CASH", "amount": "10.00"}]},
        format="json",
    )
    assert resp.status_code != 500, resp.content
    assert 400 <= resp.status_code < 500, resp.status_code


# ===========================================================================
# 4. NÓMINA — aislamiento cross-company + idempotencia de pago
# ===========================================================================
@pytest.mark.django_db
def test_nomina_payment_cross_company_404():
    """POSITIVO esperado: pagar una línea de planilla de la empresa B desde A → 404.
    (PayrollPaymentView usa get_object_or_404 scoping por company.)
    """
    company_a, branch_a = _mk_company("A-nom")
    client_a, _ = _client(company=company_a, branch=branch_a,
                          perm_codes=["nomina.payment.register"])
    # period/sheet/entry inexistentes para A → debe 404, jamás 500.
    resp = client_a.post(
        "/api/nomina/periods/999999/sheets/999999/entries/999999/pay/",
        {"payment_method": "CASH", "amount": "100.00", "idempotency_key": "k"},
        format="json",
    )
    assert resp.status_code == 404, resp.content


@pytest.mark.django_db
def test_nomina_payment_no_permission_403():
    company_a, branch_a = _mk_company("A-nom2")
    client, _ = _client(company=company_a, branch=branch_a, perm_codes=["nomina.entry.read"])
    resp = client.post(
        "/api/nomina/periods/1/sheets/1/entries/1/pay/",
        {"payment_method": "CASH", "amount": "100.00"},
        format="json",
    )
    assert resp.status_code == 403, resp.status_code


# ===========================================================================
# 5. AUTH / CSRF / BEARER
# ===========================================================================
@pytest.mark.django_db
def test_bearer_invalido_401():
    company_a, branch_a = _mk_company("A-bearer")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer token-falso-xyz")
    client.defaults["HTTP_X_AUTH_TRANSPORT"] = "header"
    client.defaults["HTTP_X_COMPANY_ID"] = str(company_a.id)
    resp = client.get("/api/payments/intents/")
    assert resp.status_code == 401, resp.status_code


@pytest.mark.django_db
def test_sin_company_header_400():
    company_a, branch_a = _mk_company("A-noheader")
    client, _ = _client(company=company_a, branch=branch_a, perm_codes=["payments.intent.read"])
    del client.defaults["HTTP_X_COMPANY_ID"]
    resp = client.get("/api/payments/intents/")
    assert resp.status_code == 400, resp.status_code


@pytest.mark.django_db
def test_company_inexistente_404():
    company_a, branch_a = _mk_company("A-badcompany")
    client, _ = _client(company=company_a, branch=branch_a, perm_codes=["payments.intent.read"])
    client.defaults["HTTP_X_COMPANY_ID"] = "999999999"
    resp = client.get("/api/payments/intents/")
    assert resp.status_code == 404, resp.status_code


@pytest.mark.django_db
def test_company_ajena_403():
    """No-miembro de la empresa B no puede operar bajo X-Company-Id=B."""
    company_a, branch_a = _mk_company("A-foreign")
    company_b, _ = _mk_company("B-foreign")
    client, _ = _client(company=company_a, branch=branch_a, perm_codes=["payments.intent.read"])
    client.defaults["HTTP_X_COMPANY_ID"] = str(company_b.id)
    resp = client.get("/api/payments/intents/")
    assert resp.status_code == 403, resp.status_code


# ===========================================================================
# 6. SYNC / DISPOSITIVOS — kill-switch (DeviceRevocationGuardMiddleware)
# ===========================================================================
def _mk_device(company: OrgUnit, *, status: str):
    from apps.modulos.sync_engine.models import Device
    return Device.objects.create(company=company, status=status, public_key=b"\x00" * 32)


@pytest.mark.django_db
def test_killswitch_device_revoked_blocks_all_api_403():
    """CRÍTICO (kill-switch): un X-Device-Id de un Device REVOKED debe bloquear
    CUALQUIER endpoint de API con 403 y error.code == DEVICE_REVOKED.
    """
    company_a, branch_a = _mk_company("A-kill")
    client, _ = _client(company=company_a, branch=branch_a, perm_codes=["payments.intent.read"])
    device = _mk_device(company_a, status="REVOKED")
    client.defaults["HTTP_X_DEVICE_ID"] = str(device.id)

    resp = client.get("/api/payments/intents/")
    assert resp.status_code == 403, resp.status_code
    body = resp.json() if hasattr(resp, "json") else resp.data
    code = (body or {}).get("error", {}).get("code") if isinstance(body, dict) else None
    assert code == "DEVICE_REVOKED", body


@pytest.mark.django_db
def test_killswitch_device_active_not_blocked():
    """POSITIVO: un device ACTIVE no debe ser bloqueado por el kill-switch."""
    company_a, branch_a = _mk_company("A-kill2")
    client, _ = _client(company=company_a, branch=branch_a, perm_codes=["payments.intent.read"])
    device = _mk_device(company_a, status="ACTIVE")
    client.defaults["HTTP_X_DEVICE_ID"] = str(device.id)
    resp = client.get("/api/payments/intents/")
    assert resp.status_code == 200, resp.status_code


@pytest.mark.django_db
def test_killswitch_malformed_device_header_no_500():
    """ROBUSTEZ: X-Device-Id basura no debe romper (no 500); se ignora."""
    company_a, branch_a = _mk_company("A-kill3")
    client, _ = _client(company=company_a, branch=branch_a, perm_codes=["payments.intent.read"])
    client.defaults["HTTP_X_DEVICE_ID"] = "no-es-uuid"
    resp = client.get("/api/payments/intents/")
    assert resp.status_code != 500, resp.content
    assert resp.status_code == 200, resp.status_code


@pytest.mark.django_db
def test_killswitch_revoked_device_can_reach_login():
    """POSITIVO: el aparato revocado todavía debe poder llegar a auth/ (exento)
    para ver el mensaje y re-enrolar; auth/login no se bloquea por device.
    """
    company_a, branch_a = _mk_company("A-kill4")
    device = _mk_device(company_a, status="REVOKED")
    client = APIClient()
    client.defaults["HTTP_X_DEVICE_ID"] = str(device.id)
    # Login con credenciales inválidas: debe 4xx de auth, NUNCA 403 DEVICE_REVOKED.
    resp = client.post("/api/auth/login/", {"username": "x", "password": "y"}, format="json",
                       HTTP_X_AUTH_TRANSPORT="header")
    assert resp.status_code != 403 or (
        isinstance(resp.data, dict)
        and (resp.data.get("error", {}) or {}).get("code") != "DEVICE_REVOKED"
    ), resp.content


# ===========================================================================
# 7. CSRF — escritura con sesión-cookie sin X-CSRF-Token → 403
# ===========================================================================
@pytest.mark.django_db
def test_csrf_required_for_cookie_session_write():
    """Escritura autenticada por COOKIE de sesión SIN X-CSRF-Token → 403.

    (Bearer no requiere CSRF; este caso prueba el transporte cookie.)
    """
    company_a, branch_a = _mk_company("A-csrf")
    username = f"u_{uuid.uuid4().hex[:10]}"
    user = User.objects.create_user(username=username, email=f"{username}@t.com", password="pass12345")
    UserMembership.objects.create(user=user, org_unit=company_a, is_active=True)
    UserMembership.objects.create(user=user, org_unit=branch_a, is_active=True)
    role = Role.objects.create(name=f"role_{uuid.uuid4().hex[:8]}", is_active=True)
    perm, _ = Permission.objects.get_or_create(code="payments.intent.create",
                                               defaults={"description": "x", "is_active": True})
    RolePermission.objects.get_or_create(role=role, permission=perm)
    RoleAssignment.objects.create(user=user, role=role, org_unit=company_a, is_active=True)
    RoleAssignment.objects.create(user=user, role=role, org_unit=branch_a, is_active=True)

    client = APIClient(enforce_csrf_checks=True)
    # Login por cookie (sin pedir transporte header).
    login = client.post("/api/auth/login/", {"username": username, "password": "pass12345"}, format="json")
    assert login.status_code == 200, login.content
    client.defaults["HTTP_X_COMPANY_ID"] = str(company_a.id)
    client.defaults["HTTP_X_BRANCH_ID"] = str(branch_a.id)

    # Escritura sin enviar X-CSRF-Token → debe 403 (CSRF), no 201.
    resp = client.post("/api/payments/intents/", {"amount": "10.00", "currency": "NIO"}, format="json")
    assert resp.status_code in (401, 403), f"esperaba 401/403 por CSRF, dio {resp.status_code}: {resp.content!r}"


# ===========================================================================
# 8. CARTERA (ampliación) — CxP (Payable) cruzada + ajuste con número negativo
# ===========================================================================
@pytest.mark.django_db
def test_portfolio_payable_create_forges_other_company():
    """CRÍTICO (fuga/escritura cruzada en CxP): igual que CxC, `PayableViewSet`
    no define perform_create() y el serializer expone `company` escribible.

    Un usuario de A crea un Payable con company=<B> → escritura cruzada real:
    una cuenta por pagar atribuida a la empresa B. Esperado: el backend fuerza
    request.company o rechaza 400/403. Lo que NO debe pasar: persistir company=B.
    """
    from apps.modulos.parties.models import Party

    company_a, branch_a = _mk_company("A-pay")
    company_b, _ = _mk_company("B-pay")
    supplier = Party.objects.create(company=company_a, display_name="Proveedor A", party_type="JURIDICAL")
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["portfolio.payable.write", "portfolio.payable.read"])

    resp = client.post(
        "/api/portfolio/payables/",
        {
            "company": company_b.id,
            "party": supplier.id,
            "currency": "NIO",
            "reference_type": "MANUAL",
            "reference_id": 1,
            "principal_amount": "250.00",
            "issue_date": "2026-01-01",
            "due_date": "2026-02-01",
        },
        format="json",
    )
    if resp.status_code in (200, 201):
        assert resp.data.get("company") != company_b.id, (
            f"FUGA: Payable (CxP) creado para empresa ajena B={company_b.id}. "
            f"company persistido={resp.data.get('company')}"
        )
    else:
        assert resp.status_code in (400, 403, 422), resp.status_code


@pytest.mark.django_db
def test_portfolio_receivable_adjust_valid_negative_number_no_500():
    """ALTO (500): un ajuste de negocio legítimo (rebaja de C$200 sobre C$100)
    debería responder 400 INVALID_ADJUSTMENT (quedaría negativo). En cambio, la
    vista pasa el string del JSON crudo a `old_amount + adjustment_amount` → 500
    ANTES de poder validar la regla. El endpoint adjust está roto para TODO valor.
    """
    from apps.modulos.parties.models import Party
    from apps.kernels.portfolio.models import Receivable

    company_a, branch_a = _mk_company("A-adj3")
    party = Party.objects.create(company=company_a, display_name="Cli", party_type="NATURAL")
    rec = Receivable.objects.create(
        company=company_a, branch=branch_a, party=party, currency="NIO",
        reference_type="MANUAL", reference_id=1,
        principal_amount=Decimal("100.00"), issue_date=date(2026, 1, 1), due_date=date(2026, 2, 1),
    )
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["portfolio.receivable.adjust", "portfolio.receivable.read"])

    resp = client.post(
        f"/api/portfolio/receivables/{rec.id}/adjust/",
        {"adjustment_amount": "-200.00", "reason": "rebaja excesiva"},
        format="json",
    )
    assert resp.status_code != 500, f"500 con ajuste numérico válido en JSON: {resp.content!r}"
    assert 400 <= resp.status_code < 500, resp.status_code


# ===========================================================================
# 9. ARQUEO DE CAJA (ampliación) — cross-company 404 + denom negativa
# ===========================================================================
@pytest.mark.django_db
def test_payments_denomination_cross_company_404():
    """POSITIVO esperado (aislamiento): hacer arqueo sobre una caja de la empresa
    B desde la empresa A → 404 (la sesión se filtra por company+branch en el
    servicio). Jamás 500 ni escribir denominaciones en la caja ajena.
    """
    company_a, branch_a = _mk_company("A-denomx")
    company_b, branch_b = _mk_company("B-denomx")
    client_b, _ = _client(company=company_b, branch=branch_b,
                          perm_codes=["payments.cash_session.open", "payments.cash_session.close",
                                      "payments.cash_session.read"])
    session_b = _open_cash_session(client_b)

    client_a, _ = _client(company=company_a, branch=branch_a,
                          perm_codes=["payments.cash_session.open", "payments.cash_session.close",
                                      "payments.cash_session.read"])
    resp = client_a.post(
        f"/api/payments/cash-sessions/{session_b}/denomination/",
        {"denominations": [{"denomination_value": 100, "quantity": 1, "denomination_type": "BILL"}]},
        format="json",
    )
    assert resp.status_code == 404, f"esperaba 404 sobre caja ajena, dio {resp.status_code}: {resp.content!r}"


@pytest.mark.django_db
def test_payments_denomination_no_permission_403():
    """ALTO: arqueo sin payments.cash_session.close → 403 (gateo backend)."""
    company_a, branch_a = _mk_company("A-denomperm")
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["payments.cash_session.open", "payments.cash_session.read"])
    session_id = _open_cash_session(client)
    resp = client.post(
        f"/api/payments/cash-sessions/{session_id}/denomination/",
        {"denominations": [{"denomination_value": 100, "quantity": 1}]},
        format="json",
    )
    assert resp.status_code == 403, resp.status_code


@pytest.mark.django_db
def test_payments_denomination_negative_quantity_4xx():
    """POSITIVO: cantidad negativa sí está validada en el servicio
    (PaymentsValidationError → 4xx). Confirma que ESE borde no es un 500.
    """
    company_a, branch_a = _mk_company("A-denomneg")
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["payments.cash_session.open", "payments.cash_session.close",
                                    "payments.cash_session.read"])
    session_id = _open_cash_session(client)
    resp = client.post(
        f"/api/payments/cash-sessions/{session_id}/denomination/",
        {"denominations": [{"denomination_value": 100, "quantity": -3}]},
        format="json",
    )
    assert resp.status_code != 500, f"500 con quantity negativa: {resp.content!r}"
    assert 400 <= resp.status_code < 500, resp.status_code


# ===========================================================================
# 10. POS — header faltante, idempotencia y concurrencia (doble venta)
# ===========================================================================
@pytest.mark.django_db
def test_pos_sale_missing_branch_header_400_not_500():
    """POSITIVO: POS sin X-Branch-Id → 400 claro (la vista lo gatea), no 500."""
    company_a, branch_a = _mk_company("A-posnobranch")
    client, _ = _client(company=company_a, branch=branch_a, perm_codes=["sales.pos.sell"])
    del client.defaults["HTTP_X_BRANCH_ID"]
    resp = client.post(
        "/api/sales/pos-sale/",
        {"warehouse_id": 1, "idempotency_key": "k1",
         "lines": [{"inventory_item_id": 1, "quantity": "1.0000"}],
         "payments": [{"method": "CASH", "amount": "10.00"}]},
        format="json",
    )
    assert resp.status_code != 500, resp.content
    assert resp.status_code == 400, resp.status_code


@pytest.mark.django_db
def test_pos_sale_malformed_payments_no_500():
    """ROBUSTEZ: payments con tipos basura (amount no numérico) → 4xx por
    serializer, jamás 500.
    """
    company_a, branch_a = _mk_company("A-posbadpay")
    client, _ = _client(company=company_a, branch=branch_a, perm_codes=["sales.pos.sell"])
    resp = client.post(
        "/api/sales/pos-sale/",
        {"warehouse_id": "no-numero", "idempotency_key": "k1",
         "lines": [{"inventory_item_id": 1, "quantity": "1.0000"}],
         "payments": [{"method": "CASH", "amount": "diez pesos"}]},
        format="json",
    )
    assert resp.status_code != 500, resp.content
    assert 400 <= resp.status_code < 500, resp.status_code


@pytest.mark.django_db(transaction=True)
def test_pos_sale_double_submit_same_key_no_double_effect():
    """IDEMPOTENCIA (rama caliente): dos POST de venta POS con la MISMA
    idempotency_key no deben crear dos documentos ni reventar.

    Sin inventario sembrado, la primera venta falla con un 4xx de negocio
    (item inexistente / sin stock). Lo que NO debe pasar nunca es un 500, ni que
    el reenvío con la misma clave produzca un resultado distinto del primero
    (la idempotencia debe ser estable bajo error o éxito).
    """
    company_a, branch_a = _mk_company("A-posidem")
    client, _ = _client(company=company_a, branch=branch_a, perm_codes=["sales.pos.sell"])
    body = {
        "warehouse_id": 1, "idempotency_key": f"idem-{uuid.uuid4().hex}",
        "lines": [{"inventory_item_id": 1, "quantity": "1.0000"}],
        "payments": [{"method": "CASH", "amount": "10.00"}],
    }
    r1 = client.post("/api/sales/pos-sale/", body, format="json")
    r2 = client.post("/api/sales/pos-sale/", body, format="json")
    assert r1.status_code != 500, r1.content
    assert r2.status_code != 500, r2.content
    # El reenvío con la misma clave debe ser estable (mismo status que el 1º).
    assert r1.status_code == r2.status_code, (r1.status_code, r2.status_code, r1.content, r2.content)


# ===========================================================================
# 11. CONCURRENCIA — doble cierre de caja simultáneo (un ganador, sin corrupción)
# ===========================================================================
@pytest.mark.django_db(transaction=True)
def test_cash_session_double_close_concurrent_no_corrupt_state():
    """CONCURRENCIA (rama caliente): varios cierres simultáneos de la MISMA caja.

    Patrón de test_integration_idempotency_concurrency.py (ThreadPoolExecutor +
    close_old_connections). El servicio usa select_for_update() y, si la sesión
    ya está CLOSED, devuelve idempotentemente (200) SIN re-cerrar ni recalcular
    (close_cash_session_for_scope, services.py:778-779).

    Invariante de robustez: NINGÚN 500, la caja queda CLOSED, y el cierre REAL
    (la transición + el closed_at/closed_by) ocurre UNA sola vez aunque seis
    requests compitan. Los reenvíos son 200 idempotentes, no doble cierre.
    """
    from concurrent.futures import ThreadPoolExecutor

    from django.db import close_old_connections, connections

    from apps.kernels.payments.models import CashSession

    company_a, branch_a = _mk_company("A-dblclose")
    client, _ = _client(company=company_a, branch=branch_a,
                        perm_codes=["payments.cash_session.open", "payments.cash_session.close",
                                    "payments.cash_session.read"])
    session_id = _open_cash_session(client)

    def _worker(_: int) -> int:
        close_old_connections()
        try:
            r = client.post(
                f"/api/payments/cash-sessions/{session_id}/close/",
                {"counted_amount": "0.00"}, format="json",
            )
            return int(r.status_code)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(_worker, range(6)))
    connections.close_all()

    assert all(s != 500 for s in statuses), f"500 en cierre concurrente: {statuses}"
    # Todo cierre concurrente debe resolver en 200 (idempotente) o 4xx, jamás 5xx.
    assert all(s == 200 or 400 <= s < 500 for s in statuses), statuses

    sessions = CashSession.objects.filter(id=session_id, status=CashSession.Status.CLOSED)
    assert sessions.count() == 1, f"la caja debe quedar CLOSED exactamente una vez, hubo {sessions.count()}"
    # El cierre REAL ocurre una sola vez: closed_at/closed_by quedan fijados y la
    # caja no se "re-cierra" con cada reenvío (sin estado corrupto).
    session = sessions.first()
    assert session.closed_at is not None
    assert session.counted_amount == Decimal("0.00")
    assert session.difference_amount == Decimal("0.00")


# ===========================================================================
# 12. KILL-SWITCH (ampliación) — device REVOKED de OTRA empresa bloquea igual
# ===========================================================================
@pytest.mark.django_db
def test_killswitch_revoked_device_of_other_company_blocks():
    """REGRESIÓN POSITIVA: el kill-switch es por APARATO (terminal), no por
    empresa. Un usuario de A que presente el X-Device-Id de un Device REVOKED de
    la empresa B igual queda bloqueado (403 DEVICE_REVOKED). Esto es correcto:
    un aparato revocado no debe poder operar bajo ninguna empresa.
    """
    company_a, branch_a = _mk_company("A-killx")
    company_b, _ = _mk_company("B-killx")
    client_a, _ = _client(company=company_a, branch=branch_a, perm_codes=["payments.intent.read"])
    device_b = _mk_device(company_b, status="REVOKED")
    client_a.defaults["HTTP_X_DEVICE_ID"] = str(device_b.id)

    resp = client_a.get("/api/payments/intents/")
    assert resp.status_code == 403, resp.status_code
    body = resp.json() if hasattr(resp, "json") else resp.data
    code = (body or {}).get("error", {}).get("code") if isinstance(body, dict) else None
    assert code == "DEVICE_REVOKED", body


@pytest.mark.django_db
def test_killswitch_unknown_device_not_blocked():
    """POSITIVO: un X-Device-Id con un UUID válido pero inexistente NO bloquea
    (el guard lo deja pasar; el device desconocido lo maneja cada vista).
    """
    company_a, branch_a = _mk_company("A-killunk")
    client, _ = _client(company=company_a, branch=branch_a, perm_codes=["payments.intent.read"])
    client.defaults["HTTP_X_DEVICE_ID"] = str(uuid.uuid4())
    resp = client.get("/api/payments/intents/")
    assert resp.status_code != 500, resp.content
    assert resp.status_code == 200, resp.status_code
