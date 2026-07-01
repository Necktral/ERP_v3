"""Planilla de complemento de salario (convenio personal, bruto en recibo).

Fija: la hoja siembra a los trabajadores con complemento habilitado tomando el monto base
del perfil; net = gross (sin retenciones); el monto es ajustable por periodo en DRAFT; SoD
(quien arma no aprueba); y el complemento NO crea PayrollEntry ni toca la base legal.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.nomina.complement_recibo import build_complement_recibo_html
from apps.kernels.nomina.models import (
    PayrollEntry,
    PayrollPeriod,
    PeriodType,
    SheetStatus,
)
from apps.kernels.nomina.services_complement import (
    approve_complement_sheet,
    complement_sheet_payload,
    create_complement_sheet,
    mark_complement_received,
    set_complement_line_amount,
    submit_complement_sheet,
)
from apps.modulos.hr.models import Employee
from apps.modulos.iam.models import OrgUnit

User = get_user_model()


def _scope():
    s = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H_{s}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name=f"C_{s}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, name=f"B_{s}", parent=company)
    return company, branch


def _actor(name="u"):
    t = uuid.uuid4().hex[:8]
    return User.objects.create_user(username=f"{name}_{t}", email=f"{name}_{t}@t.local", password="x")


def _req(company, branch, user):
    return SimpleNamespace(
        company=company, branch=branch, user=user,
        request_id="", headers={}, META={}, path="", method="POST",
    )


def _period(company):
    return PayrollPeriod.objects.create(
        company=company, year=2026, month=4, period_type=PeriodType.CATORCENA,
        start_date=date(2026, 4, 16), end_date=date(2026, 4, 30), working_days=15,
    )


def _emp(company, full_name, *, base="0.00", enabled=True):
    first, _, last = full_name.partition(" ")
    return Employee.objects.create(
        company=company, first_name=first, last_name=last,
        cedula=f"C{uuid.uuid4().hex[:10]}", salary_type="MONTHLY",
        monthly_salary_nio=Decimal("12000.00"),
        salary_complement_enabled=enabled, salary_complement_base_nio=Decimal(base),
    )


@pytest.mark.django_db
def test_create_sheet_snapshots_enabled_employees_with_base_amount():
    company, branch = _scope()
    actor = _actor()
    req = _req(company, branch, actor)
    _emp(company, "KEYLIN MARTINEZ", base="3409.20", enabled=True)
    _emp(company, "IVAN OROZCO", base="1600.00", enabled=True)
    _emp(company, "SIN COMPLEMENTO", base="0.00", enabled=False)  # no debe entrar

    sheet = create_complement_sheet(request=req, actor=actor, period=_period(company))
    payload = complement_sheet_payload(sheet)

    assert sheet.status == SheetStatus.DRAFT
    assert len(payload["lines"]) == 2  # solo los habilitados
    # net = gross en cada línea
    for ln in payload["lines"]:
        assert ln["devengado_nio"] == ln["neto_nio"]
    assert payload["subtotal_nio"] == "5009.20"
    # NO toca la planilla legal.
    assert PayrollEntry.objects.count() == 0


@pytest.mark.django_db
def test_amount_is_adjustable_per_period_in_draft():
    company, branch = _scope()
    actor = _actor()
    req = _req(company, branch, actor)
    _emp(company, "KAREN SUAZO", base="2000.00", enabled=True)
    sheet = create_complement_sheet(request=req, actor=actor, period=_period(company))
    line = sheet.lines.get()

    # Override por periodo.
    set_complement_line_amount(request=req, actor=actor, line=line, amount=Decimal("2500.00"))
    line.refresh_from_db()
    assert line.amount_nio == Decimal("2500.00")

    # Tras enviar, ya no se puede editar.
    submit_complement_sheet(request=req, actor=actor, sheet=sheet)
    with pytest.raises(ValueError, match="borrador"):
        set_complement_line_amount(request=req, actor=actor, line=line, amount=Decimal("3000.00"))


@pytest.mark.django_db
def test_sod_maker_cannot_approve():
    company, branch = _scope()
    maker = _actor("maker")
    checker = _actor("checker")
    req_maker = _req(company, branch, maker)
    req_checker = _req(company, branch, checker)
    _emp(company, "FELIX RUGAMA", base="1500.00", enabled=True)

    sheet = create_complement_sheet(request=req_maker, actor=maker, period=_period(company))
    submit_complement_sheet(request=req_maker, actor=maker, sheet=sheet)

    # Quien envía no puede aprobar.
    with pytest.raises(ValueError, match="segregación"):
        approve_complement_sheet(request=req_maker, actor=maker, sheet=sheet)

    # Otro usuario (checker) sí aprueba.
    sheet = approve_complement_sheet(request=req_checker, actor=checker, sheet=sheet)
    assert sheet.status == SheetStatus.APPROVED
    assert sheet.approved_by_id == checker.id


@pytest.mark.django_db
def test_received_only_after_approved_and_recibo_html():
    company, branch = _scope()
    maker = _actor("maker")
    checker = _actor("checker")
    req_m = _req(company, branch, maker)
    req_c = _req(company, branch, checker)
    _emp(company, "DAMARIS LOPEZ", base="3409.20", enabled=True)
    sheet = create_complement_sheet(request=req_m, actor=maker, period=_period(company))
    line = sheet.lines.get()

    # No se puede marcar recibido antes de aprobar.
    with pytest.raises(ValueError, match="aprobado"):
        mark_complement_received(request=req_m, actor=maker, line=line)

    submit_complement_sheet(request=req_m, actor=maker, sheet=sheet)
    approve_complement_sheet(request=req_c, actor=checker, sheet=sheet)
    mark_complement_received(request=req_c, actor=checker, line=line)
    line.refresh_from_db()
    assert line.received_at is not None

    # Recibo HTML calca el Excel: título, nombre, monto y subtotal.
    html = build_complement_recibo_html(sheet)
    assert "COMPLEMENTO DE SALARIO" in html
    assert "DAMARIS LOPEZ" in html
    assert "3,409.20" in html
    assert "RECIBIDO CONFORME" in html
