#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from contextlib import redirect_stderr
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate OpenAPI and enforce its warning/path ratchet.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--settings", default="config.settings.test")
    parser.add_argument("--baseline", default="qa/contracts/openapi_contract_baseline.json")
    parser.add_argument("--output", default="qa/reports/openapi_contract_guard.json")
    return parser.parse_args()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    sys.path.insert(0, str(root / "backend" / "src"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", args.settings)

    baseline_path = root / args.baseline
    output_path = root / args.output
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    issues: list[str] = []
    captured = io.StringIO()
    schema = None

    try:
        import django

        django.setup()
        from drf_spectacular.generators import SchemaGenerator

        with redirect_stderr(captured):
            schema = SchemaGenerator().get_schema(request=None, public=True)
    except Exception as exc:  # pragma: no cover - exercised by the deployment gate
        issues.append(f"schema generation failed: {type(exc).__name__}: {exc}")

    diagnostic_text = captured.getvalue()
    warning_lines = diagnostic_text.count(": Warning [")
    serializer_error_lines = diagnostic_text.count(": Error [")
    operation_id_collisions = diagnostic_text.count("Warning: operationId")
    paths_count = len((schema or {}).get("paths", {}))

    if warning_lines > int(baseline["max_warning_lines"]):
        issues.append(f"warning lines grew: {warning_lines} > {baseline['max_warning_lines']}")
    if serializer_error_lines > int(baseline["max_serializer_error_lines"]):
        issues.append(
            "serializer documentation errors grew: "
            f"{serializer_error_lines} > {baseline['max_serializer_error_lines']}"
        )
    if operation_id_collisions > int(baseline["max_operation_id_collisions"]):
        issues.append(
            f"operationId collisions grew: {operation_id_collisions} > "
            f"{baseline['max_operation_id_collisions']}"
        )
    if paths_count < int(baseline["min_paths"]):
        issues.append(f"documented paths shrank: {paths_count} < {baseline['min_paths']}")

    forbidden_hits = [pattern for pattern in baseline.get("forbidden_patterns", []) if pattern in diagnostic_text]
    if forbidden_hits:
        issues.append("forbidden diagnostics returned: " + ", ".join(forbidden_hits))

    payload = {
        "status": "failed" if issues else "passed",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "settings": args.settings,
        "paths": paths_count,
        "warning_lines": warning_lines,
        "serializer_error_lines": serializer_error_lines,
        "operation_id_collisions": operation_id_collisions,
        "forbidden_hits": forbidden_hits,
        "issues": issues,
    }
    write_json(output_path, payload)

    if issues:
        for issue in issues:
            print(f"[qa] openapi contract: {issue}", file=sys.stderr)
        return 1
    print(
        f"[qa] openapi contract passed: {paths_count} paths, "
        f"{warning_lines} warnings, {serializer_error_lines} serializer gaps"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
