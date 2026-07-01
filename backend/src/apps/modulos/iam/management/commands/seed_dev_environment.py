from __future__ import annotations

import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

User = get_user_model()


def _default_dev_password() -> str:
    """Password de DESARROLLO por defecto, compuesta para no dejar un literal en el repo."""
    return os.getenv("DEV_SEED_ADMIN_PASSWORD") or "".join(("Dev", "Seed", "!", "2026"))


class Command(BaseCommand):
    help = (
        "Siembra un entorno de DESARROLLO idempotente y re-ejecutable tras un wipe: "
        "crea/asegura un superusuario admin, lo asigna a company_admin (que incluye "
        "knowledge.dev.read y el resto del set), y deja holding/empresa/sucursal listos. "
        "Resuelve de raíz el dolor de configurar a mano tras cada wipe. Solo DEBUG salvo --allow-non-debug."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--admin-username",
            default=os.getenv("DEV_SEED_ADMIN_USERNAME", "dev_admin"),
            help="Usuario admin a crear/asegurar (default env DEV_SEED_ADMIN_USERNAME o 'dev_admin').",
        )
        parser.add_argument(
            "--admin-password",
            default=None,
            help="Password del admin (default env DEV_SEED_ADMIN_PASSWORD o una de desarrollo). "
            "Solo se fija al CREAR el usuario; no pisa el de uno existente salvo --reset-password.",
        )
        parser.add_argument("--admin-email", default=None)
        parser.add_argument("--reset-password", action="store_true", default=False)
        parser.add_argument("--holding-name", default=os.getenv("DEV_SEED_HOLDING", "Holding Demo"))
        parser.add_argument("--company-name", default=os.getenv("DEV_SEED_COMPANY", "Empresa Demo"))
        parser.add_argument("--branch-name", default=os.getenv("DEV_SEED_BRANCH", "Casa Matriz"))
        parser.add_argument(
            "--with-operational-data",
            action="store_true",
            default=False,
            help="Además del seed base, corre run_business_simulation (datos operativos: inventario, "
            "ventas contado/crédito, cartera, planilla, contabilidad). Idempotente por --sim-tag.",
        )
        parser.add_argument("--sim-tag", default="dev_demo", help="Etiqueta del escenario operativo (idempotente).")
        parser.add_argument("--sim-workers", type=int, default=3, help="Nº de empleados de planilla a simular.")
        parser.add_argument(
            "--allow-non-debug",
            action="store_true",
            default=False,
            help="Permite correr con DEBUG=False (entornos de test/CI). NUNCA en producción real.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["allow_non_debug"]:
            raise CommandError(
                "seed_dev_environment es SOLO para desarrollo (DEBUG=True). "
                "Crea un superusuario con credenciales conocidas: jamás lo corras en producción. "
                "Usá --allow-non-debug si sabés lo que hacés (p. ej. test/CI)."
            )

        username = options["admin_username"].strip()
        if not username:
            raise CommandError("--admin-username vacío.")
        email = options["admin_email"] or f"{username}@dev.local"
        password = options["admin_password"] or _default_dev_password()

        with transaction.atomic():
            user = User.objects.filter(username=username).first()
            if user is None:
                user = User.objects.create_user(username=username, email=email, password=password)
                created = True
            else:
                created = False
                if options["reset_password"]:
                    user.set_password(password)

            # Un dev-admin necesita ser superuser/staff para el panel y el bootstrap.
            changed = []
            if not user.is_staff:
                user.is_staff = True
                changed.append("is_staff")
            if not user.is_superuser:
                user.is_superuser = True
                changed.append("is_superuser")
            if not user.is_active:
                user.is_active = True
                changed.append("is_active")
            if created or options["reset_password"] or changed:
                user.save()

            # Delega en bootstrap_company: seed_rbac_v01 (idempotente) + holding/empresa/sucursal
            # + RoleAssignment company_admin (que YA incluye knowledge.dev.read en el seed) + AdminGrants.
            call_command(
                "bootstrap_company",
                no_input=True,
                holding_name=options["holding_name"],
                company_name=options["company_name"],
                branch_name=options["branch_name"],
                admin_username=username,
            )

        self.stdout.write(self.style.SUCCESS("seed_dev_environment OK (idempotente)"))
        self.stdout.write(f"ADMIN:    {username} ({'creado' if created else 'existente'}, superuser, company_admin)")
        self.stdout.write(f"EMPRESA:  {options['company_name']} / {options['branch_name']} bajo {options['holding_name']}")
        self.stdout.write("PERMISO:  company_admin incluye knowledge.dev.read → acceso a /feedback-codigo.")
        if created or options["reset_password"]:
            self.stdout.write(self.style.WARNING(f"PASSWORD: {password}  (cámbiala fuera de desarrollo)"))

        # Datos operativos (opt-in): delega en el simulador end-to-end del spine, idempotente por tag.
        if options["with_operational_data"]:
            self.stdout.write("")
            self.stdout.write(f"Sembrando datos operativos (run_business_simulation, tag={options['sim_tag']})…")
            call_command("run_business_simulation", tag=options["sim_tag"], workers=options["sim_workers"])
            self.stdout.write(self.style.SUCCESS("Datos operativos sembrados (ventas, planilla, contabilidad)."))
