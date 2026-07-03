from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from django.db.models import Count, Max, Q
from django.utils import timezone

from apps.modulos.hr.models import EmploymentAssignment
from apps.kernels.reporting.exceptions import DatasetExecutionError


def _headcount_payload(*, company, branch, filters: dict[str, Any]) -> dict[str, Any]:
    as_of_raw = filters.get("as_of")
    if isinstance(as_of_raw, datetime):
        as_of_dt = as_of_raw
    elif isinstance(as_of_raw, date):
        as_of_dt = datetime.combine(as_of_raw, time.max)
    elif isinstance(as_of_raw, str):
        raw = as_of_raw.strip()
        if not raw:
            as_of_dt = timezone.now()
        else:
            try:
                as_of_dt = datetime.combine(date.fromisoformat(raw), time.max)
            except ValueError as exc:
                raise DatasetExecutionError("as_of debe estar en formato YYYY-MM-DD.") from exc
    else:
        as_of_dt = timezone.now()
    if timezone.is_naive(as_of_dt):
        as_of_dt = timezone.make_aware(as_of_dt, timezone.get_current_timezone())

    assignments = EmploymentAssignment.objects.filter(
        employee__company=company,
        started_at__lte=as_of_dt,
    ).filter(
        Q(ended_at__isnull=True) | Q(ended_at__gt=as_of_dt)
    )
    if branch is not None:
        assignments = assignments.filter(branch=branch)

    # Agregación EN la BD (oleada 6): antes iteraba todas las asignaciones en
    # Python. Un GROUP BY por puesto + un aggregate para los totales. Se agrupa
    # por NOMBRE (igual que antes); el código es informativo (Max = determinista
    # donde el viejo "último gana" era orden de iteración).
    por_puesto = (
        assignments.values("position__name")
        .annotate(
            position_code=Max("position__code"),
            active_assignments=Count("id"),
            unique_employees=Count("employee_id", distinct=True),
        )
        .order_by("position__name")
    )
    rows: list[dict[str, Any]] = [
        {
            "position_name": str(r["position__name"]),
            "position_code": str(r["position_code"] or ""),
            "active_assignments": int(r["active_assignments"]),
            "unique_employees": int(r["unique_employees"]),
        }
        for r in por_puesto
    ]
    totales = assignments.aggregate(
        active_assignments=Count("id"),
        unique_employees=Count("employee_id", distinct=True),
    )

    return {
        "grain": "position",
        "dimensions": ["position_name", "position_code"],
        "measures": ["active_assignments", "unique_employees", "total_active_employees"],
        "rows": rows,
        "totals": {
            "active_assignments": int(totales["active_assignments"]),
            "unique_employees": int(totales["unique_employees"]),
            "total_active_employees": int(totales["unique_employees"]),
        },
        "warnings": [],
        "source_summary": {"source_modules": ["HR"]},
        "effective_filters": {"as_of": as_of_dt.date().isoformat()},
    }


def run_dataset(*, dataset_key: str, company, branch, filters: dict) -> dict[str, Any]:
    if dataset_key == "hr.headcount.current":
        return _headcount_payload(company=company, branch=branch, filters=filters)
    raise DatasetExecutionError(f"Dataset HR no soportado: {dataset_key}")
