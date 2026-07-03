"""
Golden de equivalencia del cómputo de planilla (oleada 3).

El refactor de `compute_all_entries_in_sheet` (bulk_update en vez de un save()
por entrada) NO puede cambiar ni un centavo: aquí se computa la MISMA planilla
por los dos caminos — el masivo (sheet completa) y el individual (compute_entry
por entrada) — en dos empresas espejo, y se exige igualdad campo por campo en
TODOS los campos concretos del PayrollEntry. Invariante legal: el neto del
trabajador es inviolable.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.nomina.models import (
    PayrollEntry,
    PayrollPeriod,
    PayrollSheet,
    PeriodStatus,
    PeriodType,
    SalaryType,
)
from apps.kernels.nomina.services import (
    compute_all_entries_in_sheet,
    compute_entry,
    create_default_nicaragua_config,
)
from apps.modulos.hr.models import Employee
from apps.modulos.iam.models import OrgUnit

User = get_user_model()

# Campos que NO se comparan: identidad/relaciones/timestamps (sync_uid/origin_node
# son identidad Syncable por fila, distintos por definición).
CAMPOS_EXCLUIDOS = {"id", "sheet", "employee", "created_at", "updated_at", "sync_uid", "origin_node", "cedula"}

# Variedad de entradas: mensual con INSS, mensual sin INSS, jornalero, y USD.
PERFILES = [
    {"salary_type": SalaryType.MONTHLY, "base_salary_nio": "12000.00", "has_inss": True,
     "days_worked": "15.00"},
    {"salary_type": SalaryType.MONTHLY, "base_salary_nio": "8500.50", "has_inss": False,
     "days_worked": "13.00"},
    {"salary_type": SalaryType.DAILY, "base_salary_nio": "9000.00", "has_inss": True,
     "days_worked": "11.00"},
    {"salary_type": SalaryType.MONTHLY, "base_salary_nio": "0.00", "has_inss": True,
     "days_worked": "15.00", "base_salary_usd": "600.00", "exchange_rate": "36.62"},
]


def _mk_company():
    t = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H{t}")
    return OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name=f"C{t}", parent=holding)


def _mk_sheet(company, actor):
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, name=f"B{uuid.uuid4().hex[:4]}", parent=company)
    req = SimpleNamespace(user=actor, META={}, company=company, branch=None, _request=None,
                          ctx=None, request_id="r", path="", method="POST")
    create_default_nicaragua_config(request=req, actor=actor, company=company, fiscal_year=2026)
    period = PayrollPeriod.objects.create(
        company=company, year=2026, month=6, period_type=PeriodType.SECOND_HALF,
        start_date=date(2026, 6, 16), end_date=date(2026, 6, 30), working_days=15,
        status=PeriodStatus.APPROVED,
    )
    return PayrollSheet.objects.create(period=period, branch=branch, sheet_name="GOLDEN", has_inss=True)


def _poblar(sheet, company):
    entradas = []
    for i, perfil in enumerate(PERFILES):
        emp = Employee.objects.create(
            company=company, employee_code=f"G-{i}", first_name=f"Nom{i}", last_name="Golden",
            cedula=f"00{i}-GLD-{uuid.uuid4().hex[:4]}", inss_number=f"9{i}00", is_active=True,
        )
        extras = {}
        if "base_salary_usd" in perfil:
            extras["base_salary_usd"] = Decimal(perfil["base_salary_usd"])
        if "exchange_rate" in perfil:
            extras["exchange_rate"] = Decimal(perfil["exchange_rate"])
        entradas.append(PayrollEntry.objects.create(
            sheet=sheet, employee=emp,
            full_name=f"{emp.first_name} {emp.last_name}", cedula=emp.cedula,
            inss_number=emp.inss_number, has_inss=perfil["has_inss"],
            salary_type=perfil["salary_type"],
            base_salary_nio=Decimal(perfil["base_salary_nio"]),
            days_in_period=15, days_worked=Decimal(perfil["days_worked"]),
            **extras,
        ))
    return entradas


@pytest.mark.django_db
def test_equivalencia_computo_masivo_vs_individual_campo_por_campo():
    actor = User.objects.create_user(username=f"g_{uuid.uuid4().hex[:8]}", password="x")

    # Empresa A: cómputo MASIVO (el camino refactorizado).
    company_a = _mk_company()
    sheet_a = _mk_sheet(company_a, actor)
    _poblar(sheet_a, company_a)
    procesadas = compute_all_entries_in_sheet(sheet=sheet_a)
    assert procesadas == len(PERFILES)

    # Empresa B (espejo exacto): cómputo INDIVIDUAL entrada por entrada.
    company_b = _mk_company()
    sheet_b = _mk_sheet(company_b, actor)
    for entry in _poblar(sheet_b, company_b):
        compute_entry(entry=entry)

    filas_a = list(PayrollEntry.objects.filter(sheet=sheet_a).order_by("employee__employee_code"))
    filas_b = list(PayrollEntry.objects.filter(sheet=sheet_b).order_by("employee__employee_code"))
    assert len(filas_a) == len(filas_b) == len(PERFILES)

    campos = [
        f.name for f in PayrollEntry._meta.concrete_fields
        if f.name not in CAMPOS_EXCLUIDOS
    ]
    for a, b in zip(filas_a, filas_b):
        for campo in campos:
            va, vb = getattr(a, campo), getattr(b, campo)
            assert va == vb, f"{a.full_name}.{campo}: masivo={va!r} vs individual={vb!r}"

    # El neto persiste > 0 en los perfiles con salario (sanidad del invariante legal).
    assert all(f.net_to_pay > 0 for f in filas_a), [str(f.net_to_pay) for f in filas_a]


@pytest.mark.django_db
def test_computo_masivo_es_punto_fijo():
    """Recalcular la misma planilla dos veces no mueve ni un campo (idempotencia)."""
    actor = User.objects.create_user(username=f"g_{uuid.uuid4().hex[:8]}", password="x")
    company = _mk_company()
    sheet = _mk_sheet(company, actor)
    _poblar(sheet, company)

    compute_all_entries_in_sheet(sheet=sheet)
    antes = {
        e.pk: {f.name: getattr(e, f.name) for f in PayrollEntry._meta.concrete_fields
               if f.name not in CAMPOS_EXCLUIDOS}
        for e in PayrollEntry.objects.filter(sheet=sheet)
    }
    compute_all_entries_in_sheet(sheet=sheet)
    despues = {
        e.pk: {f.name: getattr(e, f.name) for f in PayrollEntry._meta.concrete_fields
               if f.name not in CAMPOS_EXCLUIDOS}
        for e in PayrollEntry.objects.filter(sheet=sheet)
    }
    assert antes == despues
