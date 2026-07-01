"""Backfill del carnet (worker_code) en PayrollEntry existentes.

Toma el carnet del expediente (employee.party.worker_code); si la entry no tiene empleado pero sí
cédula, lo resuelve por la cédula contra el Party de SU empresa. Así las planillas ya cargadas
quedan con el ID único para el cobro entre empresas. Idempotente (solo toca las que están en blanco).
"""
from __future__ import annotations

from django.db import migrations


def backfill(apps, schema_editor):
    PayrollEntry = apps.get_model("nomina", "PayrollEntry")
    Employee = apps.get_model("hr", "Employee")
    Party = apps.get_model("parties", "Party")

    emp_carnet = dict(
        Employee.objects.exclude(party__isnull=True)
        .exclude(party__worker_code="")
        .values_list("id", "party__worker_code")
    )

    to_update = []
    for e in PayrollEntry.objects.filter(worker_code="").select_related("sheet__period"):
        code = emp_carnet.get(e.employee_id, "") if e.employee_id else ""
        if not code and (e.cedula or "").strip():
            company_id = e.sheet.period.company_id
            p = (
                Party.objects.filter(
                    company_id=company_id, national_id=(e.cedula or "").strip().upper()
                )
                .exclude(worker_code="")
                .first()
            )
            if p:
                code = p.worker_code
        if code:
            e.worker_code = code
            to_update.append(e)

    if to_update:
        PayrollEntry.objects.bulk_update(to_update, ["worker_code"], batch_size=500)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("nomina", "0018_payrollentry_worker_code"),
        ("parties", "0003_backfill_worker_code"),
    ]

    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
