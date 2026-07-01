"""Invariantes de AISLAMIENTO INTERCOMPAÑÍA por grant IAM (QA negocio).

El aislamiento intercompañía NO va por `org.IntercompanyRelationship` (registro
liviano sin montos): va por `has_intercompany_grant` en
`apps.modulos.iam.selectors`, que exige un `CompanyLink` ACTIVO + un `LinkGrant`
activo con el permiso pedido y el modo correcto, y es DIRECCIONAL (un enlace
A→B no implica B→A).

Se atacan, a nivel SELECTOR y a nivel SERVICIO (`record_intercompany_charge`):
  - sin enlace/grant ⇒ bloqueado (fail-closed);
  - con enlace activo + grant correcto ⇒ permitido en ESA dirección;
  - direccionalidad: el grant inverso NO autoriza la operación;
  - enlace inactivo / grant inactivo / permiso equivocado / modo equivocado ⇒ bloqueado;
  - el servicio no deja estado parcial cuando la autorización falla.

Archivo NUEVO de QA: no edita producción ni tests existentes.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.accounting.models import ChartOfAccount, IntercompanyTransaction
from apps.kernels.portfolio.models import Payable, Receivable
from apps.modulos.iam.models import CompanyLink, LinkGrant, OrgUnit
from apps.modulos.iam.selectors import has_intercompany_grant
from apps.modulos.intercompany.services import record_intercompany_charge
from apps.modulos.rbac.models import Permission

User = get_user_model()
UT = OrgUnit.UnitType
IC_WRITE = "accounting.intercompany.write"


# --------------------------------------------------------------------------- #
# Helpers (espejan el patrón de tests vecinos de iam/intercompany)
# --------------------------------------------------------------------------- #

def _mk_orgs():
    s = uuid.uuid4().hex[:5]
    holding = OrgUnit.objects.create(unit_type=UT.HOLDING, name=f"H {s}")
    a = OrgUnit.objects.create(unit_type=UT.COMPANY, name=f"A {s}", parent=holding)
    a_br = OrgUnit.objects.create(unit_type=UT.BRANCH, name=f"A.HQ {s}", parent=a)
    b = OrgUnit.objects.create(unit_type=UT.COMPANY, name=f"B {s}", parent=holding)
    b_br = OrgUnit.objects.create(unit_type=UT.BRANCH, name=f"B.HQ {s}", parent=b)
    return holding, a, a_br, b, b_br


def _seed_coa(company: OrgUnit):
    rows = {
        "1301": ("CxC Intercompany", ChartOfAccount.AccountType.ASSET),
        "2109": ("CxP Intercompany", ChartOfAccount.AccountType.LIABILITY),
        "4101": ("Ingresos Intercompany", ChartOfAccount.AccountType.REVENUE),
        "5101": ("Gasto Intercompany", ChartOfAccount.AccountType.EXPENSE),
    }
    for code, (name, atype) in rows.items():
        ChartOfAccount.objects.create(
            company=company, code=code, name=name, account_type=atype, is_postable=True, is_active=True
        )


def _perm(code: str = IC_WRITE) -> Permission:
    perm, _ = Permission.objects.get_or_create(
        code=code, defaults={"description": code, "is_active": True}
    )
    return perm


def _grant(*, from_company, to_company, perm=None, mode="WRITE", link_active=True, grant_active=True):
    """Crea CompanyLink (dirección from→to) + LinkGrant company-wide."""
    perm = perm or _perm()
    link = CompanyLink.objects.create(
        from_company=from_company, to_company=to_company,
        status=CompanyLink.Status.ACTIVE if link_active else CompanyLink.Status.INACTIVE,
        is_active=link_active,
    )
    grant = LinkGrant.objects.create(
        link=link, permission=perm, access_mode=mode, scope_org_unit=None, is_active=grant_active,
    )
    return link, grant


def _user():
    t = uuid.uuid4().hex[:8]
    return User.objects.create_user(username=f"ic_{t}", email=f"ic_{t}@t.local", password="pass12345")


# ===========================================================================
# Nivel SELECTOR: has_intercompany_grant
# ===========================================================================

@pytest.mark.django_db
def test_selector_blocked_without_link_or_grant():
    """Sin CompanyLink/LinkGrant: fail-closed."""
    _h, a, _abr, b, _bbr = _mk_orgs()
    _perm()  # el permiso existe en catálogo, pero no hay enlace
    assert has_intercompany_grant(from_company=a, to_company=b, permission_code=IC_WRITE, mode="WRITE") is False


@pytest.mark.django_db
def test_selector_directional_grant_one_way_only():
    """DIRECCIONALIDAD: grant A→B autoriza A→B pero NUNCA B→A."""
    _h, a, _abr, b, _bbr = _mk_orgs()
    perm = _perm()
    _grant(from_company=a, to_company=b, perm=perm, mode="WRITE")

    # La dirección concedida (A→B) pasa.
    assert has_intercompany_grant(from_company=a, to_company=b, permission_code=IC_WRITE, mode="WRITE") is True
    # La inversa (B→A) NO: no se infiere reciprocidad.
    assert has_intercompany_grant(from_company=b, to_company=a, permission_code=IC_WRITE, mode="WRITE") is False


@pytest.mark.django_db
def test_selector_inactive_link_blocks():
    """CompanyLink inactivo (is_active=False / status≠ACTIVE) ⇒ bloqueado aunque el grant exista."""
    _h, a, _abr, b, _bbr = _mk_orgs()
    perm = _perm()
    _grant(from_company=a, to_company=b, perm=perm, mode="WRITE", link_active=False)
    assert has_intercompany_grant(from_company=a, to_company=b, permission_code=IC_WRITE, mode="WRITE") is False


@pytest.mark.django_db
def test_selector_inactive_grant_blocks():
    """LinkGrant inactivo ⇒ bloqueado aunque el enlace esté activo."""
    _h, a, _abr, b, _bbr = _mk_orgs()
    perm = _perm()
    _grant(from_company=a, to_company=b, perm=perm, mode="WRITE", grant_active=False)
    assert has_intercompany_grant(from_company=a, to_company=b, permission_code=IC_WRITE, mode="WRITE") is False


@pytest.mark.django_db
def test_selector_wrong_permission_code_blocks():
    """Un grant con OTRO permiso no satisface la consulta del permiso intercompany."""
    _h, a, _abr, b, _bbr = _mk_orgs()
    other = _perm(code=f"some.other.perm_{uuid.uuid4().hex[:6]}")
    _grant(from_company=a, to_company=b, perm=other, mode="WRITE")
    assert has_intercompany_grant(from_company=a, to_company=b, permission_code=IC_WRITE, mode="WRITE") is False


@pytest.mark.django_db
def test_selector_wrong_access_mode_blocks():
    """Un grant READ no autoriza una operación WRITE (modo direccional fino)."""
    _h, a, _abr, b, _bbr = _mk_orgs()
    perm = _perm()
    _grant(from_company=a, to_company=b, perm=perm, mode="READ")
    assert has_intercompany_grant(from_company=a, to_company=b, permission_code=IC_WRITE, mode="WRITE") is False
    # En modo READ sí pasa (es el modo concedido).
    assert has_intercompany_grant(from_company=a, to_company=b, permission_code=IC_WRITE, mode="READ") is True


# ===========================================================================
# Nivel SERVICIO: record_intercompany_charge (A cobra a B)
# ===========================================================================
# El servicio exige has_intercompany_grant(from_company=target=B, to_company=source=A,
# permission=IC_WRITE, mode=WRITE). Es decir, el PAGADOR (B) autoriza al COBRADOR (A):
# el grant debe ser el enlace B→A.

@pytest.mark.django_db
def test_service_authorized_with_payer_grant():
    """A cobra a B con grant B→A (el pagador autoriza): la operación completa pasa."""
    _h, a, _abr, b, _bbr = _mk_orgs()
    _seed_coa(a)
    _seed_coa(b)
    _grant(from_company=b, to_company=a, mode="WRITE")  # B autoriza a A
    user = _user()

    res = record_intercompany_charge(
        source_company_id=a.id, target_company_id=b.id, amount="1000.00",
        reference_code="ICISO-OK", concept="Servicio", effective_date=date(2026, 3, 1), actor=user,
    )
    assert res["status"] == IntercompanyTransaction.Status.CONFIRMED
    assert Receivable.objects.filter(company=a).count() == 1
    assert Payable.objects.filter(company=b).count() == 1


@pytest.mark.django_db
def test_service_directionality_reverse_grant_does_not_authorize():
    """DIRECCIONALIDAD a nivel servicio: un grant A→B NO autoriza que A cobre a B
    (la operación exige el enlace B→A). Bloqueado y sin estado parcial."""
    _h, a, _abr, b, _bbr = _mk_orgs()
    _seed_coa(a)
    _seed_coa(b)
    _grant(from_company=a, to_company=b, mode="WRITE")  # dirección INVERSA a la requerida
    user = _user()

    with pytest.raises(ValueError, match="INTERCOMPANY_NOT_AUTHORIZED"):
        record_intercompany_charge(
            source_company_id=a.id, target_company_id=b.id, amount="1000.00",
            reference_code="ICISO-REV", concept="Servicio", effective_date=date(2026, 3, 1), actor=user,
        )
    # Rollback total: ninguna pata quedó posteada.
    assert IntercompanyTransaction.objects.count() == 0
    assert Receivable.objects.count() == 0
    assert Payable.objects.count() == 0


@pytest.mark.django_db
def test_service_blocked_when_link_inactive():
    """Enlace correcto en dirección B→A pero inactivo ⇒ la operación se bloquea."""
    _h, a, _abr, b, _bbr = _mk_orgs()
    _seed_coa(a)
    _seed_coa(b)
    _grant(from_company=b, to_company=a, mode="WRITE", link_active=False)
    user = _user()

    with pytest.raises(ValueError, match="INTERCOMPANY_NOT_AUTHORIZED"):
        record_intercompany_charge(
            source_company_id=a.id, target_company_id=b.id, amount="500.00",
            reference_code="ICISO-INACT", effective_date=date(2026, 3, 1), actor=user,
        )
    assert IntercompanyTransaction.objects.count() == 0


@pytest.mark.django_db
def test_service_blocked_with_read_only_grant():
    """Grant en dirección correcta (B→A) pero modo READ ⇒ no autoriza el WRITE intercompany."""
    _h, a, _abr, b, _bbr = _mk_orgs()
    _seed_coa(a)
    _seed_coa(b)
    _grant(from_company=b, to_company=a, mode="READ")
    user = _user()

    with pytest.raises(ValueError, match="INTERCOMPANY_NOT_AUTHORIZED"):
        record_intercompany_charge(
            source_company_id=a.id, target_company_id=b.id, amount="500.00",
            reference_code="ICISO-READ", effective_date=date(2026, 3, 1), actor=user,
        )
    assert IntercompanyTransaction.objects.count() == 0
