from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modulos.audit.writer import write_event
from apps.modulos.common.pagination import get_limit_offset, paginate_list, paginate_queryset
from apps.modulos.common.permissions import rbac_permission
from apps.modulos.common.throttling import MethodThrottleScopeMixin
from apps.modulos.iam.models import AdminGrant, OrgUnit, UserMembership
from apps.modulos.iam.selectors import get_accessible_companies
from apps.modulos.rbac.models import RoleAssignment

from .branding import parse_logo_data_url
from .models import BranchProfile, CompanyProfile, IntercompanyRelationship, OrgBranding
from .module_catalog import get_catalog
from .serializers import (
    BranchCreateSerializer,
    BranchUpdateSerializer,
    CompanyCreateSerializer,
    CompanyProfileUpdateSerializer,
    IntercompanyRelationshipIn,
    IntercompanyRelationshipUpdateIn,
    ModulesUpdateIn,
    ModuleStateOut,
    OrgBrandingUpdateIn,
)
from .services_modules import (
    ModuleDependencyError,
    resolve_company_modules,
    set_company_modules,
)


class CompanyListCreateView(MethodThrottleScopeMixin, APIView):
    """
    Holding → Companies (multi-company).
    Permisos por método:
      - GET  -> org.company.read
      - POST -> org.company.create
    """

    throttle_scope_by_method = {
        "GET": "heavy_reads",
        "POST": "admin_writes",
    }

    def get_permissions(self):
        if self.request.method == "GET":
            return [rbac_permission("org.company.read")()]
        if self.request.method == "POST":
            return [rbac_permission("org.company.create")()]
        return [rbac_permission("org.company.read")()]

    def get(self, request):
        companies = get_accessible_companies(request.user)
        limit, offset = get_limit_offset(request)
        total, rows = paginate_list(companies, limit=limit, offset=offset)
        out = []
        for c in rows:
            prof = getattr(c, "company_profile", None)
            out.append(
                {
                    "id": c.id,
                    "name": c.name,
                    "code": c.code,
                    "is_active": c.is_active,
                    "legal_name": getattr(prof, "legal_name", ""),
                    "tax_id": getattr(prof, "tax_id", ""),
                }
            )
        return Response(
            {"count": total, "limit": limit, "offset": offset, "results": out},
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        with transaction.atomic():
            current_company: OrgUnit | None = getattr(request, "company", None)

            holding: OrgUnit | None = None
            if current_company and current_company.unit_type == OrgUnit.UnitType.HOLDING:
                holding = current_company
            elif current_company and current_company.parent and current_company.parent.unit_type == OrgUnit.UnitType.HOLDING:
                holding = current_company.parent
            else:
                holding = OrgUnit.objects.filter(unit_type=OrgUnit.UnitType.HOLDING).order_by("id").first()

            if not holding:
                return Response({"detail": "No existe holding. Ejecuta bootstrap primero."}, status=status.HTTP_400_BAD_REQUEST)

            serializer = CompanyCreateSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            v = serializer.validated_data

            # Dedupe por name dentro del holding (robusto)
            if OrgUnit.objects.filter(parent=holding, unit_type=OrgUnit.UnitType.COMPANY, name=v["name"]).exists():
                return Response(
                    {"name": "Ya existe una compañía con ese nombre en el holding"},
                    status=status.HTTP_409_CONFLICT,
                )

            new_company = OrgUnit.objects.create(
                unit_type=OrgUnit.UnitType.COMPANY,
                parent=holding,
                name=v["name"],
                code=v.get("code", ""),
                is_active=True,
            )
            CompanyProfile.objects.create(
                company=new_company,
                legal_name=v.get("legal_name", "") or v["name"],
                tax_id=v.get("tax_id", ""),
                address=v.get("address", ""),
                phone=v.get("phone", ""),
                email=v.get("email", ""),
            )

            # Dar acceso inmediato al creador (para selector/ACL)
            membership, _created = UserMembership.objects.get_or_create(
                user=request.user,
                org_unit=new_company,
                defaults={"is_active": True},
            )
            if not membership.is_active:
                membership.is_active = True
                membership.left_at = None
                membership.save()

            # Clonar roles del creador desde su compañía actual
            if current_company and current_company.unit_type == OrgUnit.UnitType.COMPANY:
                roles_to_clone = RoleAssignment.objects.filter(
                    user=request.user,
                    org_unit=current_company,
                    is_active=True,
                )
                for ra in roles_to_clone:
                    cloned_ra, _ = RoleAssignment.objects.get_or_create(
                        user=request.user,
                        role=ra.role,
                        org_unit=new_company,
                        defaults={
                            "is_active": True,
                            "granted_by": request.user,
                            "origin_ref": "org.company.create.clone",
                        },
                    )
                    if not cloned_ra.is_active:
                        cloned_ra.is_active = True
                        cloned_ra.granted_by = request.user
                        cloned_ra.origin_ref = "org.company.create.clone"
                        cloned_ra.save()

                grants_to_clone = AdminGrant.objects.filter(
                    user=request.user,
                    org_unit=current_company,
                    is_active=True,
                )
                for g in grants_to_clone:
                    cloned_g, _ = AdminGrant.objects.get_or_create(
                        user=request.user,
                        org_unit=new_company,
                        capability=g.capability,
                        defaults={
                            "is_active": True,
                            "applies_to_subtree": g.applies_to_subtree,
                            "granted_by": request.user,
                        },
                    )
                    if not cloned_g.is_active:
                        cloned_g.is_active = True
                        cloned_g.applies_to_subtree = g.applies_to_subtree
                        cloned_g.granted_by = request.user
                        cloned_g.save()

            write_event(
                request=request,
                module="ORG",
                event_type="ORG_COMPANY_CREATED",
                reason_code="OK",
                actor_user=request.user,
                subject_type="COMPANY",
                subject_id=str(new_company.id),
                metadata={"company_name": new_company.name, "holding_id": str(holding.id)},
            )
            return Response({"id": new_company.id}, status=status.HTTP_201_CREATED)


class BranchListCreateView(MethodThrottleScopeMixin, APIView):
    """
    Permisos por método (robusto):
      - GET  -> org.branch.read
      - POST -> org.branch.create
    """

    throttle_scope_by_method = {
        "GET": "heavy_reads",
        "POST": "admin_writes",
    }

    def get_permissions(self):
        if self.request.method == "GET":
            return [rbac_permission("org.branch.read")()]
        if self.request.method == "POST":
            return [rbac_permission("org.branch.create")()]
        # Fallback seguro: negar por defecto a quien no tenga al menos read
        return [rbac_permission("org.branch.read")()]

    def get(self, request):
        company: OrgUnit = request.company
        qs = OrgUnit.objects.filter(parent=company, unit_type=OrgUnit.UnitType.BRANCH).order_by("name")
        limit, offset = get_limit_offset(request)
        total, rows = paginate_queryset(qs, limit=limit, offset=offset)
        data = []
        for b in rows:
            prof = getattr(b, "branch_profile", None)
            data.append(
                {
                    "id": b.id,
                    "name": b.name,
                    "code": b.code,
                    "is_active": b.is_active,
                    "address": getattr(prof, "address", ""),
                    "phone": getattr(prof, "phone", ""),
                    "email": getattr(prof, "email", ""),
                }
            )
        return Response(
            {"count": total, "limit": limit, "offset": offset, "results": data},
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        company: OrgUnit = request.company
        serializer = BranchCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        v = serializer.validated_data
        branch = OrgUnit.objects.create(
            unit_type=OrgUnit.UnitType.BRANCH,
            parent=company,
            name=v["name"],
            code=v.get("code", ""),
            is_active=True,
        )
        BranchProfile.objects.create(
            branch=branch,
            address=v.get("address", ""),
            phone=v.get("phone", ""),
            email=v.get("email", ""),
        )

        write_event(
            request=request,
            module="ORG",
            event_type="ORG_BRANCH_CREATED",
            reason_code="OK",
            actor_user=request.user,
            subject_type="BRANCH",
            subject_id=str(branch.id),
            metadata={"branch_name": branch.name},
        )
        return Response({"id": branch.id}, status=status.HTTP_201_CREATED)


class BranchDetailView(APIView):
    permission_classes = [rbac_permission("org.branch.update")]
    throttle_scope = "admin_writes"

    def patch(self, request, branch_id: int):
        company: OrgUnit = request.company
        branch = get_object_or_404(OrgUnit, id=branch_id, parent=company, unit_type=OrgUnit.UnitType.BRANCH)
        before = {"name": branch.name, "code": branch.code, "is_active": branch.is_active}
        serializer = BranchUpdateSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        v = serializer.validated_data
        changed = False
        if "name" in v:
            branch.name = v["name"]
            changed = True
        if "code" in v:
            branch.code = v["code"]
            changed = True
        if "is_active" in v:
            branch.is_active = bool(v["is_active"])
            changed = True
        if changed:
            branch.save()
        prof, _ = BranchProfile.objects.get_or_create(branch=branch)
        prof_changed = False
        for f in ["address", "phone", "email"]:
            if f in v:
                setattr(prof, f, v[f])
                prof_changed = True
        if prof_changed:
            prof.save()
        after = {"name": branch.name, "code": branch.code, "is_active": branch.is_active}
        write_event(
            request=request,
            module="ORG",
            event_type="ORG_BRANCH_UPDATED",
            reason_code="OK",
            actor_user=request.user,
            subject_type="BRANCH",
            subject_id=str(branch.id),
            before_snapshot=before,
            after_snapshot=after,
        )
        return Response({"ok": True}, status=status.HTTP_200_OK)


class CompanyProfileView(MethodThrottleScopeMixin, APIView):
    throttle_scope_by_method = {
        "GET": "heavy_reads",
        "PUT": "admin_writes",
    }
    def get_permissions(self):
        # Separar ver vs editar
        if self.request.method == "GET":
            return [rbac_permission("org.company.read")()]
        if self.request.method == "PUT":
            return [rbac_permission("org.company.update")()]
        return [rbac_permission("org.company.read")()]

    def get(self, request):
        company: OrgUnit = request.company
        prof, _ = CompanyProfile.objects.get_or_create(company=company)
        return Response(
            {
                "legal_name": prof.legal_name,
                "tax_id": prof.tax_id,
                "address": prof.address,
                "phone": prof.phone,
                "email": prof.email,
            },
            status=status.HTTP_200_OK,
        )

    def put(self, request):
        company: OrgUnit = request.company
        prof, _ = CompanyProfile.objects.get_or_create(company=company)
        serializer = CompanyProfileUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        before = {
            "legal_name": prof.legal_name,
            "tax_id": prof.tax_id,
            "address": prof.address,
            "phone": prof.phone,
            "email": prof.email,
        }
        v = serializer.validated_data
        for f in ["legal_name", "tax_id", "address", "phone", "email"]:
            if f in v:
                setattr(prof, f, v[f])
        prof.save()
        after = {
            "legal_name": prof.legal_name,
            "tax_id": prof.tax_id,
            "address": prof.address,
            "phone": prof.phone,
            "email": prof.email,
        }
        write_event(
            request=request,
            module="ORG",
            event_type="ORG_COMPANY_PROFILE_UPDATED",
            reason_code="OK",
            actor_user=request.user,
            subject_type="COMPANY",
            subject_id=str(company.id),
            before_snapshot=before,
            after_snapshot=after,
        )
        return Response({"ok": True}, status=status.HTTP_200_OK)


def _branding_dict(b: OrgBranding | None) -> dict | None:
    if b is None:
        return None
    return {
        "display_name": b.display_name,
        "tagline": b.tagline,
        "logo_data_url": b.logo_data_url,
        "logo_mime": b.logo_mime,
    }


class OrgBrandingView(MethodThrottleScopeMixin, APIView):
    """Marca (nombre + logo) del holding y/o de la empresa activa.

    GET  -> { holding, company } del contexto activo (cada uno o null).
    PUT  -> upsert del branding del nivel pedido (``level``: holding|company).
    El logo viaja como data-URL base64 (offline-first; ver `org/branding.py`).
    """

    throttle_scope_by_method = {"GET": "heavy_reads", "PUT": "admin_writes"}

    def get_permissions(self):
        if self.request.method == "PUT":
            return [rbac_permission("org.company.update")()]
        return [rbac_permission("org.company.read")()]

    @staticmethod
    def _holding_for(company: OrgUnit) -> OrgUnit | None:
        if company.unit_type == OrgUnit.UnitType.HOLDING:
            return company
        return company.parent if company.parent_id else None

    def get(self, request):
        company: OrgUnit = request.company
        holding = self._holding_for(company)
        company_branding = (
            OrgBranding.objects.filter(org_unit=company).first()
            if company.unit_type == OrgUnit.UnitType.COMPANY
            else None
        )
        holding_branding = (
            OrgBranding.objects.filter(org_unit=holding).first() if holding is not None else None
        )
        return Response(
            {"holding": _branding_dict(holding_branding), "company": _branding_dict(company_branding)},
            status=status.HTTP_200_OK,
        )

    def put(self, request):
        company: OrgUnit = request.company
        serializer = OrgBrandingUpdateIn(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        v = serializer.validated_data

        if v["level"] == "holding":
            target = self._holding_for(company)
            if target is None:
                return Response(
                    {"detail": "No hay un holding para el contexto activo."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            target = company
            if target.unit_type != OrgUnit.UnitType.COMPANY:
                return Response(
                    {"detail": "El contexto activo no es una empresa."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        prof, _ = OrgBranding.objects.get_or_create(org_unit=target)
        before = _branding_dict(prof)
        for f in ["display_name", "tagline", "logo_data_url"]:
            if f in v:
                setattr(prof, f, v[f])
        # `logo_mime` se deriva del data-URL (ya validado por el serializer).
        prof.logo_mime, _bytes = parse_logo_data_url(prof.logo_data_url)
        prof.save()

        write_event(
            request=request,
            module="ORG",
            event_type="ORG_BRANDING_UPDATED",
            reason_code="OK",
            actor_user=request.user,
            subject_type="HOLDING" if v["level"] == "holding" else "COMPANY",
            subject_id=str(target.id),
            before_snapshot=before,
            after_snapshot=_branding_dict(prof),
        )
        return Response({"ok": True}, status=status.HTTP_200_OK)


class CompanyModulesView(MethodThrottleScopeMixin, APIView):
    """Módulos que la empresa ocupa (habilitación self-service, advisory).

    Es la decisión de negocio "¿qué módulos usa esta empresa?", independiente del
    acceso por permisos (que sigue gobernado por RBAC). El front cruza esto con
    ``allowed_modules`` para mostrar/ocultar.

    Permisos por método:
      - GET -> org.module.read
      - PUT -> org.module.manage
    """

    throttle_scope_by_method = {
        "GET": "heavy_reads",
        "PUT": "admin_writes",
    }

    def get_permissions(self):
        if self.request.method == "PUT":
            return [rbac_permission("org.module.manage")()]
        return [rbac_permission("org.module.read")()]

    def get(self, request):
        company: OrgUnit = request.company
        state = resolve_company_modules(company)
        rows = [
            {
                "code": spec.code,
                "label": spec.label,
                "category": spec.category,
                "core": spec.core,
                "is_enabled": bool(state.get(spec.code, spec.default_enabled)),
            }
            for spec in get_catalog()
        ]
        return Response({"results": ModuleStateOut(rows, many=True).data}, status=status.HTTP_200_OK)

    def put(self, request):
        company: OrgUnit = request.company
        serializer = ModulesUpdateIn(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            after = set_company_modules(
                company=company,
                changes=serializer.validated_data["modules"],
                request=request,
                actor=request.user,
            )
        except ModuleDependencyError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        rows = [
            {
                "code": spec.code,
                "label": spec.label,
                "category": spec.category,
                "core": spec.core,
                "is_enabled": bool(after.get(spec.code, spec.default_enabled)),
            }
            for spec in get_catalog()
        ]
        return Response({"results": ModuleStateOut(rows, many=True).data}, status=status.HTTP_200_OK)


def _serialize_relationship(rel: IntercompanyRelationship) -> dict:
    return {
        "id": rel.id,
        "company_a_id": rel.company_a_id,
        "company_a_name": rel.company_a.name,
        "company_b_id": rel.company_b_id,
        "company_b_name": rel.company_b.name,
        "relationship_type": rel.relationship_type,
        "relationship_type_label": rel.get_relationship_type_display(),
        "note": rel.note,
        "is_active": rel.is_active,
    }


class IntercompanyRelationshipListCreateView(MethodThrottleScopeMixin, APIView):
    """Relaciones intercompañía SIMPLES (declarar/listar). Sin montos ni cuentas.

    Acotado a las empresas accesibles del holding del usuario. Permisos:
      - GET  -> org.module.read
      - POST -> org.module.manage  (es "habilitar la opción")
    """

    throttle_scope_by_method = {"GET": "heavy_reads", "POST": "admin_writes"}

    def get_permissions(self):
        if self.request.method == "POST":
            return [rbac_permission("org.module.manage")()]
        return [rbac_permission("org.module.read")()]

    def get(self, request):
        company_ids = [c.id for c in get_accessible_companies(request.user)]
        qs = (
            IntercompanyRelationship.objects.filter(
                company_a_id__in=company_ids, company_b_id__in=company_ids
            )
            .select_related("company_a", "company_b")
            .order_by("company_a__name", "company_b__name", "relationship_type")
        )
        limit, offset = get_limit_offset(request)
        total, rows = paginate_queryset(qs, limit=limit, offset=offset)
        return Response(
            {"count": total, "limit": limit, "offset": offset,
             "results": [_serialize_relationship(r) for r in rows]},
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        s = IntercompanyRelationshipIn(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        accessible = {c.id: c for c in get_accessible_companies(request.user)}
        for key in ("company_a_id", "company_b_id"):
            if v[key] not in accessible:
                return Response({key: "Empresa no accesible o inexistente."}, status=status.HTTP_400_BAD_REQUEST)
        rel = IntercompanyRelationship(
            company_a=accessible[v["company_a_id"]],
            company_b=accessible[v["company_b_id"]],
            relationship_type=v["relationship_type"],
            note=v.get("note", ""),
            is_active=v.get("is_active", True),
            created_by=request.user,
        )
        try:
            # La unicidad la valida la BD (→ 409); full_clean solo corre las reglas de negocio.
            rel.full_clean(exclude=["created_by"], validate_unique=False, validate_constraints=False)
            with transaction.atomic():
                rel.save()
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}
            return Response(detail, status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError:
            return Response(
                {"detail": "Ya existe esa relación entre esas empresas."},
                status=status.HTTP_409_CONFLICT,
            )
        write_event(
            request=request,
            module="ORG",
            event_type="ORG_INTERCOMPANY_RELATIONSHIP_CREATED",
            reason_code="OK",
            actor_user=request.user,
            subject_type="INTERCOMPANY_RELATIONSHIP",
            subject_id=str(rel.id),
            metadata={
                "company_a_id": str(rel.company_a_id),
                "company_b_id": str(rel.company_b_id),
                "relationship_type": rel.relationship_type,
            },
        )
        return Response(_serialize_relationship(rel), status=status.HTTP_201_CREATED)


class IntercompanyRelationshipDetailView(APIView):
    """Editar (activar/desactivar/tipo/nota) o quitar una relación intercompañía."""

    permission_classes = [rbac_permission("org.module.manage")]
    throttle_scope = "admin_writes"

    def _get(self, request, rel_id):
        company_ids = [c.id for c in get_accessible_companies(request.user)]
        return get_object_or_404(
            IntercompanyRelationship.objects.select_related("company_a", "company_b"),
            id=rel_id,
            company_a_id__in=company_ids,
            company_b_id__in=company_ids,
        )

    def patch(self, request, rel_id):
        rel = self._get(request, rel_id)
        s = IntercompanyRelationshipUpdateIn(data=request.data)
        s.is_valid(raise_exception=True)
        for field, value in s.validated_data.items():
            setattr(rel, field, value)
        try:
            with transaction.atomic():
                rel.save()
        except IntegrityError:
            return Response(
                {"detail": "Ya existe esa relación entre esas empresas."},
                status=status.HTTP_409_CONFLICT,
            )
        write_event(
            request=request,
            module="ORG",
            event_type="ORG_INTERCOMPANY_RELATIONSHIP_UPDATED",
            reason_code="OK",
            actor_user=request.user,
            subject_type="INTERCOMPANY_RELATIONSHIP",
            subject_id=str(rel.id),
            metadata={"is_active": rel.is_active, "relationship_type": rel.relationship_type},
        )
        return Response(_serialize_relationship(rel), status=status.HTTP_200_OK)

    def delete(self, request, rel_id):
        rel = self._get(request, rel_id)
        rel_pk = rel.id
        rel.delete()
        write_event(
            request=request,
            module="ORG",
            event_type="ORG_INTERCOMPANY_RELATIONSHIP_DELETED",
            reason_code="OK",
            actor_user=request.user,
            subject_type="INTERCOMPANY_RELATIONSHIP",
            subject_id=str(rel_pk),
            metadata={},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
