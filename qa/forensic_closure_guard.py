#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PASS_STATUSES = {"pass", "passed", "ok", "success"}
OPEN_BUG_STATUSES = {"abierto", "en progreso"}
BUG_HEADER_RE = re.compile(r"^###\s+(BUG-\d+)\b", re.MULTILINE)
BUG_STATUS_RE = re.compile(r"\*\*Estado:\*\*\s*([^\n]+)", re.IGNORECASE)
MATRIX_ROW_RE = re.compile(r"^\|\s*([UL])(\d+)\s*(?:—[^|]*)?\|\s*([^|]+)\|", re.MULTILINE)
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fail closed unless the forensic campaign is certifiably complete.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--contract", default="qa/contracts/forensic_closure_contract.json")
    parser.add_argument("--reports-dir", default="qa/reports/final")
    parser.add_argument("--output", default="qa/reports/forensic_closure_guard.json")
    parser.add_argument("--now", default="", help="UTC ISO-8601 clock override for deterministic tests")
    parser.add_argument("--require-clean", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("top-level JSON must be an object")
    return payload


def parse_time(raw: Any) -> datetime:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("missing ISO-8601 timestamp")
    normalized = raw.strip().replace("Z", "+00:00")
    value = datetime.fromisoformat(normalized)
    if value.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return value.astimezone(timezone.utc)


def status_passes(value: Any) -> bool:
    return str(value or "").strip().lower() in PASS_STATUSES


def git(root: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args], cwd=root, check=False, capture_output=True, text=True
    )
    return proc.returncode, (proc.stdout or "").strip()


def add(issues: list[dict[str, str]], check: str, detail: str) -> None:
    issues.append({"check": check, "detail": detail})


def check_manifest(
    *, manifest: dict[str, Any], policy: dict[str, Any], head: str, now: datetime, issues: list[dict[str, str]]
) -> dict[str, Any]:
    observed_commit = ""
    for field in policy["commit_fields"]:
        candidate = str(manifest.get(field) or "").strip()
        if candidate:
            observed_commit = candidate
            break
    if observed_commit != head:
        add(issues, "manifest.commit", f"expected {head!r}, found {observed_commit!r}")

    started: datetime | None = None
    finished: datetime | None = None
    try:
        started = parse_time(manifest.get("run_started_at"))
        finished = parse_time(manifest.get("run_finished_at"))
        if finished < started:
            add(issues, "manifest.time", "run_finished_at precedes run_started_at")
        if finished > now + timedelta(minutes=5):
            add(issues, "manifest.time", "run_finished_at is in the future")
        age = now - finished
        if age > timedelta(hours=float(policy["max_age_hours"])):
            add(issues, "manifest.freshness", f"manifest is {age.total_seconds() / 3600:.2f} hours old")
    except (TypeError, ValueError) as exc:
        add(issues, "manifest.time", str(exc))

    required_status = str(policy["required_status"])
    if str(manifest.get("run_status") or "").lower() != required_status.lower():
        add(issues, "manifest.status", f"run_status must be {required_status!r}")
    gates = manifest.get("gates")
    if not isinstance(gates, dict):
        add(issues, "manifest.gates", "gates must be an object")
        gates = {}
    for gate_name in policy["required_gates"]:
        if not status_passes(gates.get(gate_name)):
            add(issues, "manifest.gates", f"{gate_name} is not passed")
    return {
        "commit": observed_commit,
        "run_started_at": started.isoformat() if started else None,
        "run_finished_at": finished.isoformat() if finished else None,
    }


def check_json_report(path: Path, label: str, issues: list[dict[str, str]]) -> None:
    if not path.is_file():
        add(issues, label, f"missing report: {path.name}")
        return
    try:
        payload = load_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        add(issues, label, f"invalid JSON in {path.name}: {exc}")
        return
    status = payload.get("status", payload.get("gate_status", payload.get("overall_status")))
    if not status_passes(status):
        add(issues, label, f"{path.name} status is not passed: {status!r}")


