#!/usr/bin/env python3
"""Validate privacy and the semantics of self-contained research audits."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk/python/src"))
from threedx_report10.matrix_probe import evaluate_phase, matrix_success
from threedx_report10.cli import _matrix_phases
PRIVATE = re.compile("/" + "home/|/" + "Users/|/" + "workspace/|(?:08|4[3-7]) 59(?: [0-9a-fA-F]{2}){6}")
VENDOR_BINARIES = {".msi", ".dll", ".exe", ".sys", ".cab"}
SOURCE = re.compile(r"^- \[CONFIRMED\].*\(source: ([^)]+)\)$")


def validate_matrix(document: dict) -> list[str]:
    errors = []
    for field in ("tool_git_commit", "started_at", "finished_at", "transport",
                  "vid", "pid", "hid_descriptor_sha256", "subcommand", "device",
                  "input_hidraw", "event", "baseline_report10_hex"):
        if not document.get(field):
            errors.append(f"missing audit context: {field}")
    if document.get("transport") not in (None, "wired", "receiver"):
        errors.append("invalid transport")
    phases = document.get("phases", [])
    if "stages" in document and "selected_slot" in document:
        planned = _matrix_phases(tuple(document["stages"]), document["selected_slot"])
        if [item.get("name") for item in phases] != [item["name"] for item in planned]:
            errors.append("required phase sequence missing or changed")
    if len(phases) != document.get("required_phase_count") or not phases:
        errors.append("required phases missing")
    requested = document.get("requested_presses_per_phase", 0)
    for phase in phases:
        name = phase.get("name", "unnamed")
        for field in ("physical_button", "report10_hex", "required_presses",
                      "raw_reports", "key_events", "phase_result"):
            if field not in phase:
                errors.append(f"{name}: missing {field}")
        calculated = evaluate_phase(phase)
        for field in ("phase_result", "observed_expected_presses", "observed_expected_releases", "unexpected_input"):
            if phase.get(field) != calculated[field]:
                errors.append(f"{name}: {field} contradicts raw capture")
        if phase.get("required", True) and phase.get("phase_result") != "PASS":
            errors.append(f"{name}: required phase did not PASS")
        if not phase.get("transfer_wait_completed"):
            errors.append(f"{name}: transfer wait failed")
        if phase.get("unexpected_input"):
            errors.append(f"{name}: unexpected bitmap/input")
        if phase.get("negative_control"):
            if not phase.get("positive_controls_passed") or not phase.get("activity_confirmed") or not phase.get("observation_window_complete"):
                errors.append(f"{name}: negative control incomplete")
        elif phase.get("required", True):
            if not phase.get("expected_input_complete"):
                errors.append(f"{name}: expected_input_complete false")
            if (phase.get("observed_expected_presses", 0) < requested
                    or phase.get("observed_expected_releases", 0) < requested):
                errors.append(f"{name}: specified press/release count unmet")
    if not all(document.get(k) for k in (
        "baseline_restored", "baseline_transfer_wait_completed", "baseline_operation_confirmed"
    )):
        errors.append("baseline restoration or operation failed")
    code = document.get("baseline_expected_evdev_code")
    by_path: dict[str, list[int]] = {}
    for event in document.get("baseline_check_key_events", []):
        if event.get("code") != code:
            continue
        pair = by_path.setdefault(str(event.get("path", "unknown")), [0, 0])
        if event.get("value") == 1:
            pair[0] += 1
        elif event.get("value") == 0:
            pair[1] += 1
    confirmed = any(pair[0] >= requested and pair[1] >= requested
                    for pair in by_path.values()) if isinstance(code, int) and requested else False
    if document.get("baseline_operation_confirmed") != confirmed:
        errors.append("baseline operation flag contradicts evdev capture")
    if document.get("success") != matrix_success(document):
        errors.append("overall success contradicts phase or restoration results")
    return errors


def validate_claims(spec: str, root: Path = ROOT) -> list[str]:
    errors = []
    for line in spec.splitlines():
        if "[CONFIRMED]" not in line:
            continue
        match = SOURCE.fullmatch(line)
        if not match or not (root / match.group(1)).is_file():
            errors.append(f"CONFIRMED claim lacks an existing source: {line[:90]}")
    return errors


def validate_repository(root: Path = ROOT) -> list[str]:
    errors = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if ".git" in relative.parts or relative.parts[0] == "release" or not path.is_file():
            continue
        if path.suffix.lower() in VENDOR_BINARIES:
            errors.append(f"vendor binary present: {relative}")
        if path.suffix == ".pyc":
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if PRIVATE.search(content):
            errors.append(f"private path or ID present: {relative}")
        if path.suffix != ".json":
            continue
        try:
            document = json.loads(content)
        except json.JSONDecodeError as exc:
            errors.append(f"invalid JSON {relative}: {exc}")
            continue
        if document.get("schema") == "c658-report03-matrix/v2":
            errors.extend(f"{relative}: {item}" for item in validate_matrix(document))
        for ref in document.get("evidence_files", []):
            candidate = (root / ref).resolve()
            if root.resolve() not in candidate.parents or not candidate.is_file():
                errors.append(f"missing evidence file: {ref}")
    spec = root / "SPEC.md"
    if not spec.is_file():
        errors.append("SPEC.md missing")
    else:
        errors.extend(validate_claims(spec.read_text(encoding="utf-8"), root))
    return errors


def validate_audit(path: Path) -> list[str]:
    errors = []
    try:
        content = path.read_text(encoding="utf-8")
        document = json.loads(content)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{path}: unreadable JSON: {exc}"]
    if PRIVATE.search(content):
        errors.append(f"{path}: private path or ID present")
    if document.get("schema") == "c658-report03-matrix/v2":
        errors.extend(f"{path}: {item}" for item in validate_matrix(document))
    if document.get("schema", "").startswith("c652-experimental-"):
        for field in ("tool_git_commit", "transport", "vid", "pid", "hidraw",
                      "hid_descriptor_sha256", "subcommand", "options", "started_at",
                      "finished_at", "before", "snapshots", "failure", "success"):
            if field not in document or (field == "hid_descriptor_sha256" and not document[field]):
                errors.append(f"{path}: missing pairing audit context: {field}")
        if document.get("success") and document.get("subcommand") == "pair":
            if not document.get("new_slots") or not document.get("stop_sent"):
                errors.append(f"{path}: pairing success lacks slot/stop evidence")
        if document.get("success") and document.get("subcommand") == "unpair":
            if not document.get("target_empty_confirmed") or not document.get("after"):
                errors.append(f"{path}: unpair success lacks empty-slot evidence")
    for ref in document.get("evidence_files", []):
        candidate = (path.parent / ref).resolve()
        if path.parent.resolve() not in candidate.parents or not candidate.is_file():
            errors.append(f"{path}: missing evidence file {ref}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audits", nargs="*", type=Path, help="additional JSON audits to validate")
    args = parser.parse_args(argv)
    errors = validate_repository()
    for path in args.audits:
        errors.extend(validate_audit(path))
    for error in errors:
        print(f"validation failed: {error}", file=sys.stderr)
    if errors:
        return 1
    print("public and semantic validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
