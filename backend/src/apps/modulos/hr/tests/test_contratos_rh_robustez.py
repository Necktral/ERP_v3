"""ROBUSTEZ de contratos y RH (firmas, renovaciones, vacaciones 2.5 d/mes NIC).

Catálogo de ataque (no el camino feliz; eso lo cubre test_contracts_advanced /
test_vacaciones):
- FIRMAS: fully_signed solo con ambas partes; firmar dos veces la MISMA parte es
  idempotente (update_or_create, no crea una segunda firma ni reabre el contrato);
  party_role / method basura → ValueError tipado, no 500; firmar BORRADOR → rechazo.
- RENOVACIÓN encadenada: renovar un EMITIDO finaliza el previo y crea borrador
  encadenado SIN borrar el previo; renovar dos veces no rompe la cadena.
- VACACIONES: acumulación 2.5 d/mes idempotente por (empleado, año, mes); días
  hábiles excluyen domingo y feriado; no se puede tomar más de lo acumulado;
  rango invertido / días=0 / empleado de otra empresa → VacationError tipado.

ENTRADA BASURA: tipos/valores fuera de dominio → excepción tipada de negocio.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.modulos.hr.models import (
    ContractSignature,
    Employee,
    EmploymentContract,
    VacationLedgerEntry,
)
from apps.modulos.hr.services import create_contract_draft, issue_contract
from apps.modulos.hr.services_contracts import register_signature, renew_contract
from apps.modulos.hr.services_vacaciones import (
    VacationError,
    accrue_vacation_month,
    adjust_balance,
    register_vacation,
    vacation_balance,
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


def _mk_employee(company, **kw):
    return Employee.objects.create(company=company, first_name="Ana", last_name="López", **kw)


def _draft(emp, ctype=EmploymentContract.ContractType.INDEFINIDO, **kw):
    return create_contract_draft(
        employee=emp,
        contract_type=ctype,
        start_date=kw.get("start_date", date(2025, 1, 1)),
        end_date=kw.get("end_date"),
        salary_amount=kw.get("salary_amount", Decimal("12000.00")),
        actor=kw.get("actor"),
    )


# --------------------------------------------------------------------------- #
# FIRMAS
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_firmar_misma_parte_dos_veces_es_idempotente():
    """Re-registrar la firma del empleador (reintento) NO crea una segunda firma ni
    reabre el contrato; actualiza la existente. fully_signed sigue dependiendo de AMBAS."""
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    actor = _mk_user()
    c = _draft(emp)
    issue_contract(contract=c, actor=actor)

    register_signature(contract=c, party_role=ContractSignature.PartyRole.EMPLEADOR, signer_name="Gerente", actor=actor)
    register_signature(contract=c, party_role=ContractSignature.PartyRole.EMPLEADOR, signer_name="Gerente (re)", actor=actor)
    c.refresh_from_db()
    assert c.signatures.filter(party_role=ContractSignature.PartyRole.EMPLEADOR).count() == 1  # no duplica
    assert c.fully_signed_at is None  # sigue faltando el trabajador


@pytest.mark.django_db
def test_fully_signed_solo_con_ambas_partes_y_no_se_mueve_al_refirmar():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    actor = _mk_user()
    c = _draft(emp)
    issue_contract(contract=c, actor=actor)
    register_signature(contract=c, party_role=ContractSignature.PartyRole.EMPLEADOR, signer_name="Gerente", actor=actor)
    register_signature(contract=c, party_role=ContractSignature.PartyRole.TRABAJADOR, signer_name="Ana", actor=actor)
    c.refresh_from_db()
    assert c.fully_signed_at is not None
    sealed_at = c.fully_signed_at
    # Re-firmar una parte NO debe mover el sello de fully_signed.
    register_signature(contract=c, party_role=ContractSignature.PartyRole.TRABAJADOR, signer_name="Ana (re)", actor=actor)
    c.refresh_from_db()
    assert c.fully_signed_at == sealed_at


@pytest.mark.django_db
def test_party_role_basura_es_rechazado():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    actor = _mk_user()
    c = _draft(emp)
    issue_contract(contract=c, actor=actor)
    with pytest.raises(ValueError) as exc:
        register_signature(contract=c, party_role="EXTRATERRESTRE", signer_name="x", actor=actor)
    assert str(exc.value) == "INVALID_PARTY_ROLE"


@pytest.mark.django_db
def test_metodo_de_firma_basura_es_rechazado():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    actor = _mk_user()
    c = _draft(emp)
    issue_contract(contract=c, actor=actor)
    with pytest.raises(ValueError) as exc:
        register_signature(
            contract=c, party_role=ContractSignature.PartyRole.EMPLEADOR,
            signer_name="x", method="HUELLA_GENETICA", actor=actor,
        )
    assert str(exc.value) == "INVALID_SIGNATURE_METHOD"


@pytest.mark.django_db
def test_firmar_sin_nombre_es_rechazado():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    actor = _mk_user()
    c = _draft(emp)
    issue_contract(contract=c, actor=actor)
    with pytest.raises(ValueError) as exc:
        register_signature(contract=c, party_role=ContractSignature.PartyRole.EMPLEADOR, signer_name="   ", actor=actor)
    assert str(exc.value) == "SIGNER_NAME_REQUIRED"


@pytest.mark.django_db
def test_firmar_borrador_es_rechazado():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    c = _draft(emp)  # BORRADOR, no emitido
    with pytest.raises(ValueError) as exc:
        register_signature(contract=c, party_role=ContractSignature.PartyRole.EMPLEADOR, signer_name="x", actor=_mk_user())
    assert str(exc.value) == "CONTRACT_NOT_ISSUED"


# --------------------------------------------------------------------------- #
# RENOVACIÓN ENCADENADA
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_renovar_no_borra_el_previo_y_encadena():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    actor = _mk_user()
    prev = _draft(emp, EmploymentContract.ContractType.PLAZO_FIJO, end_date=date(2025, 6, 30))
    issue_contract(contract=prev, actor=actor)
    new = renew_contract(contract=prev, start_date=date(2025, 7, 1), end_date=date(2025, 12, 31), actor=actor)
    # El previo SIGUE existiendo (finalizado), no se borra; el nuevo lo encadena.
    assert EmploymentContract.objects.filter(pk=prev.pk).exists()
    prev.refresh_from_db()
    assert prev.status == EmploymentContract.Status.FINALIZADO
    assert new.renews_id == prev.id
    assert new.status == EmploymentContract.Status.BORRADOR


@pytest.mark.django_db
def test_renovar_dos_veces_encadena_sin_romper():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    actor = _mk_user()
    c1 = _draft(emp, EmploymentContract.ContractType.PLAZO_FIJO, end_date=date(2025, 6, 30))
    issue_contract(contract=c1, actor=actor)
    c2 = renew_contract(contract=c1, start_date=date(2025, 7, 1), end_date=date(2025, 12, 31), actor=actor)
    issue_contract(contract=c2, actor=actor)
    c3 = renew_contract(contract=c2, start_date=date(2026, 1, 1), end_date=date(2026, 6, 30), actor=actor)
    assert c3.renews_id == c2.id
    c2.refresh_from_db()
    assert c2.renews_id == c1.id
    assert c2.status == EmploymentContract.Status.FINALIZADO
    # Cadena intacta: los tres existen.
    assert EmploymentContract.objects.filter(pk__in=[c1.pk, c2.pk, c3.pk]).count() == 3


@pytest.mark.django_db
def test_renovar_borrador_es_rechazado():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    prev = _draft(emp)  # BORRADOR
    with pytest.raises(ValueError) as exc:
        renew_contract(contract=prev, start_date=date(2025, 7, 1), actor=_mk_user())
    assert str(exc.value) == "CONTRACT_NOT_RENEWABLE"


# --------------------------------------------------------------------------- #
# VACACIONES (2.5 d/mes, días hábiles, no sobre-girar)
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_acumulacion_2_5_idempotente_y_no_duplica_ledger():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    actor = _mk_user()
    assert accrue_vacation_month(company=company, year=2025, month=1, actor=actor) == 1
    assert accrue_vacation_month(company=company, year=2025, month=1, actor=actor) == 0  # idempotente
    assert vacation_balance(emp) == Decimal("2.50")
    # Un solo asiento ACCRUAL para ese (empleado, año, mes).
    assert VacationLedgerEntry.objects.filter(
        employee=emp, entry_type=VacationLedgerEntry.EntryType.ACCRUAL, accrual_year=2025, accrual_month=1
    ).count() == 1


@pytest.mark.django_db
def test_no_se_puede_tomar_mas_de_lo_acumulado():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    actor = _mk_user()
    # Solo 2.5 acumulados; pedir una semana (6 hábiles) debe rechazarse.
    accrue_vacation_month(company=company, year=2025, month=1, actor=actor)
    with pytest.raises(VacationError) as exc:
        register_vacation(
            company=company, employee_id=emp.id,
            start_date=date(2025, 6, 9), end_date=date(2025, 6, 15), actor=actor,
        )
    assert exc.value.code == "HR_VACATION_INSUFFICIENT_BALANCE"
    assert vacation_balance(emp) == Decimal("2.50")  # saldo intacto


@pytest.mark.django_db
def test_rango_invertido_es_rechazado():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    actor = _mk_user()
    adjust_balance(company=company, employee_id=emp.id, days=Decimal("30"), reason="inicial", actor=actor)
    with pytest.raises(VacationError) as exc:
        register_vacation(
            company=company, employee_id=emp.id,
            start_date=date(2025, 6, 15), end_date=date(2025, 6, 9), actor=actor,
        )
    assert exc.value.code == "INVALID_DATE_RANGE"


@pytest.mark.django_db
def test_rango_de_solo_domingo_da_cero_dias_habiles():
    """Un rango que cae solo en domingo no tiene días hábiles → rechazo (no descuenta 0
    silencioso, no revienta)."""
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    actor = _mk_user()
    adjust_balance(company=company, employee_id=emp.id, days=Decimal("30"), reason="inicial", actor=actor)
    # 2025-06-15 es domingo.
    with pytest.raises(VacationError) as exc:
        register_vacation(
            company=company, employee_id=emp.id,
            start_date=date(2025, 6, 15), end_date=date(2025, 6, 15), actor=actor,
        )
    assert exc.value.code == "ZERO_BUSINESS_DAYS"


@pytest.mark.django_db
def test_vacaciones_de_empleado_de_otra_empresa_rechazado():
    _, c1, _ = _mk_org()
    _, c2, _ = _mk_org()
    emp2 = _mk_employee(c2)
    adjust_balance(company=c2, employee_id=emp2.id, days=Decimal("30"), reason="x", actor=_mk_user())
    with pytest.raises(VacationError) as exc:
        register_vacation(
            company=c1, employee_id=emp2.id,
            start_date=date(2025, 6, 9), end_date=date(2025, 6, 10), actor=_mk_user(),
        )
    assert exc.value.code == "EMPLOYEE_NOT_FOUND"


@pytest.mark.django_db
def test_ajuste_cero_es_rechazado():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    with pytest.raises(VacationError) as exc:
        adjust_balance(company=company, employee_id=emp.id, days=Decimal("0"), reason="x", actor=_mk_user())
    assert exc.value.code == "ADJUSTMENT_ZERO"


@pytest.mark.django_db
def test_acumulacion_no_toca_empleado_inactivo():
    """La acumulación es solo para ACTIVO: un empleado dado de baja no acumula."""
    _, company, _ = _mk_org()
    activo = _mk_employee(company)
    inactivo = _mk_employee(
        company, is_active=False, employment_status=Employee.EmploymentStatus.BAJA
    )
    actor = _mk_user()
    created = accrue_vacation_month(company=company, year=2025, month=1, actor=actor)
    assert created == 1  # solo el activo
    assert vacation_balance(activo) == Decimal("2.50")
    assert vacation_balance(inactivo) == Decimal("0.00")
