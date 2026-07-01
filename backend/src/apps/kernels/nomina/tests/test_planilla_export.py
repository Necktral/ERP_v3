"""Tests del export de la planilla legal (.xlsx) — todas las casillas + agrupaciones + firmas."""
from __future__ import annotations

import io
import uuid
import zipfile
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.kernels.nomina.models import PayrollEntry, PayrollPeriod, PayrollSheet, PeriodType, SalaryType
from apps.kernels.nomina.planilla_export import build_planilla_matrix, render_planilla_xlsx
from apps.kernels.nomina.services import create_default_nicaragua_config
from apps.modulos.hr.models import Employee
from apps.modulos.iam.models import OrgUnit

User = get_user_model()


def _scope():
    tag = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name=f"H_{tag}")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name=f"C_{tag}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, name=f"B_{tag}", parent=company)
    return company, branch


def _actor():
    u = f"u_{uuid.uuid4().hex[:8]}"
    return User.objects.create_user(username=u, email=f"{u}@t.local", password="x")


def _req(actor, *, company=None):
    return SimpleNamespace(user=actor, META={}, company=company, branch=None, _request=None,
                           ctx=None, request_id="r", path="", method="POST")


def _sheet_with_entry(company, branch, actor):
    create_default_nicaragua_config(request=_req(actor, company=company), actor=actor, company=company, fiscal_year=2026)
    period = PayrollPeriod.objects.create(
        company=company, year=2026, month=6, period_type=PeriodType.CATORCENA,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 14), working_days=14,
    )
    sheet = PayrollSheet.objects.create(period=period, branch=branch, sheet_name="FINCA ABISINIA", has_inss=True)
    emp = Employee.objects.create(company=company, employee_code="E1", first_name="Juan", last_name="Pérez", is_active=True)
    entry = PayrollEntry.objects.create(
        sheet=sheet, employee=emp, full_name="Juan Pérez", inss_number="1234567",
        cedula="001-010190-0001A", cargo="Cortador", has_inss=True, salary_type=SalaryType.DAILY,
        base_salary_nio=Decimal("6000.00"), days_in_period=14, days_worked=Decimal("12.00"),
        # ALIMENTOS = alimentación de la empresa: SUMA al neto (beneficio).
        alimentacion_amount=Decimal("300.00"),
    )
    # Captura día-por-día (planilla fiel): 1–14 junio, presente salvo el 5 (ausente).
    from datetime import timedelta

    from apps.kernels.nomina.services import apply_daily_marks_to_entry

    marks, d = {}, period.start_date
    while d <= period.end_date:
        marks[d.isoformat()] = "A" if d.day == 5 else "P"
        d += timedelta(days=1)
    apply_daily_marks_to_entry(entry=entry, daily_attendance=marks)
    entry.save()
    return sheet, entry


@pytest.mark.django_db
def test_con_inss_matrix_layout_grid_and_alimentos():
    company, branch = _scope()
    actor = _actor()
    sheet, entry = _sheet_with_entry(company, branch, actor)
    data = build_planilla_matrix(sheet)
    labels = [c[1] for c in data["columns"]]
    keys = [c[0] for c in data["columns"]]
    # Layout FIEL CON INSS (sin No.INSS/Cédula; con Actividad + grilla + Alimentos + Total a Pagar)
    for lbl in (
        "No.", "Salario", "Nombres y Apellidos", "Género", "Salario Diario", "Actividad",
        "Suma Días", "Días Lab", "Salario Básico", "Sept Día", "TOTAL", "Vacaciones", "13vo Mes",
        "Total Ingresos", "INSS", "IR", "Total Devengado", "Alimentos", "Total a Pagar", "Recibe Conforme",
    ):
        assert lbl in labels, f"falta columna {lbl}"
    # NO lleva FINCA (es cobro interno del CO-PA) ni costos patronales en el documento.
    assert "FINCA" not in labels
    assert "COSTOS PATRONALES" not in [c[2] for c in data["columns"]]

    # Grilla de días: 14 columnas (1–14 junio), con las marcas capturadas.
    assert "day_2026-06-01" in keys
    assert "day_2026-06-14" in keys
    row = data["rows"][0]
    assert row["day_2026-06-05"] == "A"   # el 5 ausente
    assert row["day_2026-06-01"] == "P"

    # ALIMENTOS suma al neto: Total a Pagar = Total Devengado neto + Alimentos.
    assert row["alimentacion_amount"] == Decimal("300.00")
    assert row["neto_pagar"] == row["total_devengado_neto"] + Decimal("300.00")
    assert row["neto_pagar"] == entry.net_to_pay   # coincide con el neto legal del sistema
    # Los cobros internos NO son columnas del documento.
    assert "store_credit_deduction" not in row


