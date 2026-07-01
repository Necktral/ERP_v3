"""Skills de Terceros (parties): clientes y proveedores."""
from __future__ import annotations

from apps.modulos.parties.models import Party, PartyRole

from . import skill


def _contar(company, role) -> int:
    return (
        Party.objects.filter(company=company, roles__role=role, roles__is_active=True)
        .distinct()
        .count()
    )


@skill(
    key="parties.clientes",
    description="Cuántos clientes hay registrados en la empresa.",
    required_permission="parties.party.read",
    keywords=("cuantos clientes", "numero de clientes", "total de clientes", "cantidad de clientes"),
    examples=("¿Cuántos clientes hay?",),
)
def clientes(*, request, args):
    company = request.company
    n = _contar(company, PartyRole.Role.CUSTOMER)
    answer = f"{company.name} tiene {n} cliente{'s' if n != 1 else ''} registrado{'s' if n != 1 else ''}."
    return {"answer": answer, "data": {"total": n, "empresa": company.name}}


@skill(
    key="parties.proveedores",
    description="Cuántos proveedores hay registrados en la empresa.",
    required_permission="parties.party.read",
    keywords=("cuantos proveedores", "numero de proveedores", "total de proveedores", "cantidad de proveedores"),
    examples=("¿Cuántos proveedores hay?",),
)
def proveedores(*, request, args):
    company = request.company
    n = _contar(company, PartyRole.Role.SUPPLIER)
    answer = f"{company.name} tiene {n} proveedor{'es' if n != 1 else ''} registrado{'s' if n != 1 else ''}."
    return {"answer": answer, "data": {"total": n, "empresa": company.name}}
