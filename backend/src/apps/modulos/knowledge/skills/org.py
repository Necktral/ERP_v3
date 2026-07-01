"""Skills de Organización: empresas, sucursales, usuarios."""
from __future__ import annotations

from apps.modulos.iam.models import OrgUnit, UserMembership

from . import skill

UT = OrgUnit.UnitType


@skill(
    key="org.empresas",
    description="Cuántas empresas (compañías) hay en el grupo/holding y cuáles son.",
    required_permission="org.company.read",
    keywords=("cuantas empresas", "numero de empresas", "total de empresas", "cuantas companias", "que empresas hay"),
    examples=("¿Cuántas empresas hay?", "Qué empresas tengo"),
)
def empresas(*, request, args):
    company = request.company
    holding = company.parent if company.parent_id and company.parent.unit_type == UT.HOLDING else None
    qs = OrgUnit.objects.filter(unit_type=UT.COMPANY, is_active=True)
    if holding is not None:
        qs = qs.filter(parent=holding)
    nombres = list(qs.order_by("name").values_list("name", flat=True))
    n = len(nombres)
    if n:
        answer = f"Hay {n} empresa{'s' if n != 1 else ''} en el grupo: {', '.join(nombres)}."
    else:
        answer = "No hay empresas registradas."
    return {"answer": answer, "data": {"total": n, "empresas": nombres}}


@skill(
    key="org.sucursales",
    description="Cuántas sucursales tiene la empresa actual y cuáles son.",
    required_permission="org.branch.read",
    keywords=("cuantas sucursales", "numero de sucursales", "total de sucursales", "que sucursales hay"),
    examples=("¿Cuántas sucursales hay?",),
)
def sucursales(*, request, args):
    company = request.company
    qs = OrgUnit.objects.filter(parent=company, unit_type=UT.BRANCH, is_active=True).order_by("name")
    nombres = list(qs.values_list("name", flat=True))
    n = len(nombres)
    if n:
        answer = f"{company.name} tiene {n} sucursal{'es' if n != 1 else ''}: {', '.join(nombres)}."
    else:
        answer = f"{company.name} no tiene sucursales registradas."
    return {"answer": answer, "data": {"total": n, "sucursales": nombres}}


@skill(
    key="org.usuarios",
    description="Cuántos usuarios activos tiene la empresa (personas con acceso al sistema).",
    required_permission="org.company.read",
    keywords=("cuantos usuarios", "numero de usuarios", "total de usuarios", "usuarios activos", "cuantas personas tienen acceso"),
    examples=("¿Cuántos usuarios hay?",),
)
def usuarios(*, request, args):
    company = request.company
    branch_ids = list(
        OrgUnit.objects.filter(parent=company, unit_type=UT.BRANCH).values_list("id", flat=True)
    )
    scope_ids = [company.id, *branch_ids]
    n = (
        UserMembership.objects.filter(org_unit_id__in=scope_ids, is_active=True)
        .values("user_id")
        .distinct()
        .count()
    )
    answer = f"{company.name} tiene {n} usuario{'s' if n != 1 else ''} activo{'s' if n != 1 else ''}."
    return {"answer": answer, "data": {"total": n, "empresa": company.name}}
