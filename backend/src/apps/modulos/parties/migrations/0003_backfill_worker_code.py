"""Backfill del carnet (worker_code) en Party existentes.

Asigna el ID único de persona del holding a los Party que aún no lo tienen:
- Misma **cédula** (national_id) ⇒ MISMO carnet entre empresas (es la misma persona).
- Sin cédula ⇒ carnet nuevo por persona (no hay forma de deduplicar; el operador podrá ligarlos
  luego escribiendo/escaneando el carnet en la otra empresa).
Solo personas NATURAL (empresas/INTERNAL no llevan carnet). Idempotente/reejecutable: reusa los
carnets ya emitidos (siembra el mapa cédula→carnet desde los Party ya carnetizados).
"""
from __future__ import annotations

import re

from django.db import migrations

_RX = re.compile(r"^W-(\d+)$")


def backfill(apps, schema_editor):
    Party = apps.get_model("parties", "Party")

    # Contador inicial = máximo correlativo W-NNNN ya existente (no colisionar con nadie).
    counter = 0
    by_cedula: dict[str, str] = {}
    for code in Party.objects.exclude(worker_code="").values_list("worker_code", flat=True):
        m = _RX.match((code or "").strip().upper())
        if m:
            counter = max(counter, int(m.group(1)))

    # Sembrar cédula→carnet desde los que YA tienen carnet (idempotencia en re-runs).
    for ced, code in (
        Party.objects.filter(party_type="NATURAL")
        .exclude(worker_code="")
        .exclude(national_id="")
        .values_list("national_id", "worker_code")
    ):
        key = (ced or "").strip().upper()
        if key and key not in by_cedula:
            by_cedula[key] = (code or "").strip().upper()

    to_update = []
    for p in Party.objects.filter(party_type="NATURAL", worker_code="").order_by("id"):
        ced = (p.national_id or "").strip().upper()
        if ced and ced in by_cedula:
            code = by_cedula[ced]
        else:
            counter += 1
            code = f"W-{counter:06d}"
            if ced:
                by_cedula[ced] = code
        p.worker_code = code
        to_update.append(p)

    if to_update:
        Party.objects.bulk_update(to_update, ["worker_code"], batch_size=500)


def noop_reverse(apps, schema_editor):
    # No revertimos: el carnet es identidad emitida; quitarla rompería los cruces.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("parties", "0002_party_worker_code_party_ix_party_company_worker_code_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
