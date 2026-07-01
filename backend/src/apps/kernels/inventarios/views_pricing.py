"""Administración de listas de precios (CRUD por API).

Cierra el follow-up §12: hasta ahora ``PriceList``/``PriceListItem``/
``PriceListAssignment`` solo se cargaban por shell/admin. El precio de venta lo sigue
resolviendo SIEMPRE el servidor (``pricing.resolve_sale_price``); esta API solo administra
las listas, sus tramos y a quién aplican. Todo gated por RBAC y auditado.

``PriceList`` es de empresa (sin ``branch``): el scope es ``request.company``.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import IntegrityError, transaction
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modulos.audit.writer import write_event
from apps.modulos.common.pagination import get_limit_offset, paginate_queryset
from apps.modulos.common.permissions import rbac_permission
from apps.modulos.parties.models import Party

from .models import InventoryItem, PriceList, PriceListAssignment, PriceListItem

_READ = "inventory.pricelist.read"
_WRITE = "inventory.pricelist.write"


# --------------------------------------------------------------------------- #
# Serializers de entrada                                                       #
# --------------------------------------------------------------------------- #
class PriceListInSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    currency = serializers.CharField(max_length=8, required=False, default="NIO")
    is_active = serializers.BooleanField(required=False, default=True)

    def validate_currency(self, v: str) -> str:
        return (v or "NIO").strip().upper()


class PriceListPatchSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80, required=False)
    currency = serializers.CharField(max_length=8, required=False)
    is_active = serializers.BooleanField(required=False)

    def validate_currency(self, v: str) -> str:
        return (v or "").strip().upper()


class PriceListItemInSerializer(serializers.Serializer):
    item_id = serializers.IntegerField(min_value=1)
    min_qty = serializers.DecimalField(
        max_digits=18, decimal_places=4, min_value=Decimal("0"),
        required=False, default=Decimal("0.0000"),
    )
    price = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"))


class PriceListAssignmentInSerializer(serializers.Serializer):
    party_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    segment = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        party_id = attrs.get("party_id")
        segment = (attrs.get("segment") or "").strip().upper()
        attrs["segment"] = segment
        if bool(party_id) == bool(segment):
            raise serializers.ValidationError(
                "Indique exactamente uno: 'party_id' (cliente) o 'segment'."
            )
        return attrs


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #
def _pricelist_or_none(company, pricelist_id: int) -> PriceList | None:
    return PriceList.objects.filter(company=company, id=int(pricelist_id)).first()


def _pricelist_payload(pl: PriceList) -> dict:
    return {
        "id": pl.id,
        "name": pl.name,
        "currency": pl.currency,
        "is_active": pl.is_active,
        "items": [
            {
                "id": it.id,
                "item_id": it.item_id,
                "min_qty": str(it.min_qty),
                "price": str(it.price),
            }
            for it in pl.items.select_related("item").order_by("item_id", "min_qty")
        ],
        "assignments": [
            {
                "id": a.id,
                "party_id": a.party_id,
                "segment": a.segment,
                "is_active": a.is_active,
            }
            for a in pl.assignments.filter(is_active=True).order_by("id")
        ],
        "created_at": pl.created_at,
    }


def _audit(request, *, event_type: str, pl: PriceList, after=None, metadata=None):
    write_event(
        request=request,
        module="INVENTORY",
        event_type=event_type,
        reason_code="INVENTORY_OK",
        actor_user=getattr(request, "user", None),
        subject_type="INVENTORY_PRICELIST",
        subject_id=str(pl.id),
        after_snapshot=after,
        metadata=metadata or {},
    )


# --------------------------------------------------------------------------- #
# Vistas                                                                       #
# --------------------------------------------------------------------------- #
class PriceListListCreateView(APIView):
    """GET lista listas de precios (read) + POST crea (write)."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [rbac_permission(_WRITE)()]
        return [rbac_permission(_READ)()]

    def get(self, request):
        qs = PriceList.objects.filter(company=request.company).order_by("name")
        currency = (request.query_params.get("currency") or "").strip().upper()
        if currency:
            qs = qs.filter(currency=currency)
        active = request.query_params.get("is_active")
        if active is not None:
            qs = qs.filter(is_active=str(active).lower() in ("1", "true", "yes"))
        limit, offset = get_limit_offset(request)
        total, rows = paginate_queryset(qs, limit=limit, offset=offset)
        results = [
            {
                "id": pl.id,
                "name": pl.name,
                "currency": pl.currency,
                "is_active": pl.is_active,
                "created_at": pl.created_at,
            }
            for pl in rows
        ]
        return Response({"count": total, "limit": limit, "offset": offset, "results": results})

    def post(self, request):
        s = PriceListInSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        try:
            with transaction.atomic():
                pl = PriceList.objects.create(
                    company=request.company,
                    name=v["name"],
                    currency=v["currency"],
                    is_active=v["is_active"],
                )
        except IntegrityError:
            return Response({"detail": "PRICELIST_NAME_CONFLICT"}, status=status.HTTP_409_CONFLICT)
        _audit(request, event_type="INVENTORY_PRICELIST_CREATED", pl=pl,
               after={"name": pl.name, "currency": pl.currency, "is_active": pl.is_active})
        return Response(_pricelist_payload(pl), status=status.HTTP_201_CREATED)