def _sin_inss_sheet_with_entry(company, branch, actor):
    create_default_nicaragua_config(request=_req(actor, company=company), actor=actor, company=company, fiscal_year=2026)
    period = PayrollPeriod.objects.create(
        company=company, year=2026, month=6, period_type=PeriodType.CATORCENA,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 14), working_days=14,
    )
    sheet = PayrollSheet.objects.create(period=period, branch=branch, sheet_name="ADMON SIN INSS", has_inss=False)
    emp = Employee.objects.create(company=company, employee_code="E2", first_name="Ana", last_name="López", is_active=True)
    entry = PayrollEntry.objects.create(
        sheet=sheet, employee=emp, full_name="Ana López", cargo="Administradora", has_inss=False,
        salary_type=SalaryType.MONTHLY, base_salary_nio=Decimal("18000.00"), days_in_period=14,
        days_worked=Decimal("14.00"), alimentacion_amount=Decimal("250.00"),
    )
    from datetime import timedelta

    from apps.kernels.nomina.services import apply_daily_marks_to_entry

    marks, d = {}, period.start_date
    while d <= period.end_date:
        marks[d.isoformat()] = "P"
        d += timedelta(days=1)
    apply_daily_marks_to_entry(entry=entry, daily_attendance=marks)
    entry.save()
    return sheet, entry


@pytest.mark.django_db
def test_sin_inss_matrix_layout_fiel():
    company, branch = _scope()
    actor = _actor()
    sheet, entry = _sin_inss_sheet_with_entry(company, branch, actor)
    data = build_planilla_matrix(sheet)
    labels = [c[1] for c in data["columns"]]
    keys = [c[0] for c in data["columns"]]
    # Layout FIEL SIN INSS: simple, SIN grilla, SIN INSS/IR/patronal/Cédula; con Alimentación.
    for lbl in (
        "No.", "Nombres y Apellidos", "Género", "Cargo", "Salario Diario", "Salario Mensual",
        "Salario Quincenal", "Días Laborados", "Total Básico", "Vacaciones", "13vo Mes",
        "Total Ingresos", "Alimentación", "Total a Pagar", "Recibí Conforme",
    ):
        assert lbl in labels, f"falta columna {lbl}"
    assert "INSS" not in labels and "IR" not in labels       # SIN INSS oculta las retenciones (son 0)
    assert "No. INSS" not in labels and "Cédula" not in labels
    assert "COSTOS PATRONALES" not in [c[2] for c in data["columns"]]
    assert not any(k.startswith("day_") for k in keys)        # la SIN INSS no lleva grilla de días
    # ALIMENTACIÓN suma al neto: Total a Pagar == net_to_pay legal del sistema.
    row = data["rows"][0]
    assert row["alimentacion_amount"] == Decimal("250.00")
    assert row["neto_pagar"] == entry.net_to_pay


@pytest.mark.django_db
def test_con_inss_xlsx_is_valid_and_has_fiel_casillas():
    company, branch = _scope()
    actor = _actor()
    sheet, entry = _sheet_with_entry(company, branch, actor)
    content = render_planilla_xlsx(sheet)

    z = zipfile.ZipFile(io.BytesIO(content))
    for part in ("[Content_Types].xml", "xl/workbook.xml", "xl/worksheets/sheet1.xml"):
        assert part in z.namelist()
    xml = z.read("xl/worksheets/sheet1.xml").decode("utf-8")

    for label in (
        "Salario", "Nombres y Apellidos", "Actividad", "Suma Días", "Salario Básico",
        "Sept Día", "Total Ingresos", "INSS", "IR", "Total Devengado", "Alimentos",
        "Total a Pagar", "Recibe Conforme", "ASISTENCIA", "INGRESOS", "RETENCIONES",
        "ELABORADO", "REVISADO", "AUTORIZADO", "TOTALES",
    ):
        assert label in xml, f"falta casilla/etiqueta: {label}"
    assert "Juan Pérez" in xml
    # El documento legal NO muestra cobros internos (comisariato/préstamo) — eso vive en el CO-PA.
    for prohibido in ("Crédito Comisariato", "Abono Préstamos", "Adelanto Finca"):
        assert prohibido not in xml, f"el documento NO debe mostrar: {prohibido}"
    assert "<mergeCell" in xml
