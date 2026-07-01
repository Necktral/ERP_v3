"""F1 — worker del NODO: sube los eventos de replicación pendientes al central.

Drena el outbox (`source_module="sync_replication"`, FIFO = padres antes que hijos), empaqueta cada
evento como comando `sync.replicate.v1`, firma el lote por el riel del `sync_engine`
(`POST /api/sync/batch/`, v2 Ed25519) y marca cada evento `SENT` (ACCEPTED/DUPLICATE) o lo reintenta
(retry/DLQ del propio outbox). Reentrante: reenviar NO duplica (AppliedCommand + sync_uid).

Sin `SYNC_CENTRAL_URL` (dev sin central) → no-op: los eventos quedan en el outbox (bufferea). Nada
bloquea la operación del nodo.
"""
from __future__ import annotations

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.modulos.common.sync_replication import SYNC_SOURCE_MODULE
from apps.modulos.integration.models import OutboxEvent
from apps.modulos.integration.services import mark_outbox_event_retry, mark_outbox_event_sent
from apps.modulos.sync_engine.node_signing import (
    build_replication_command,
    build_signed_batch,
    load_private_key,
)


class Command(BaseCommand):
    help = "Sube al central los eventos de replicación pendientes del outbox, firmados (riel sync_engine)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--max-attempts", type=int, default=5)
        parser.add_argument("--timeout", type=float, default=15.0)

    def handle(self, *args, **options):
        central = str(getattr(settings, "SYNC_CENTRAL_URL", "") or "").rstrip("/")
        device_id = str(getattr(settings, "SYNC_NODE_DEVICE_ID", "") or "").strip()
        priv_b64 = str(getattr(settings, "SYNC_NODE_PRIVATE_KEY_B64", "") or "").strip()

        if not central:
            self.stdout.write("SYNC_CENTRAL_URL vacío → no-op (los eventos quedan en el outbox).")
            return
        if not device_id or not priv_b64:
            raise CommandError("Faltan SYNC_NODE_DEVICE_ID / SYNC_NODE_PRIVATE_KEY_B64 (enrola el nodo: sync_enroll_node).")

        limit = int(options["limit"])
        max_attempts = int(options["max_attempts"])
        pending = list(
            OutboxEvent.objects.filter(
                status=OutboxEvent.Status.PENDING, source_module=SYNC_SOURCE_MODULE
            ).order_by("occurred_at", "id")[:limit]
        )
        if not pending:
            self.stdout.write("Sin eventos de replicación pendientes.")
            return

        private_key = load_private_key(priv_b64)
        commands = [build_replication_command(ev) for ev in pending]
        body = build_signed_batch(device_id=device_id, private_key=private_key, commands=commands)

        try:
            resp = httpx.post(
                f"{central}/api/sync/batch/",
                json=body,
                headers={"X-Device-Id": device_id},
                timeout=float(options["timeout"]),
            )
        except Exception as exc:  # transporte caído → reintentar todo
            for ev in pending:
                mark_outbox_event_retry(event=ev, error=f"transport: {exc}", max_attempts=max_attempts)
            raise CommandError(f"No se pudo contactar al central: {exc}")

        if resp.status_code != 200:
            for ev in pending:
                mark_outbox_event_retry(
                    event=ev, error=f"HTTP {resp.status_code}: {resp.text[:160]}", max_attempts=max_attempts
                )
            raise CommandError(f"Central respondió HTTP {resp.status_code}.")

        out = resp.json()
        by_id = {str(r.get("command_id")): r for r in (out.get("results") or [])}
        sent = retried = 0
        for ev in pending:
            r = by_id.get(str(ev.event_id)) or {}
            if r.get("status") in ("APPLIED", "DUPLICATE"):
                mark_outbox_event_sent(event=ev)
                sent += 1
            else:
                mark_outbox_event_retry(
                    event=ev, error=str(r.get("reason") or "sin resultado del central"), max_attempts=max_attempts
                )
                retried += 1

        summary = out.get("summary", {})
        self.stdout.write(
            f"push: enviados={sent} reintentos={retried} | "
            f"central applied={summary.get('applied')} dup={summary.get('duplicate')} rej={summary.get('rejected')}"
        )