class PriceListDetailView(APIView):
    def get_permissions(self):
        if self.request.method == "PATCH":
            return [rbac_permission(_WRITE)()]
        return [rbac_permission(_READ)()]

    def get(self, request, pricelist_id: int):
        pl = _pricelist_or_none(request.company, pricelist_id)
        if pl is None:
            return Response({"detail": "PRICELIST_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        return Response(_pricelist_payload(pl))

    def patch(self, request, pricelist_id: int):
        pl = _pricelist_or_none(request.company, pricelist_id)
        if pl is None:
            return Response({"detail": "PRICELIST_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        s = PriceListPatchSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        fields = []
        for f in ("name", "currency", "is_active"):
            if f in v:
                setattr(pl, f, v[f])
                fields.append(f)
        if not fields:
            return Response(_pricelist_payload(pl))
        try:
            with transaction.atomic():
                pl.save(update_fields=fields)
        except IntegrityError:
            return Response({"detail": "PRICELIST_NAME_CONFLICT"}, status=status.HTTP_409_CONFLICT)
        _audit(request, event_type="INVENTORY_PRICELIST_UPDATED", pl=pl,
               after={f: getattr(pl, f) for f in fields}, metadata={"fields": ",".join(fields)})
        return Response(_pricelist_payload(pl))


class PriceListItemView(APIView):
    """GET tramos (read) + POST upsert tramo por (item, min_qty) (write)."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [rbac_permission(_WRITE)()]
        return [rbac_permission(_READ)()]

    def get(self, request, pricelist_id: int):
        pl = _pricelist_or_none(request.company, pricelist_id)
        if pl is None:
            return Response({"detail": "PRICELIST_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        rows = pl.items.order_by("item_id", "min_qty")
        return Response({
            "results": [
                {"id": it.id, "item_id": it.item_id, "min_qty": str(it.min_qty), "price": str(it.price)}
                for it in rows
            ]
        })

    def post(self, request, pricelist_id: int):
        pl = _pricelist_or_none(request.company, pricelist_id)
        if pl is None:
            return Response({"detail": "PRICELIST_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        s = PriceListItemInSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        item = InventoryItem.objects.filter(company=request.company, id=v["item_id"]).first()
        if item is None:
            return Response({"detail": "INVENTORY_ITEM_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        with transaction.atomic():
            row, created = PriceListItem.objects.update_or_create(
                pricelist=pl, item=item, min_qty=v["min_qty"],
                defaults={"price": v["price"]},
            )
        _audit(request, event_type="INVENTORY_PRICELIST_UPDATED", pl=pl,
               metadata={"tramo": "set", "item_id": str(item.id),
                         "min_qty": str(row.min_qty), "price": str(row.price)})
        out = {"id": row.id, "item_id": row.item_id, "min_qty": str(row.min_qty), "price": str(row.price)}
        return Response(out, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class PriceListItemDeleteView(APIView):
    permission_classes = [rbac_permission(_WRITE)]

    def delete(self, request, pricelist_id: int, line_id: int):
        pl = _pricelist_or_none(request.company, pricelist_id)
        if pl is None:
            return Response({"detail": "PRICELIST_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        row = pl.items.filter(id=int(line_id)).first()
        if row is None:
            return Response({"detail": "PRICELIST_ITEM_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        meta = {"tramo": "delete", "item_id": str(row.item_id), "min_qty": str(row.min_qty)}
        with transaction.atomic():
            row.delete()
        _audit(request, event_type="INVENTORY_PRICELIST_UPDATED", pl=pl, metadata=meta)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PriceListAssignmentView(APIView):
    """GET asignaciones activas (read) + POST asigna a party o segmento (write)."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [rbac_permission(_WRITE)()]
        return [rbac_permission(_READ)()]

    def get(self, request, pricelist_id: int):
        pl = _pricelist_or_none(request.company, pricelist_id)
        if pl is None:
            return Response({"detail": "PRICELIST_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        rows = pl.assignments.filter(is_active=True).order_by("id")
        return Response({
            "results": [
                {"id": a.id, "party_id": a.party_id, "segment": a.segment, "is_active": a.is_active}
                for a in rows
            ]
        })

    def post(self, request, pricelist_id: int):
        pl = _pricelist_or_none(request.company, pricelist_id)
        if pl is None:
            return Response({"detail": "PRICELIST_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        s = PriceListAssignmentInSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        party = None
        if v.get("party_id"):
            party = Party.objects.filter(company=request.company, id=v["party_id"]).first()
            if party is None:
                return Response({"detail": "PARTY_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        try:
            with transaction.atomic():
                assignment = PriceListAssignment.objects.create(
                    company=request.company,
                    pricelist=pl,
                    party=party,
                    segment=v["segment"],
                    is_active=True,
                )
        except IntegrityError:
            # Ya hay una asignación activa para ese party/segmento en la empresa.
            return Response(
                {"detail": "PRICELIST_ASSIGNMENT_CONFLICT"}, status=status.HTTP_409_CONFLICT
            )
        _audit(request, event_type="INVENTORY_PRICELIST_ASSIGNED", pl=pl,
               metadata={"party_id": str(party.id) if party else "", "segment": v["segment"]})
        return Response(
            {"id": assignment.id, "party_id": assignment.party_id,
             "segment": assignment.segment, "is_active": True},
            status=status.HTTP_201_CREATED,
        )


class PriceListAssignmentDeleteView(APIView):
    permission_classes = [rbac_permission(_WRITE)]

    def delete(self, request, pricelist_id: int, assign_id: int):
        pl = _pricelist_or_none(request.company, pricelist_id)
        if pl is None:
            return Response({"detail": "PRICELIST_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        a = pl.assignments.filter(id=int(assign_id), is_active=True).first()
        if a is None:
            return Response({"detail": "PRICELIST_ASSIGNMENT_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        meta = {"party_id": str(a.party_id or ""), "segment": a.segment}
        with transaction.atomic():
            a.is_active = False
            a.save(update_fields=["is_active"])
        _audit(request, event_type="INVENTORY_PRICELIST_UNASSIGNED", pl=pl, metadata=meta)
        return Response(status=status.HTTP_204_NO_CONTENT)