def check_junit(path: Path, allowed_skips: list[str], issues: list[dict[str, str]]) -> dict[str, int]:
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    if not path.is_file():
        add(issues, "junit", f"missing JUnit report: {path.name}")
        return totals
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        add(issues, "junit", f"invalid JUnit {path.name}: {exc}")
        return totals

    suites = list(root.iter("testsuite"))
    leaf_suites = [suite for suite in suites if not list(suite.iterfind("testsuite"))]
    for suite in leaf_suites:
        for key in totals:
            totals[key] += int(suite.attrib.get(key, "0") or 0)
    if totals["failures"] or totals["errors"]:
        add(issues, "junit", f"{path.name} has {totals['failures']} failures and {totals['errors']} errors")

    observed_skips = 0
    for case in root.iter("testcase"):
        if case.find("skipped") is None:
            continue
        observed_skips += 1
        test_id = f"{case.attrib.get('classname', '')}::{case.attrib.get('name', '')}"
        if not any(fnmatch.fnmatchcase(test_id, pattern) for pattern in allowed_skips):
            add(issues, "junit.skip", f"unapproved skip in {path.name}: {test_id}")
    if observed_skips != totals["skipped"]:
        add(issues, "junit", f"{path.name} declares {totals['skipped']} skips but contains {observed_skips}")
    return totals


def check_bugs(path: Path, issues: list[dict[str, str]]) -> int:
    if not path.is_file():
        add(issues, "bugs", f"missing file: {path}")
        return 0
    text = path.read_text(encoding="utf-8")
    matches = list(BUG_HEADER_RE.finditer(text))
    open_count = 0
    for idx, match in enumerate(matches):
        bug_id = match.group(1)
        if bug_id == "BUG-000":
            continue
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        status_match = BUG_STATUS_RE.search(text[match.end() : end])
        status = str(status_match.group(1) if status_match else "").strip().lower()
        if status in OPEN_BUG_STATUSES:
            open_count += 1
            add(issues, "bugs", f"{bug_id} remains {status.upper()}")
        elif not status:
            add(issues, "bugs", f"{bug_id} has no status")
    return open_count


def check_matrix(path: Path, expected_units: int, expected_lenses: int, closed: str, issues: list[dict[str, str]]) -> dict[str, int]:
    counts = {"units": 0, "lenses": 0, "closed": 0}
    if not path.is_file():
        add(issues, "matrix", f"missing file: {path}")
        return counts
    rows: dict[tuple[str, int], str] = {}
    for kind, number, status in MATRIX_ROW_RE.findall(path.read_text(encoding="utf-8")):
        key = (kind, int(number))
        if key in rows:
            add(issues, "matrix", f"duplicate row: {kind}{number}")
        rows[key] = status.strip()
    units = {number for (kind, number) in rows if kind == "U"}
    lenses = {number for (kind, number) in rows if kind == "L"}
    counts["units"], counts["lenses"] = len(units), len(lenses)
    if units != set(range(1, expected_units + 1)):
        add(issues, "matrix", f"expected U1..U{expected_units}, found {sorted(units)}")
    if lenses != set(range(1, expected_lenses + 1)):
        add(issues, "matrix", f"expected L1..L{expected_lenses}, found {sorted(lenses)}")
    for (kind, number), status in sorted(rows.items()):
        if status != closed:
            add(issues, "matrix", f"{kind}{number} is {status!r}, expected {closed!r}")
        else:
            counts["closed"] += 1
    return counts


def normalize_heading(value: str) -> str:
    table = str.maketrans("áéíóúüñ", "aeiouun")
    return value.lower().translate(table).strip()


