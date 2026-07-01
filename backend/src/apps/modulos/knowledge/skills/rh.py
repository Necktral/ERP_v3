"""Skills de Recursos Humanos: empleados, INSS, complemento."""
from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from apps.kernels.nomina.models import EmployeeInssEnrollment, InssRegime
from apps.modulos.hr.models import Employee

from . import skill


@skill(
    key="rh.empleados_total",
    description="Cuántos empleados (trabajadores) tiene la empresa, total y activos.",
    required_permission="hr.employee.read",
    keywords=(
        "cuantos empleados", "cuantos trabajadores", "numero de empleados", "total de empleados",
        "total de trabajadores", "cantidad de empleados", "cuanta gente trabaja",
    ),
    examples=("¿Cuántos empleados hay?", "Cuántos trabajadores tengo"),
)
def empleados_total(*, request, args):
    company = request.company
    qs = Employee.objects.filter(company=company)
    n = qs.count()
    activos = qs.filter(is_active=True).count()
    answer = (
        f"{company.name} tiene {n} empleado{'s' if n != 1 else ''} "
        f"({activos} activo{'s' if activos != 1 else ''})."
    )
    return {"answer": answer, "data": {"total": n, "activos": activos, "empresa": company.name}}


def _regime_by_employee(company, on_date):
    emp_ids = list(Employee.objects.filter(company=company, is_active=True).values_list("id", flat=True))
    regime: dict[int, str] = {}
    for emp_id, reg in (
        EmployeeInssEnrollment.objects.filter(employee_id__in=emp_ids, effective_from__lte=on_date)
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=on_date))
        .order_by("employee_id", "-effective_from")
        .values_list("employee_id", "regime")
    ):
        regime.setdefault(emp_id, reg)
    return emp_ids, regime


@skill(
    key="rh.empleados_inss",
    description="Cuántos empleados activos cotizan INSS y cuántos no cotizan.",
    required_permission="hr.employee.read",
    keywords=(
        "cuantos cotizan inss", "empleados con inss", "cuantos cotizan", "cuantos tienen inss",
        "empleados sin inss", "cuantos no cotizan",
    ),
    examples=("¿Cuántos empleados cotizan INSS?",),
)
def empleados_inss(*, request, args):
    company = request.company
    emp_ids, regime = _regime_by_employee(company, timezone.localdate())
    cotizan = sum(1 for eid in emp_ids if regime.get(eid, InssRegime.AFFILIATED) != InssRegime.NOT_AFFILIATED)
    no = len(emp_ids) - cotizan
    answer = (
        f"De {len(emp_ids)} empleado{'s' if len(emp_ids) != 1 else ''} activo{'s' if len(emp_ids) != 1 else ''} "
        f"en {company.name}, {cotizan} cotizan INSS y {no} no cotizan."
    )
    return {"answer": answer, "data": {"activos": len(emp_ids), "cotizan": cotizan, "no_cotizan": no}}


@skill(
    key="rh.empleados_complemento",
    description="Cuántos empleados tienen complemento de salario habilitado.",
    required_permission="hr.employee.read",
    keywords=("cuantos tienen complemento", "empleados con complemento", "cuantos complementos"),
    examples=("¿Cuántos empleados tienen complemento de salario?",),
)
def empleados_complemento(*, request, args):
    company = request.company
    n = Employee.objects.filter(company=company, is_active=True, salary_complement_enabled=True).count()
    answer = f"{n} empleado{'s' if n != 1 else ''} en {company.name} tiene{'n' if n != 1 else ''} complemento de salario habilitado."
    return {"answer": answer, "data": {"con_complemento": n, "empresa": company.name}}
