"""Comando periódico (cron) que corre todos los escáneres de alertas.

Idempotente: re-correrlo no duplica alertas (dedupe por sujeto) ni notificaciones
(dedupe_key por alerta+día). Pensado para correr 1-2 veces al día.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.modulos.alertas.services import run_all_scanners
from apps.modulos.iam.models import OrgUnit


class Command(BaseCommand):
    help = "Corre los escáneres deterministas de alertas (CxC, préstamos, stock, flota)."

    def add_arguments(self, parser):
        parser.add_argument("--company-id", type=int, default=None)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        company = None
        if options["company_id"]:
            company = OrgUnit.objects.get(
                pk=options["company_id"], unit_type=OrgUnit.UnitType.COMPANY
            )
        result = run_all_scanners(company=company)
        if options["json"]:
            self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            for comp, types in result.items():
                for alert_type, counts in types.items():
                    self.stdout.write(
                        f"{comp} {alert_type}: activas={counts['active']} "
                        f"abiertas/reabiertas={counts['opened']} resueltas={counts['resolved']}"
                    )