def check_risks(path: Path, accepted_headings: list[str], issues: list[dict[str, str]]) -> bool:
    if not path.is_file():
        add(issues, "residual_risks", f"missing file: {path}")
        return False
    text = path.read_text(encoding="utf-8")
    headings = list(HEADING_RE.finditer(text))
    accepted = {normalize_heading(item) for item in accepted_headings}
    for idx, heading in enumerate(headings):
        if normalize_heading(heading.group(1)) not in accepted:
            continue
        end = headings[idx + 1].start() if idx + 1 < len(headings) else len(text)
        body = text[heading.end() : end].strip()
        if body:
            return True
        add(issues, "residual_risks", "residual risk section is empty")
        return False
    add(issues, "residual_risks", "residual risk heading not found")
    return False


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    reports_dir = (root / args.reports_dir).resolve()
    output = (root / args.output).resolve()
    issues: list[dict[str, str]] = []
    observed: dict[str, Any] = {}

    try:
        contract = load_json((root / args.contract).resolve())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        contract = {}
        add(issues, "contract", str(exc))

    rc, head = git(root, "rev-parse", "HEAD")
    if rc != 0 or not head:
        add(issues, "git", "cannot resolve HEAD")

    try:
        now = parse_time(args.now) if args.now else datetime.now(tz=timezone.utc)
    except ValueError as exc:
        add(issues, "clock", str(exc))
        now = datetime.now(tz=timezone.utc)

    manifest_policy = contract.get("manifest", {})
    manifest_path = reports_dir / str(manifest_policy.get("path", "run_manifest.json"))
    try:
        manifest = load_json(manifest_path)
        observed["manifest"] = check_manifest(
            manifest=manifest, policy=manifest_policy, head=head, now=now, issues=issues
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        add(issues, "manifest", f"cannot load {manifest_path.name}: {exc}")

    for filename in contract.get("required_reports", []):
        check_json_report(reports_dir / filename, "required_report", issues)

    junit_totals: dict[str, dict[str, int]] = {}
    allowed_skips = [str(item) for item in contract.get("allowed_skips", [])]
    for filename in contract.get("junit_reports", []):
        junit_totals[filename] = check_junit(reports_dir / filename, allowed_skips, issues)
    observed["junit"] = junit_totals

    for group, candidates in sorted(contract.get("evidence_groups", {}).items()):
        passing = False
        for filename in candidates:
            path = reports_dir / filename
            try:
                passing = status_passes(load_json(path).get("status"))
            except (OSError, ValueError, json.JSONDecodeError):
                passing = False
            if passing:
                break
        if not passing:
            add(issues, "evidence", f"no passing evidence for {group}")

    observed["open_bugs"] = check_bugs(root / str(contract.get("bugs_file", "BUGS.md")), issues)
    observed["matrix"] = check_matrix(
        root / str(contract.get("audit_log_file", "docs/AUDITORIA_LOG.md")),
        int(contract.get("expected_units", 30)),
        int(contract.get("expected_lenses", 5)),
        str(contract.get("closed_matrix_status", "HECHO")),
        issues,
    )
    observed["residual_risks_documented"] = check_risks(
        root / str(contract.get("residual_risk_file", "docs/AUDITORIA_FORENSE_2026.md")),
        [str(item) for item in contract.get("residual_risk_headings", [])],
        issues,
    )

    if args.require_clean:
        rc, dirty = git(root, "status", "--porcelain", "--untracked-files=all")
        if rc != 0:
            add(issues, "git.clean", "cannot inspect worktree")
        elif dirty:
            add(issues, "git.clean", "worktree is not clean")
        observed["worktree_clean"] = rc == 0 and not dirty

    issues.sort(key=lambda row: (row["check"], row["detail"]))
    report = {
        "status": "failed" if issues else "passed",
        "contract_version": contract.get("version"),
        "evaluated_commit": head,
        "evaluation_clock": now.isoformat(),
        "require_clean": bool(args.require_clean),
        "observed": observed,
        "issues": issues,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if issues:
        print(f"[qa] forensic closure guard failed: {len(issues)} issue(s)")
        for issue in issues:
            print(f"[qa] - {issue['check']}: {issue['detail']}")
        return 1
    print("[qa] forensic closure guard passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
