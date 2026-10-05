from __future__ import annotations

import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "qa" / "forensic_closure_guard.py"
NOW = "2026-08-18T19:00:00+00:00"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
    return proc.stdout.strip()


def make_fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    root = tmp_path / "repo"
    reports = root / "reports"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "qa@example.test")
    git(root, "config", "user.name", "QA")

    bugs = """# Bugs\n\n### BUG-000 — plantilla\n- **Estado:** ABIERTO / CERRADO\n\n### BUG-001 — resuelto\n- **Estado:** CERRADO\n"""
    (root / "BUGS.md").write_text(bugs, encoding="utf-8")
    audit_rows = [f"| U{i} — unit | HECHO | ok |" for i in range(1, 31)]
    audit_rows += [f"| L{i} — lens | HECHO | ok |" for i in range(1, 6)]
    (root / "AUDITORIA_LOG.md").write_text("\n".join(audit_rows), encoding="utf-8")
    (root / "AUDITORIA.md").write_text("# Informe\n\n## Riesgos residuales\n\n- Requiere visto bueno legal.\n", encoding="utf-8")

    contract = {
        "version": 1,
        "manifest": {
            "path": "run_manifest.json",
            "commit_fields": ["commit"],
            "max_age_hours": 24,
            "required_status": "passed",
            "required_gates": ["setup", "gate1", "gate2", "gate3"],
        },
        "required_reports": ["migration_rehearsal_summary.json", "production_preflight.json"],
        "junit_reports": ["pytest.xml"],
        "allowed_skips": ["suite.Optional::test_model"],
        "evidence_groups": {
            "browser": ["browser.json"],
            "roles": ["roles.json"],
        },
        "bugs_file": "BUGS.md",
        "audit_log_file": "AUDITORIA_LOG.md",
        "expected_units": 30,
        "expected_lenses": 5,
        "closed_matrix_status": "HECHO",
        "residual_risk_file": "AUDITORIA.md",
        "residual_risk_headings": ["riesgos residuales"],
    }
    write_json(root / "contract.json", contract)
    for name in ["migration_rehearsal_summary.json", "production_preflight.json", "browser.json", "roles.json"]:
        write_json(reports / name, {"status": "passed"})
    (reports / "pytest.xml").write_text(
        '<testsuites><testsuite tests="2" failures="0" errors="0" skipped="1">'
        '<testcase classname="suite.Core" name="test_ok" />'
        '<testcase classname="suite.Optional" name="test_model"><skipped /></testcase>'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture")
    head = git(root, "rev-parse", "HEAD")
    write_json(
        reports / "run_manifest.json",
        {
            "commit": head,
            "run_started_at": "2026-08-18T18:00:00+00:00",
            "run_finished_at": "2026-08-18T18:30:00+00:00",
            "run_status": "passed",
            "gates": {name: "passed" for name in ("setup", "gate1", "gate2", "gate3")},
        },
    )
    return root, reports, head


def run_guard(root: Path, *, require_clean: bool = False) -> subprocess.CompletedProcess[str]:
    cmd = [
        "python3",
        str(GUARD),
        "--root",
        str(root),
        "--contract",
        "contract.json",
        "--reports-dir",
        "reports",
        "--output",
        "result.json",
        "--now",
        NOW,
    ]
    if require_clean:
        cmd.append("--require-clean")
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def test_passes_complete_fixture_and_is_reproducible(tmp_path: Path) -> None:
    root, _, _ = make_fixture(tmp_path)

    first = run_guard(root)
    first_bytes = (root / "result.json").read_bytes()
    second = run_guard(root)

    assert first.returncode == second.returncode == 0
    assert (root / "result.json").read_bytes() == first_bytes
    assert json.loads(first_bytes)["status"] == "passed"


def test_fails_stale_wrong_commit_failed_report_and_unapproved_skip(tmp_path: Path) -> None:
    root, reports, _ = make_fixture(tmp_path)
    manifest = json.loads((reports / "run_manifest.json").read_text(encoding="utf-8"))
    manifest["commit"] = "deadbeef"
    manifest["run_finished_at"] = "2026-08-16T18:30:00+00:00"
    write_json(reports / "run_manifest.json", manifest)
    write_json(reports / "production_preflight.json", {"status": "failed"})
    (reports / "pytest.xml").write_text(
        '<testsuite tests="1" failures="0" errors="0" skipped="1">'
        '<testcase classname="suite.Other" name="test_skip"><skipped /></testcase></testsuite>',
        encoding="utf-8",
    )

    proc = run_guard(root)
    report = json.loads((root / "result.json").read_text(encoding="utf-8"))

    assert proc.returncode == 1
    checks = {row["check"] for row in report["issues"]}
    assert {"manifest.commit", "manifest.freshness", "required_report", "junit.skip"} <= checks


def test_fails_open_bug_incomplete_matrix_missing_evidence_and_risks(tmp_path: Path) -> None:
    root, reports, _ = make_fixture(tmp_path)
    with (root / "BUGS.md").open("a", encoding="utf-8") as stream:
        stream.write("\n### BUG-049 — pendiente\n- **Estado:** EN PROGRESO\n")
    text = (root / "AUDITORIA_LOG.md").read_text(encoding="utf-8")
    (root / "AUDITORIA_LOG.md").write_text(text.replace("| U30 — unit | HECHO |", "| U30 — unit | EN-CURSO |"), encoding="utf-8")
    (root / "AUDITORIA.md").write_text("# Informe sin sección requerida\n", encoding="utf-8")
    (reports / "browser.json").unlink()

    proc = run_guard(root)
    report = json.loads((root / "result.json").read_text(encoding="utf-8"))

    assert proc.returncode == 1
    checks = {row["check"] for row in report["issues"]}
    assert {"bugs", "matrix", "evidence", "residual_risks"} <= checks


def test_require_clean_blocks_dirty_or_untracked_worktree(tmp_path: Path) -> None:
    root, _, _ = make_fixture(tmp_path)
    (root / "untracked.txt").write_text("dirty", encoding="utf-8")

    proc = run_guard(root, require_clean=True)
    report = json.loads((root / "result.json").read_text(encoding="utf-8"))

    assert proc.returncode == 1
    assert report["observed"]["worktree_clean"] is False
    assert any(row["check"] == "git.clean" for row in report["issues"])
