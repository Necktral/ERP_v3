#!/usr/bin/env python3
"""Sella una corrida del programa de cartografía (solo stdlib).

- Copia reports/run_manifest.json a run_manifest.raw.json (el que emitió el runner).
- Reescribe reports/run_manifest.json agregando commit/tree/rama/estado del worktree,
  los datos de corrida.env, los pasos de steps.tsv y la frescura de cada reporte
  (mtime >= inicio de la corrida), que forensic_closure_guard no verifica.
- Escribe SHA256SUMS (formato `sha256sum -c`) de todos los archivos de la corrida.

Uso: sellar.py --run <dir_corrida> --root <raiz_del_repo>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def read_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                data[key.strip()] = value.strip()
    return data


def read_steps(path: Path) -> list[dict[str, object]]:
    steps: list[dict[str, object]] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                steps.append({"paso": parts[0], "rc": int(parts[1]), "segundos": int(parts[2])})
    return steps


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--root", required=True)
    args = parser.parse_args()

    run = Path(args.run).resolve()
    root = Path(args.root).resolve()
    reports = run / "reports"
    corrida = read_env(run / "corrida.env")
    start_epoch = float(corrida.get("inicio_epoch", "0") or 0)

    manifest_path = reports / "run_manifest.json"
    raw: dict[str, object] = {}
    if manifest_path.exists():
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        (run / "run_manifest.raw.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    stale: list[str] = []
    fresh = 0
    for item in sorted(reports.rglob("*")):
        if item.is_file() and item.name != "run_manifest.json":
            if item.stat().st_mtime + 1 < start_epoch:
                stale.append(str(item.relative_to(run)))
            else:
                fresh += 1

    steps = read_steps(run / "steps.tsv")
    enriched = dict(raw)
    enriched.update(
        {
            "commit": git(root, "rev-parse", "HEAD"),
            "tree": git(root, "rev-parse", "HEAD^{tree}"),
            "branch": git(root, "rev-parse", "--abbrev-ref", "HEAD"),
            "worktree_porcelain": git(root, "status", "--porcelain").splitlines(),
            "erpbl_corrida": corrida,
            "erpbl_pasos": steps,
            "erpbl_pasos_rojos": [s["paso"] for s in steps if s["rc"] != 0],
            "erpbl_frescura": {"reportes_frescos": fresh, "reportes_viejos": stale},
            "erpbl_sellado_utc": datetime.now(timezone.utc).isoformat(),
        }
    )
    reports.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(enriched, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    sums = run / "SHA256SUMS"
    lines = [
        f"{sha256_file(item)}  {item.relative_to(run)}"
        for item in sorted(run.rglob("*"))
        if item.is_file() and item != sums
    ]
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"sellado: {run}")
    print(f"  commit={enriched['commit']} archivos={len(lines)} reportes_frescos={fresh} viejos={len(stale)}")
    print(f"  pasos={len(steps)} rojos={len(enriched['erpbl_pasos_rojos'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
