"""DEV: enrola un nodo como firmante (reusa `Device` Ed25519). Correr en el CENTRAL.

Genera un par Ed25519, registra el `Device` (empresa/sucursal) e imprime las credenciales que van
en el ENV del NODO (`SYNC_NODE_DEVICE_ID`, `SYNC_NODE_PRIVATE_KEY_B64`) + el `SYNC_CENTRAL_URL`.
Atajo de desarrollo; el enrolamiento real (modelo `Node` propio + reto→llave + snapshot inicial)
es F3.
"""
from __future__ import annotations

import base64

from django.core.management.base import BaseCommand, CommandError

from apps.modulos.iam.models import OrgUnit
from apps.modulos.sync_engine.models import Device
from apps.modulos.sync_engine.node_signing import generate_keypair


class Command(BaseCommand):
    help = "DEV: enrola un nodo como Device firmante (genera keypair, crea el Device, imprime credenciales)."

    def add_arguments(self, parser):
        parser.add_argument("--company-id", type=int, required=True)
        parser.add_argument("--branch-id", type=int, default=None)
        parser.add_argument("--label", type=str, default="node")

    def handle(self, *args, **options):
        company = OrgUnit.objects.filter(
            id=options["company_id"], unit_type=OrgUnit.UnitType.COMPANY
        ).first()
        if company is None:
            raise CommandError(f"No existe empresa con id={options['company_id']}.")
        branch = None
        if options.get("branch_id"):
            branch = OrgUnit.objects.filter(
                id=options["branch_id"], unit_type=OrgUnit.UnitType.BRANCH, parent_id=company.id
            ).first()
            if branch is None:
                raise CommandError(f"No existe sucursal id={options['branch_id']} bajo la empresa {company.id}.")

        priv_b64, pub_b64 = generate_keypair()
        device = Device.objects.create(
            company=company,
            branch=branch,
            label=str(options["label"]),
            public_key=base64.b64decode(pub_b64.encode("utf-8"), validate=True),
            status=Device.Status.ACTIVE,
        )

        self.stdout.write("Nodo enrolado. Poné esto en el ENV del NODO:")
        self.stdout.write(f"  SYNC_NODE_DEVICE_ID={device.id}")
        self.stdout.write(f"  SYNC_NODE_PRIVATE_KEY_B64={priv_b64}")
        self.stdout.write("  SYNC_CENTRAL_URL=<URL del central, ej. http://central:8000>")
