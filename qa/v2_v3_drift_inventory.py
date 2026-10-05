#!/usr/bin/env python3
"""Inventario reproducible de arrastre v2→v3 y superficies legacy U30/L5."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

IGNORED_PARTS = {"__pycache__", ".pytest_cache", "node_modules", "dist", "test-results"}
IGNORED_SUFFIXES = {".pyc", ".pyo", ".map"}
TRACKING_ID = re.compile(r"\b(?:BUG|MEJ)-\d+\b")


def files(root: Path) -> dict[str, Path]:
    return {
        str(path.relative_to(root)): path
        for path in root.rglob("*")
        if path.is_file()
        and not any(part in IGNORED_PARTS for part in path.parts)
        and path.suffix not in IGNORED_SUFFIXES
    }


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def last_commit(repo: Path, path: str) -> dict[str, object]:
    proc = subprocess.run(
        ["git", "log", "-1", "--format=%H%x00%s", "--", path],
        cwd=repo, text=True, capture_output=True, check=False,
    )
    raw = proc.stdout.strip()
    if not raw:
        return {"commit": None, "subject": None, "tracking_ids": [], "mapped": False}
    commit, _, subject = raw.partition("\0")
    ids = sorted(set(TRACKING_ID.findall(subject)))
    return {"commit": commit, "subject": subject, "tracking_ids": ids, "mapped": bool(ids)}


def owner(path: str) -> str:
    parts = Path(path).parts
    for marker in ("kernels", "modulos", "modules"):
        if marker in parts and len(parts) > parts.index(marker) + 1:
            return f"{marker}/{parts[parts.index(marker) + 1]}"
    if path.startswith("frontend/src/core/"):
        return "frontend/core"
    if path.startswith("frontend/src/"):
        return "frontend/platform"
    return "backend/platform"


def classify(row: dict[str, object]) -> dict[str, str]:
    path, delta = str(row["path"]), str(row["delta"])
    if "/tests/" in path or Path(path).name.startswith("test_") or "/__tests__/" in path:
        return {"classification": "test", "reason": "cobertura/regresión v3", "owner": owner(path)}
    if "/migrations/" in path:
        return {"classification": "generated", "reason": "historial de esquema Django; validar por migration guard", "owner": owner(path)}
    if any(token in path for token in ("/management/commands/", "certification", "/phase7", "/phase8")):
        return {"classification": "tooling", "reason": "herramienta de operación/certificación", "owner": owner(path)}
    if delta == "only_v2":
        return {"classification": "legacy_removed", "reason": "presente sólo en v2; requiere decisión de retirada", "owner": owner(path)}
    if delta == "only_v3":
        return {"classification": "new_feature", "reason": "superficie nueva de v3", "owner": owner(path)}
    if row["mapped"]:
        return {"classification": "expected_v3", "reason": f"delta trazado por {', '.join(row['tracking_ids'])}", "owner": owner(path)}
    subject = str(row.get("subject") or "")
    if re.match(r"^(?:feat|fix|perf|refactor|chore|build|ci)(?:\(.+?\))?:", subject):
        return {"classification": "expected_v3", "reason": f"delta trazado por commit convencional: {subject}", "owner": owner(path)}
    return {"classification": "productive_unexplained", "reason": "cambio productivo sin BUG/MEJ explícito en el commit", "owner": owner(path)}


def compare(repo: Path, v2: Path, subtree: str) -> list[dict[str, object]]:
    old_root, new_root = v2 / subtree, repo / subtree
    old, new = files(old_root), files(new_root)
    rows: list[dict[str, object]] = []
    for relative in sorted(old.keys() | new.keys()):
        if relative not in old:
            kind = "only_v3"
        elif relative not in new:
            kind = "only_v2"
        elif digest(old[relative]) != digest(new[relative]):
            kind = "changed"
        else:
            continue
        repo_path = f"{subtree}/{relative}"
        tracking = last_commit(repo, repo_path) if relative in new else {
            "commit": None, "subject": None, "tracking_ids": [], "mapped": False,
        }
        row: dict[str, object] = {"path": repo_path, "delta": kind, **tracking}
        row.update(classify(row))
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--v2", default="/home/wis/dev/ERP_v2")
    parser.add_argument("--output", default="qa/reports/v2_v3_drift_inventory.json")
    args = parser.parse_args()
    repo, v2 = Path(args.repo).resolve(), Path(args.v2).resolve()
    deltas = compare(repo, v2, "backend/src") + compare(repo, v2, "frontend/src")
    unexplained = [row for row in deltas if row["classification"] == "productive_unexplained"]
    u30 = [
        {"surface": "apps.modulos.accounting", "kind": "compatibility_shim", "reachable": True, "auth_scope": "hereda el consumidor canónico", "disposition": "compat; retirar sólo tras eliminar imports", "owner": "kernels/accounting"},
        {"surface": "apps.modulos.facturacion", "kind": "compatibility_shim", "reachable": True, "auth_scope": "hereda el consumidor canónico", "disposition": "compat; retirar sólo tras eliminar imports", "owner": "kernels/facturacion"},
        {"surface": "apps.modulos.inventarios", "kind": "compatibility_shim", "reachable": True, "auth_scope": "hereda el consumidor canónico", "disposition": "compat; retirar sólo tras eliminar imports", "owner": "kernels/inventarios"},
        {"surface": "apps.kernels.facturacion.urls_legacy", "kind": "legacy_routes", "reachable": True, "auth_scope": "permisos de las views canónicas", "disposition": "compat; inventariar consumidores antes de remover", "owner": "kernels/facturacion"},
        {"surface": "apps.modulos.sync_engine.handlers_demo.DEMO_PING", "kind": "demo_handler", "reachable": False, "auth_scope": "dispatch exige SYNC_DEMO_COMMANDS_ENABLED explícito; producción lo fuerza false", "disposition": "prod-gated; habilitado deliberadamente sólo en dev/test", "owner": "modulos/sync_engine"},
        {"surface": "accounting phase7/phase7b/phase8 and certification*", "kind": "cutover_tooling", "reachable": True, "auth_scope": "CLI/management command; no endpoint público directo", "disposition": "tooling operativo; conservar con tests", "owner": "kernels/accounting"},
        {"surface": "apps.modulos.sync", "kind": "legacy_migration_only_namespace", "reachable": False, "auth_scope": "no instalado ni montado; sync_engine es el namespace activo", "disposition": "conservar sólo si el historial de migración externo lo exige; en otro caso remover", "owner": "modulos/sync"},
    ]
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "v2_root": str(v2),
        "v3_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
        "filters": {"ignored_parts": sorted(IGNORED_PARTS), "ignored_suffixes": sorted(IGNORED_SUFFIXES)},
        "summary": {
            "deltas": len(deltas),
            "mapped_to_tracking_id": sum(bool(row["mapped"]) for row in deltas),
            "productive_unexplained": len(unexplained),
            "by_classification": {name: sum(row["classification"] == name for row in deltas) for name in sorted({str(row["classification"]) for row in deltas})},
        },
        "closure_status": "passed" if not unexplained else "incomplete",
        "u30_surfaces": u30,
        "deltas": deltas,
    }
    output = repo / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
