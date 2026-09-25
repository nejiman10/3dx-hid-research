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
from threedx_report10.matrix_probe import evaluate_phase, matrix_success, summarize_capture
from threedx_report10.cli import _grade_receiver_input, _matrix_phases
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
    profile = document.get("profile")
    success = document.get("success") is True
    if profile in ("handle", "transition", "smoke", "core", "exhaustive"):
        planned = _matrix_phases(profile)
        expected_names = [item["name"] for item in planned]
        recorded_names = [item.get("name") for item in phases]
        if recorded_names != expected_names[:len(phases)]:
            errors.append("required phase sequence missing or changed")
        if success and recorded_names != expected_names:
            errors.append("successful audit has missing phases")
        if document.get("planned_phase_names") != expected_names:
            errors.append("planned phase names contradict profile")
        if document.get("required_phase_count") != len(planned):
            errors.append("required phase count contradicts profile")
    else:
        errors.append("missing or invalid matrix profile")
    if not phases:
        errors.append("no phase records")
    if profile == "transition":
        for phase in phases:
            if phase.get("mapping_wire_value") != "0x2f" or phase.get("capture_interrupted"):
                continue
            for field in ("set_feature_started_monotonic", "set_feature_finished_monotonic",
                          "before_requested_motion_started_monotonic",
                          "before_requested_motion_finished_monotonic",
                          "before_requested_motion_raw_reports",
                          "before_requested_motion_key_events", "motion_requested_monotonic",
                          "post_motion_input_requested_monotonic"):
                if field not in phase:
                    errors.append(f"{phase.get('name')}: missing transition timing/capture {field}")
            raw = phase.get("before_requested_motion_raw_reports")
            if isinstance(raw, list):
                if phase.get("before_requested_motion_summary") != summarize_capture(raw, 0x40):
                    errors.append(f"{phase.get('name')}: early summary contradicts raw capture")
            stamps = [phase.get(key) for key in (
                "set_feature_started_monotonic", "set_feature_finished_monotonic",
                "before_requested_motion_started_monotonic",
                "before_requested_motion_finished_monotonic", "motion_requested_monotonic",
                "post_motion_input_requested_monotonic")]
            if not all(isinstance(value, (int, float)) for value in stamps) or stamps != sorted(stamps):
                errors.append(f"{phase.get('name')}: transition timestamps are missing or out of order")
    if not success and not document.get("failure"):
        errors.append("unsuccessful audit lacks failure reason")
    requested = document.get("requested_presses_per_phase", 0)
    for index, phase in enumerate(phases):
        name = phase.get("name", "unnamed")
        for field in ("physical_button", "report10_hex", "required_presses",
                      "raw_reports", "key_events", "phase_result"):
            if field not in phase:
                errors.append(f"{name}: missing {field}")
        calculated = evaluate_phase(phase)
        for field in ("phase_result", "observed_expected_presses", "observed_expected_releases", "unexpected_input"):
            if phase.get(field) != calculated[field]:
                errors.append(f"{name}: {field} contradicts raw capture")
        if success and phase.get("required", True) and phase.get("phase_result") != "PASS":
            errors.append(f"{name}: required phase did not PASS")
        if phase.get("phase_result") == "PASS" and not phase.get("transfer_wait_completed"):
            errors.append(f"{name}: transfer wait failed")
        if phase.get("phase_result") == "PASS" and phase.get("unexpected_input"):
            errors.append(f"{name}: unexpected bitmap/input")
        if phase.get("negative_control"):
            adjacent_pass = bool(index > 0 and index + 1 < len(phases)
                and phases[index - 1].get("phase_result") == "PASS"
                and phases[index + 1].get("phase_result") == "PASS"
                and phases[index - 1].get("mapping_wire_value") == "0x29"
                and phases[index + 1].get("mapping_wire_value") == "0x29")
            if phase.get("phase_result") == "PASS" and phase.get("positive_controls_passed") != adjacent_pass:
                errors.append(f"{name}: positive-control flag contradicts adjacent phases")
            if (phase.get("phase_result") == "PASS" and
                    (not phase.get("positive_controls_passed") or not phase.get("activity_confirmed")
                     or not phase.get("observation_window_complete"))):
                errors.append(f"{name}: negative control incomplete")
        elif phase.get("phase_result") == "PASS" and phase.get("required", True):
            if not phase.get("expected_input_complete"):
                errors.append(f"{name}: expected_input_complete false")
            if (phase.get("observed_expected_presses", 0) < requested
                    or phase.get("observed_expected_releases", 0) < requested):
                errors.append(f"{name}: specified press/release count unmet")
    if success and not all(document.get(k) for k in (
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


def validate_direct6(document: dict) -> list[str]:
    errors = []
    for field in ("tool_git_commit", "started_at", "finished_at", "transport",
                  "vid", "pid", "hid_descriptor_sha256", "device", "input_hidraw",
                  "event_paths", "baseline_report10_hex", "test_report10_hex",
                  "requested_presses_per_phase"):
        if not document.get(field):
            errors.append(f"missing direct6 context: {field}")
    try:
        baseline = bytes.fromhex(document["baseline_report10_hex"])
        test = bytes.fromhex(document["test_report10_hex"])
        slot = int(document["slot"])
        if (len(baseline) != 32 or len(test) != 32 or baseline[0] != 0x10
                or test[0] != 0x10 or not 1 <= slot <= 7
                or test[18 + slot] != 0x0f
                or any(a != b for i, (a, b) in enumerate(zip(baseline, test))
                       if i != 18 + slot)):
            errors.append("direct6 report differs outside the selected mapping byte")
    except (KeyError, ValueError, TypeError, IndexError):
        errors.append("invalid direct6 reports or slot")
        baseline = test = b""
    phases = document.get("phases", [])
    if [p.get("phase") for p in phases] != ["known-before", "code6", "known-after"]:
        errors.append("direct6 phase sequence incomplete")
    requested = document.get("requested_presses_per_phase")
    code = document.get("known_evdev_code")
    if not isinstance(requested, int) or requested < 10 or not isinstance(code, int):
        errors.append("invalid direct6 control count or event code")
    for phase in phases:
        name = phase.get("phase", "unnamed")
        expected = test if name == "code6" else baseline
        if expected and phase.get("report10_hex") != expected.hex(" "):
            errors.append(f"{name}: sent report contradicts plan")
        for field in ("set_feature_started_at", "set_feature_finished_at", "ioctl_result",
                      "transfer_wait_raw_reports", "transfer_wait_key_events",
                      "raw_reports", "key_events", "capture_started_at", "capture_finished_at"):
            if field not in phase:
                errors.append(f"{name}: missing {field}")
        stamps = [phase.get(field) for field in (
            "set_feature_started_monotonic", "set_feature_finished_monotonic",
            "capture_started_monotonic", "capture_finished_monotonic")]
        if not all(isinstance(v, (int, float)) for v in stamps) or stamps != sorted(stamps):
            errors.append(f"{name}: timestamps missing or out of order")
        if name.startswith("known-") and isinstance(code, int) and isinstance(requested, int):
            events = phase.get("key_events", [])
            presses = sum(e.get("code") == code and e.get("value") == 1 for e in events)
            releases = sum(e.get("code") == code and e.get("value") == 0 for e in events)
            if phase.get("known_presses") != presses or phase.get("known_releases") != releases:
                errors.append(f"{name}: control counts contradict evdev")
            confirmed = (phase.get("ioctl_result") == 32
                         and phase.get("transfer_wait_completed") is True
                         and presses >= requested and releases >= requested)
            if phase.get("known_input_confirmed") is not confirmed:
                errors.append(f"{name}: control confirmation contradicts capture")
    if document.get("success"):
        if (len(phases) != 3 or document.get("failure") is not None
                or not document.get("restore_attempted") or not document.get("baseline_restored")
                or not document.get("baseline_operation_confirmed")
                or not all(p.get("ioctl_result") == 32 and p.get("transfer_wait_completed")
                           and p.get("capture_complete") for p in phases)
                or not phases[0].get("known_input_confirmed")
                or not phases[2].get("known_input_confirmed")):
            errors.append("direct6 success contradicts capture or restoration")
    elif not document.get("failure"):
        errors.append("unsuccessful direct6 audit lacks failure reason")
    return errors


def validate_receiver_input(document: dict) -> list[str]:
    errors = []
    for field in ("tool_git_commit", "started_at", "finished_at", "input_hidraw",
                  "event_paths", "hid_descriptor_sha256", "raw_reports", "key_events",
                  "required_presses"):
        if field not in document or document[field] is None:
            errors.append(f"missing receiver input field: {field}")
    if errors:
        return errors
    if (not document.get("success") and document.get("failure")
            and "raw_left_press_transitions" not in document
            and "evdev_left_press_release_by_path" not in document
            and not document["raw_reports"] and not document["key_events"]):
        return errors
    count, paths, confirmed = _grade_receiver_input(
        document["raw_reports"], document["key_events"], document["required_presses"])
    if document.get("raw_left_press_transitions") != count:
        errors.append("raw transition count contradicts capture")
    if document.get("evdev_left_press_release_by_path") != paths:
        errors.append("evdev counts contradict capture")
    if document.get("success") is not confirmed:
        errors.append("receiver input success contradicts capture")
    return errors


def validate_receiver_cycle(document: dict) -> list[str]:
    errors = []
    records = document.get("records", {})
    required = ("before_slots", "before_input", "unpair", "pair",
                "failed_after_input", "after_slots", "after_input")
    if not isinstance(records, dict) or any(key not in records for key in required):
        return ["receiver cycle lacks one or more source audits"]
    for name in ("before_input", "failed_after_input", "after_input"):
        errors.extend(f"{name}: {item}" for item in validate_receiver_input(records[name]))
    before = records["before_slots"]["slots"]
    after = records["after_slots"]["slots"]
    unpair = records["unpair"]
    pair = records["pair"]
    occupied_before = [item["slot"] for item in before if item["occupied"]]
    occupied_after = [item["slot"] for item in after if item["occupied"]]
    if len(occupied_before) != 1 or len(occupied_after) != 1:
        errors.append("cycle requires one occupied slot before and after")
    if occupied_before and (unpair.get("slot") != occupied_before[0]
                            or not unpair.get("target_empty_confirmed")):
        errors.append("unpair target or empty-slot result contradicts before snapshot")
    new_slots = [item.get("slot") for item in pair.get("new_slots", [])]
    if occupied_after and new_slots != occupied_after:
        errors.append("pair new slot contradicts after snapshot")
    if not all(records[name].get("success") for name in
               ("before_input", "unpair", "pair", "after_input")):
        errors.append("cycle success lacks input or management success")
    if records["failed_after_input"].get("success"):
        errors.append("failed first post-pair capture was rewritten as success")
    if not pair.get("stop_sent") or not unpair.get("unpair_request_attempted"):
        errors.append("management packet sequence incomplete")
    moments = [records["before_input"].get("started_at"),
               unpair.get("started_at"), pair.get("started_at"),
               records["failed_after_input"].get("started_at"),
               records["after_input"].get("started_at")]
    if not all(isinstance(value, str) for value in moments) or moments != sorted(moments):
        errors.append("cycle timestamps missing or out of order")
    if document.get("success") is not (not errors):
        errors.append("cycle success contradicts component audits")
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
        if (".git" in relative.parts or relative.parts[0] == "release"
                or relative.parts[:2] == ("evidence", "source-private-not-in-repository")
                or not path.is_file()):
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
        if document.get("schema") == "c658-report03-matrix/v3":
            errors.extend(f"{relative}: {item}" for item in validate_matrix(document))
        if document.get("schema") == "c658-direct6-controlled/v1":
            errors.extend(f"{relative}: {item}" for item in validate_direct6(document))
        if document.get("schema") == "c652-physical-input/v1":
            errors.extend(f"{relative}: {item}" for item in validate_receiver_input(document))
        if document.get("schema") == "c652-receiver-repair-cycle/v1":
            errors.extend(f"{relative}: {item}" for item in validate_receiver_cycle(document))
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
    if document.get("schema") == "c658-report03-matrix/v3":
        errors.extend(f"{path}: {item}" for item in validate_matrix(document))
    if document.get("schema") == "c658-direct6-controlled/v1":
        errors.extend(f"{path}: {item}" for item in validate_direct6(document))
    if document.get("schema") == "c652-physical-input/v1":
        errors.extend(f"{path}: {item}" for item in validate_receiver_input(document))
    if document.get("schema") == "c652-receiver-repair-cycle/v1":
        errors.extend(f"{path}: {item}" for item in validate_receiver_cycle(document))
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
