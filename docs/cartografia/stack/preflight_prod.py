#!/usr/bin/env python3
"""Preflight de producción reproducible (el productor que faltaba en el repo).

Corre `manage.py check --deploy --fail-level ERROR` con settings de producción y claves
descartables (las del .env de desarrollo dispararían el fail-fast de prod.py), igual que
`docker/entrypoint.prod.sh`. La salida va a un archivo, no a un argumento (es larga), y se
resume en JSON. Se corre dentro del backend del stack aislado:

    erpbl exec-backend "python /app/docs/cartografia/stack/preflight_prod.py --output /app/qa/reports/final/production_preflight.json"
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
from datetime import datetime, timezone


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--backend-dir", default="/app/backend")
    args = parser.parse_args()

    env = dict(os.environ)
    env["DJANGO_SETTINGS_MODULE"] = "config.settings.prod"
    env["DJANGO_SECRET_KEY"] = secrets.token_urlsafe(64)
    env["AUDIT_HMAC_KEY"] = secrets.token_urlsafe(48)
    cmd = ["python", "manage.py", "check", "--deploy", "--fail-level", "ERROR"]
    proc = subprocess.run(cmd, cwd=args.backend_dir, env=env, capture_output=True, text=True)
    output = (proc.stdout or "") + (proc.stderr or "")
    lines = output.splitlines()
    report = {
        "status": "passed" if proc.returncode == 0 else "failed",
        "exit_code": proc.returncode,
        "command": "manage.py check --deploy --fail-level ERROR (settings.prod, claves descartables)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "warning_lines": sum(1 for line in lines if "WARNING" in line or ": (" in line and ".W" in line),
        "error_lines": sum(1 for line in lines if ".E" in line and ": (" in line),
        "system_check_summary": next((line for line in reversed(lines) if "System check identified" in line), ""),
        "output_tail": "\n".join(lines[-60:]),
    }
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"preflight {report['status']} (rc={proc.returncode}) → {args.output}")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
