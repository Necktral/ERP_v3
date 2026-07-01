#!/usr/bin/env python3
"""Route Authorization Guard (gate de authz de escritura).

Afirma que TODA vista con handlers de ESCRITURA (POST/PUT/PATCH/DELETE, o
create/update/partial_update/destroy en ViewSets) está gateada por
`rbac_permission(...)` — la fábrica de permisos RBAC del proyecto
(`apps.modulos.common.permissions.rbac_permission`).

Motivación — hueco de seguridad sin dueño: el CI ya cubre secretos (gitleaks),
CVEs de dependencias (pip-audit/npm audit), SAST (bandit) y migraciones, pero
NADIE verifica de forma sistemática que cada endpoint de escritura exija un
permiso efectivo en el backend. Una vista de escritura sin `rbac_permission` es
candidata a IDOR / fuga cross-tenant (gateo solo en la UI, no en el servidor).

Diseño: scan AST estático (sin runtime Django), estilo ratchet con baseline —
igual que `migration_safety_guard.py`. Una vista de escritura se considera
GATEADA si su cuerpo (o el de una clase base definida en el MISMO archivo)
referencia `rbac_permission`. Las vistas de escritura legítimamente NO-RBAC
(login/refresh/logout, webhooks públicos, kiosko self-service, health) van en el
baseline-allowlist CON una razón explícita.

Falla (exit 1) si aparece una vista de escritura no gateada que NO está en el
baseline (drift nuevo). El baseline es un trinquete: agregar una excepción exige
editarlo en el PR con su razón. NO uses `--write-baseline` para silenciar gaps
reales; solo para el bootstrap inicial revisado.
"""
from __future__ import annotations

import argparse
import ast
import json
from datetime import datetime, timezone
from pathlib import Path

# Handlers que MUTAN estado (APIView + ViewSet/DRF).
WRITE_METHODS = {
    "post", "put", "patch", "delete",
    "create", "update", "partial_update", "destroy",
}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Assert every write endpoint is gated by rbac_permission (ratchet baseline)."
    )
    p.add_argument("--root", default=".", help="Repository root")
    p.add_argument("--baseline", default="qa/contracts/route_authz_baseline.json")
    p.add_argument("--output", default="qa/reports/route_authz_guard.json")
    p.add_argument(
        "--write-baseline",
        action="store_true",
        help="Bootstrap: regenera el baseline desde las vistas no gateadas actuales y sale. "
        "Solo para el primer arranque REVISADO; no lo uses para silenciar gaps nuevos.",
    )
    return p.parse_args()


def _is_view_file(path: Path) -> bool:
    name = path.name
    return name.startswith("views") or name.endswith("_views.py") or "views" in path.parts


def _iter_view_files(apps_root: Path):
    for path in sorted(apps_root.rglob("*.py")):
        parts = set(path.parts)
        if {"migrations", "__pycache__", "tests"} & parts:
            continue
        if _is_view_file(path):
            yield path


def _references_rbac(node: ast.ClassDef) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id == "rbac_permission":
            return True
        if isinstance(n, ast.Attribute) and n.attr == "rbac_permission":
            return True
    return False


def _sets_permission_decision(node: ast.ClassDef) -> bool:
    for stmt in node.body:
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "permission_classes":
                    return True
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name == "get_permissions":
            return True
    return False


def _write_methods_of(node: ast.ClassDef) -> list[str]:
    out = []
    for stmt in node.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name in WRITE_METHODS:
            out.append(stmt.name)
    return sorted(set(out))


def _base_names(node: ast.ClassDef) -> list[str]:
    names = []
    for b in node.bases:
        if isinstance(b, ast.Name):
            names.append(b.id)
        elif isinstance(b, ast.Attribute):
            names.append(b.attr)
    return names


