"""Tests de contratos a fondo (Ola F): versionado, renovación, firmas, tipos, vencimientos."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.modulos.hr.models import (
    ContractSignature,
    Employee,
    EmploymentContract,
)
from apps.modulos.hr.services import create_contract_draft, issue_contract
from apps.modulos.hr.services_contracts import (
    amend_contract,
    expiring_contracts,
    register_signature,
    renew_contract,
)
from apps.modulos.iam.models import OrgUnit

User = get_user_model()
UT = OrgUnit.UnitType


def _mk_org():
    s = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=UT.HOLDING, name=f"H_{s}")
    company = OrgUnit.objects.create(unit_type=UT.COMPANY, name=f"C_{s}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=UT.BRANCH, name=f"B_{s}", parent=company)
    return holding, company, branch


def _mk_user():
    u = f"hr_{uuid.uuid4().hex[:8]}"
    return User.objects.create_user(username=u, email=f"{u}@t.local", password="pass12345")


def _mk_employee(company):
    return Employee.objects.create(company=company, first_name="Ana", last_name="López")


def _draft(emp, ctype=EmploymentContract.ContractType.INDEFINIDO, **kw):
    return create_contract_draft(
        employee=emp,
        contract_type=ctype,
        start_date=kw.get("start_date", date(2025, 1, 1)),
        end_date=kw.get("end_date"),
        salary_amount=kw.get("salary_amount", Decimal("12000.00")),
        actor=kw.get("actor"),
    )


@pytest.mark.django_db
def test_issue_snapshots_version_1():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    c = _draft(emp)
    assert c.versions.count() == 0
    issue_contract(contract=c, actor=_mk_user())
    c.refresh_from_db()
    assert c.status == EmploymentContract.Status.EMITIDO
    versions = list(c.versions.all())
    assert len(versions) == 1
    assert versions[0].version_no == 1
    assert versions[0].body == c.body


@pytest.mark.django_db
def test_amend_creates_version_2_and_updates_body():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    actor = _mk_user()
    c = _draft(emp)
    issue_contract(contract=c, actor=actor)
    v = amend_contract(contract=c, body="TEXTO DE ADENDA", reason="Aumento salarial", actor=actor)
    c.refresh_from_db()
    assert v.version_no == 2
    assert c.body == "TEXTO DE ADENDA"
    assert c.versions.count() == 2


@pytest.mark.django_db
def test_amend_requires_issued_contract():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    c = _draft(emp)  # BORRADOR
    with pytest.raises(ValueError) as exc:
        amend_contract(contract=c, body="x", reason="y", actor=_mk_user())
    assert str(exc.value) == "CONTRACT_NOT_ISSUED"


@pytest.mark.django_db
def test_renew_finalizes_previous_and_chains():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    actor = _mk_user()
    prev = _draft(emp, EmploymentContract.ContractType.PLAZO_FIJO, end_date=date(2025, 6, 30))
    issue_contract(contract=prev, actor=actor)
    new = renew_contract(
        contract=prev, start_date=date(2025, 7, 1), end_date=date(2025, 12, 31), actor=actor
    )
    prev.refresh_from_db()
    assert prev.status == EmploymentContract.Status.FINALIZADO
    assert new.status == EmploymentContract.Status.BORRADOR
    assert new.renews_id == prev.id
    assert new.contract_type == prev.contract_type


@pytest.mark.django_db
def test_renew_rejects_draft():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    prev = _draft(emp)  # BORRADOR
    with pytest.raises(ValueError) as exc:
        renew_contract(contract=prev, start_date=date(2025, 7, 1), actor=_mk_user())
    assert str(exc.value) == "CONTRACT_NOT_RENEWABLE"


@pytest.mark.django_db
def test_signatures_mark_fully_signed_only_with_both():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    actor = _mk_user()
    c = _draft(emp)
    issue_contract(contract=c, actor=actor)

    register_signature(
        contract=c, party_role=ContractSignature.PartyRole.EMPLEADOR, signer_name="Gerente", actor=actor
    )
    c.refresh_from_db()
    assert c.signed_employer_at is not None
    assert c.fully_signed_at is None  # solo una parte

    register_signature(
        contract=c, party_role=ContractSignature.PartyRole.TRABAJADOR, signer_name="Ana López", actor=actor
    )
    c.refresh_from_db()
    assert c.signed_employee_at is not None
    assert c.fully_signed_at is not None  # ambas partes
    assert c.signatures.count() == 2


@pytest.mark.django_db
def test_sign_requires_issued():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    c = _draft(emp)  # BORRADOR
    with pytest.raises(ValueError) as exc:
        register_signature(
            contract=c, party_role=ContractSignature.PartyRole.EMPLEADOR, signer_name="x", actor=_mk_user()
        )
    assert str(exc.value) == "CONTRACT_NOT_ISSUED"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "ctype,end",
    [
        (EmploymentContract.ContractType.PRUEBA, date(2025, 2, 1)),
        (EmploymentContract.ContractType.PARCIAL, None),
        (EmploymentContract.ContractType.APRENDIZAJE, date(2025, 6, 1)),
    ],
)
def test_new_contract_types_render_body(ctype, end):
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    c = _draft(emp, ctype, end_date=end)
    assert c.contract_type == ctype
    assert c.body.strip() != ""
    assert "CONTRATO INDIVIDUAL DE TRABAJO" in c.body


@pytest.mark.django_db
def test_expiring_contracts_window():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    actor = _mk_user()
    today = date.today()
    soon = _draft(emp, EmploymentContract.ContractType.PLAZO_FIJO, end_date=today + timedelta(days=10))
    far = _draft(emp, EmploymentContract.ContractType.PLAZO_FIJO, end_date=today + timedelta(days=200))
    issue_contract(contract=soon, actor=actor)
    issue_contract(contract=far, actor=actor)

    ids = {c.id for c in expiring_contracts(company=company, within_days=30)}
    assert soon.id in ids
    assert far.id not in ids
