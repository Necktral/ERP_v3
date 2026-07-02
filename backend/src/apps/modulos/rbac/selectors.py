from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Q

if TYPE_CHECKING:
    from apps.modulos.iam.models import OrgUnit


def get_effective_permissions_for_scope(
    user, *, company: OrgUnit, branch: OrgUnit | None = None, include_global: bool = False
) -> set[str]:
    """
    Permisos efectivos para un usuario en un contexto (company + opcional branch).

    Reglas:
      - si hay RoleAssignment a COMPANY aplica a toda la empresa (todas sus branches)
      - si hay RoleAssignment a BRANCH aplica solo a esa branch
      - include_global=True conserva acceso explícito al catálogo UserRole legacy para auditoría/backoffice
    """

    from .models import RoleAssignment, RolePermission, UserRole

    role_ids: set[int] = set()

    # Scoped: company roles
    company_role_ids = RoleAssignment.objects.filter(
        user=user,
        is_active=True,
        org_unit=company,
    ).values_list("role_id", flat=True)
    role_ids.update(company_role_ids)

    # Scoped: branch roles (solo si branch existe)
    if branch is not None:
        branch_role_ids = RoleAssignment.objects.filter(
            user=user,
            is_active=True,
            org_unit=branch,
        ).values_list("role_id", flat=True)
        role_ids.update(branch_role_ids)

    # Legacy/global (transición)
    if include_global:
        global_role_ids = UserRole.objects.filter(user=user).values_list("role_id", flat=True)
        role_ids.update(global_role_ids)

    if not role_ids:
        return set()

    # RBAC-01: respetar el flag de activación del permiso (igual que get_effective_permissions);
    # un permiso desactivado globalmente NO debe seguir concediendo acceso en la ruta scoped.
    perm_codes = (
        RolePermission.objects.filter(role_id__in=list(role_ids), permission__is_active=True)
        .select_related("permission")
        .values_list("permission__code", flat=True)
    )
    return set(perm_codes)


def get_effective_permissions_for_scope_cached(
    *,
    request,
    user,
    company: OrgUnit,
    branch: OrgUnit | None = None,
    include_global: bool = False,
) -> set[str]:
    """
    Variante memoizada por-request de get_effective_permissions_for_scope.

    El memo vive en el HttpRequest crudo (muere con el request; cero estado
    cross-request), así la 2ª evaluación de permisos del mismo request no
    vuelve a consultar la BD. Con request=None degrada a la variante directa.
    """
    if request is None or user is None or getattr(user, "pk", None) is None:
        return get_effective_permissions_for_scope(
            user, company=company, branch=branch, include_global=include_global
        )

    raw = getattr(request, "_request", request)
    memo = getattr(raw, "_rbac_perms_memo", None)
    if memo is None:
        memo = {}
        try:
            raw._rbac_perms_memo = memo
        except (AttributeError, TypeError):
            return get_effective_permissions_for_scope(
                user, company=company, branch=branch, include_global=include_global
            )

    key = (
        user.pk,
        getattr(company, "id", None),
        getattr(branch, "id", None),
        bool(include_global),
    )
    if key not in memo:
        memo[key] = get_effective_permissions_for_scope(
            user, company=company, branch=branch, include_global=include_global
        )
    return memo[key]


def get_effective_permissions(user) -> list[str]:
    if user.is_superuser:
        return ["*"]

    from .models import Permission, RolePermission, UserRole

    role_ids = UserRole.objects.filter(user=user).values_list("role_id", flat=True)
    perm_ids = RolePermission.objects.filter(role_id__in=role_ids).values_list("permission_id", flat=True)

    perms = Permission.objects.filter(Q(id__in=perm_ids), is_active=True).values_list("code", flat=True)
    return sorted(set(perms))