def _scan(apps_root: Path, root: Path):
    """Devuelve (total_write_views, gated_count, ungated[list])."""
    total = 0
    gated = 0
    ungated = []
    for path in _iter_view_files(apps_root):
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        classes: dict[str, dict] = {}
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                classes[node.name] = {
                    "rbac": _references_rbac(node),
                    "writes": _write_methods_of(node),
                    "sets_perm": _sets_permission_decision(node),
                    "bases": _base_names(node),
                }

        def is_gated(cname: str, seen: set | None = None) -> bool:
            seen = seen or set()
            if cname in seen or cname not in classes:
                return False
            seen.add(cname)
            c = classes[cname]
            if c["rbac"]:
                return True
            return any(is_gated(b, seen) for b in c["bases"])

        for cname, c in classes.items():
            if not c["writes"]:
                continue
            total += 1
            if is_gated(cname):
                gated += 1
                continue
            ungated.append(
                {
                    "id": f"{rel}::{cname}",
                    "methods": c["writes"],
                    "sets_other_permission": c["sets_perm"],
                }
            )
    ungated.sort(key=lambda e: e["id"])
    return total, gated, ungated


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = _parse_args()
    root = Path(args.root).resolve()
    apps_root = root / "backend" / "src" / "apps"
    if not apps_root.is_dir():
        print(f"[qa] route authz guard: apps root no encontrado en {apps_root}")
        return 2

    total, gated, ungated = _scan(apps_root, root)

    if args.write_baseline:
        allow = {
            e["id"]: {
                "reason": "BOOTSTRAP_REVISAR: clasificar como público/webhook/kiosko o como gap real",
                "methods": e["methods"],
            }
            for e in ungated
        }
        payload = {
            "version": 1,
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "allow": allow,
            "notes": [
                "Baseline-allowlist de vistas de ESCRITURA intencionalmente NO gateadas por rbac_permission.",
                "Cada entrada exige una razón explícita. Una vista de escritura nueva sin rbac y sin entrada aquí FALLA el gate.",
                "Revisa cada entrada BOOTSTRAP_REVISAR: si es un endpoint de negocio que deberia exigir permiso, es un GAP — arregla la vista, no la baselinees.",
            ],
        }
        _write_json((root / args.baseline).resolve(), payload)
        print(f"[qa] baseline bootstrap escrito: {len(allow)} entradas en {args.baseline}")
        return 0

    baseline_path = (root / args.baseline).resolve()
    allow = {}
    if baseline_path.exists():
        allow = json.loads(baseline_path.read_text(encoding="utf-8")).get("allow", {})

    ungated_ids = {e["id"] for e in ungated}
    unbaselined = [e for e in ungated if e["id"] not in allow]
    stale = sorted(k for k in allow if k not in ungated_ids)

    status = "passed" if not unbaselined else "failed"
    report = {
        "status": status,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "summary": {
            "write_views_total": total,
            "gated_by_rbac": gated,
            "ungated_total": len(ungated),
            "allowlisted": len(ungated) - len(unbaselined),
            "unbaselined": len(unbaselined),
            "stale_baseline_entries": len(stale),
        },
        "unbaselined": unbaselined,
        "stale_baseline": stale,
        "ungated_all": ungated,
    }
    _write_json((root / args.output).resolve(), report)

    if stale:
        print(f"[qa] route authz guard: {len(stale)} entrada(s) de baseline ya no existen (limpia el baseline):")
        for k in stale:
            print(f"[qa]   stale: {k}")

    if unbaselined:
        print("[qa] route authz guard failed")
        for e in unbaselined:
            tag = "fija permission sin rbac" if e["sets_other_permission"] else "SIN ningún permiso"
            print(f"[qa] - escritura sin rbac_permission ni baseline: {e['id']} "
                  f"({','.join(e['methods'])}; {tag})")
        return 1

    print(f"[qa] route authz guard passed "
          f"(escrituras: {total}, gateadas rbac: {gated}, allowlisted: {len(ungated)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
