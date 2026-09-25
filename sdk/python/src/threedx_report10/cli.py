"""Command-line hardware tool connected to the Report 0x10 SDK."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import math
import os
import selectors
import sys
import tempfile
import time
import subprocess
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .input_events import (
    BTN_EXTRA,
    BTN_LEFT,
    BTN_MIDDLE,
    BTN_RIGHT,
    BTN_SIDE,
    KEY_NAMES,
    input_event_nodes_for_hidraw,
    wait_for_key_press,
)
from .linux_hidraw import (
    HidrawDevice,
    discover_report03_inputs,
    discover_receiver_c658_handles,
    discover_wired_c658,
    enumerate_hidraw,
    validate_report10_target,
    _read_descriptor,
)
from .hold_open import run_wired_hold_open
from .matrix_probe import (
    MultiInputCapture,
    count_expected_press_transitions,
    evaluate_phase,
    matrix_success,
    summarize_capture,
)
from .receiver import (
    PAIR_START,
    PAIR_STOP,
    build_unpair_packet,
    discover_receiver_management,
    newly_occupied_slots,
    read_receiver_slots,
    set_pairing_mode,
    unpair_slot,
    validate_receiver_management,
)
from .read_audit import audit_read_paths
from .report03 import REPORT03_MASKS, Report03Reader
from .report10 import (
    ButtonMapping,
    DirectAction,
    LiftDetection,
    PollingRate,
    Report10Config,
    WheelMode,
)
from .send_cache import Report10SendCache

DIRECT_TOKENS = {
    "left": DirectAction.HID_MOUSE_LEFT,
    "right": DirectAction.HID_MOUSE_RIGHT,
    "middle": DirectAction.HID_MOUSE_MIDDLE_OR_WHEEL_BUTTON,
    "backward": DirectAction.HID_MOUSE_BACKWARD,
    "forward": DirectAction.HID_MOUSE_FORWARD,
    "unknown6": DirectAction.UNKNOWN_DIRECT_CODE_6,
}

EXPECTED_LINUX_CODES = {
    DirectAction.HID_MOUSE_LEFT: BTN_LEFT,
    DirectAction.HID_MOUSE_RIGHT: BTN_RIGHT,
    DirectAction.HID_MOUSE_MIDDLE_OR_WHEEL_BUTTON: BTN_MIDDLE,
    DirectAction.HID_MOUSE_BACKWARD: BTN_SIDE,
    DirectAction.HID_MOUSE_FORWARD: BTN_EXTRA,
}

BASELINE_SLOT_ACTIONS = (
    DirectAction.HID_MOUSE_LEFT,
    DirectAction.HID_MOUSE_RIGHT,
    DirectAction.HID_MOUSE_MIDDLE_OR_WHEEL_BUTTON,
    DirectAction.HID_MOUSE_MIDDLE_OR_WHEEL_BUTTON,
    DirectAction.HID_MOUSE_FORWARD,
    DirectAction.HID_MOUSE_BACKWARD,
    DirectAction.HID_MOUSE_MIDDLE_OR_WHEEL_BUTTON,
)

# C658 physical controls in the recovered seven-entry table. Slot 7's Radial
# association is correlation evidence; it does not name direct action code 6.
PHYSICAL_BUTTON_NAMES = (
    "left",
    "right",
    "middle",
    "wheel",
    "forward",
    "back",
    "radial",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit_identity(path: str, command: str, options: dict[str, object],
                    transport: str = "receiver", pid: str = "c652") -> dict[str, object]:
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                           stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = "unknown"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
        try:
            descriptor_hash = hashlib.sha256(_read_descriptor(fd)).hexdigest()
        finally:
            os.close(fd)
    except OSError:
        descriptor_hash = None
    return {
        "tool_git_commit": revision, "transport": transport, "vid": "256f",
        "pid": pid, "hidraw": path, "hid_descriptor_sha256": descriptor_hash,
        "subcommand": command, "options": options,
    }


def _parse_mapping(token: str) -> ButtonMapping:
    normalized = token.strip().lower()
    if normalized in DIRECT_TOKENS:
        return ButtonMapping.direct(DIRECT_TOKENS[normalized])
    if normalized.startswith("host:"):
        try:
            index = int(normalized.split(":", 1)[1], 0)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid host mapping: {token}") from exc
        try:
            return ButtonMapping.host_routed(index)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(str(exc)) from exc
    raise argparse.ArgumentTypeError(
        "mapping must be left,right,middle,backward,forward,unknown6 or host:N"
    )


def _parse_direct_action(value: str) -> DirectAction:
    try:
        return DIRECT_TOKENS[value.strip().lower()]
    except KeyError as exc:
        raise argparse.ArgumentTypeError(
            "action must be left,right,middle,backward,forward or unknown6"
        ) from exc


def _parse_buttons(value: str) -> tuple[ButtonMapping, ...]:
    parts = value.split(",")
    if len(parts) != 7:
        raise argparse.ArgumentTypeError("exactly seven comma-separated mappings are required")
    return tuple(_parse_mapping(part) for part in parts)


def _parse_lift(value: str) -> LiftDetection:
    if value.strip().lower() == "disabled":
        return LiftDetection.disabled()
    try:
        threshold = int(value, 0)
        return LiftDetection.enabled_with_threshold(threshold)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("lift must be 'disabled' or a raw byte 0..255") from exc


def _parse_host_index(value: str) -> int:
    try:
        index = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("host index must be an integer") from exc
    if not 0 <= index <= 215:
        raise argparse.ArgumentTypeError("host index must be in range 0..215")
    return index


def _config_from_args(args: argparse.Namespace) -> Report10Config:
    return Report10Config.create(
        dpi=args.dpi,
        lift_detection=args.lift,
        wheel_mode=WheelMode[args.wheel.upper()],
        buttons=args.buttons,
        polling_rate=PollingRate(args.polling),
    )


def _add_config_arguments(parser: argparse.ArgumentParser) -> None:
    baseline = Report10Config.latest_software_baseline()
    parser.add_argument("--dpi", type=int, default=baseline.dpi)
    parser.add_argument(
        "--lift",
        type=_parse_lift,
        default=LiftDetection.disabled(),
        metavar="disabled|BYTE",
        help="experimental on C658; BYTE accepts decimal or 0xNN",
    )
    parser.add_argument("--wheel", choices=("normal", "inertial"), default="normal")
    parser.add_argument("--polling", type=int, choices=(1000, 500, 250, 125), default=1000)
    parser.add_argument(
        "--buttons",
        type=_parse_buttons,
        default=baseline.buttons,
        metavar="M1,M2,M3,M4,M5,M6,M7",
        help="tokens: left,right,middle,backward,forward,unknown6,host:N",
    )


def _cmd_scan(args: argparse.Namespace) -> int:
    wired = discover_wired_c658(args.pattern)
    receiver = discover_receiver_c658_handles(args.pattern)
    management = discover_receiver_management(args.pattern)
    report03_inputs = discover_report03_inputs(args.pattern)
    rows = [
        {
            "path": str(item.path),
            "connection": connection,
            "vid": f"{item.vendor_id:04x}",
            "pid": f"{item.product_id:04x}",
            "report10_wire_length": item.feature_report_lengths.get(0x10),
            "input_report03_wire_length": item.input_report_lengths.get(0x03),
        }
        for connection, items in (
            ("wired-c658", wired),
            ("receiver-c658-handle", receiver),
            ("receiver-management", management),
            ("report03-input", report03_inputs),
        )
        for item in items
    ]
    if args.all:
        known_paths = {row["path"] for row in rows}
        rows.extend(
            {
                "path": str(item.path),
                "connection": "other-3dx-hidraw",
                "vid": f"{item.vendor_id:04x}",
                "pid": f"{item.product_id:04x}",
                "report10_wire_length": item.feature_report_lengths.get(0x10),
                "input_report03_wire_length": item.input_report_lengths.get(0x03),
            }
            for item in enumerate_hidraw(args.pattern)
            if item.vendor_id == 0x256F and str(item.path) not in known_paths
        )
    if args.json:
        print(json.dumps(rows, indent=2))
    elif not rows:
        print("No validated Report 0x10 target found.")
    else:
        for row in rows:
            print(
                f"{row['path']}  {row['connection']}  "
                f"{row['vid']}:{row['pid']}  report10={row['report10_wire_length']} "
                f"input03={row.get('input_report03_wire_length')}"
            )
    return 0 if rows else 2


def _cmd_receiver_slots(args: argparse.Namespace) -> int:
    slots = read_receiver_slots(args.device)
    document = {
        "schema": "c652-slot-snapshot/v1",
        "time": _utc_now(),
        "device": args.device,
        "operation": "GET_FEATURE 0x43..0x47",
        "write_performed": False,
        "slots": [slot.to_dict() for slot in slots],
    }
    _write_audit(args.audit, document)
    return 0


def _cmd_audit_read_paths(args: argparse.Namespace) -> int:
    if Path(args.audit).exists():
        raise RuntimeError(f"audit already exists: {args.audit}")
    document = audit_read_paths(args.device, report10_readback=args.report10_readback)
    _write_audit(args.audit, document, quiet=True)
    print(f"private audit: {args.audit}")
    return 1 if document.get("failure") else 0


def _cmd_hold_open(args: argparse.Namespace) -> int:
    print(
        "[hold-open] monitoring all wired 256f:c658 hidraw interfaces; "
        "receiver 256f:c652 nodes are excluded",
        flush=True,
    )

    def emit(event: dict[str, object]) -> None:
        print(json.dumps({"time": _utc_now(), **event}, ensure_ascii=False), flush=True)

    return run_wired_hold_open(
        pattern=args.pattern,
        poll_interval=args.poll_interval,
        once=args.once,
        emit=emit,
    )


def _frame_dict(frame) -> dict[str, object]:
    return {
        "raw_hex": frame.raw.hex(" "),
        "bitmap": f"0x{frame.bitmap:02x}",
        "previous_bitmap": f"0x{frame.previous_bitmap:02x}",
        "pressed_mask": f"0x{frame.pressed_mask:02x}",
        "released_mask": f"0x{frame.released_mask:02x}",
        "monotonic_time": frame.monotonic_time,
    }


def _cmd_monitor_report03(args: argparse.Namespace) -> int:
    if not discover_report03_inputs(args.input_hidraw):
        raise RuntimeError(f"{args.input_hidraw} does not declare Input Report 0x03")
    print(
        f"monitoring {args.input_hidraw} for Report 0x03 host index {args.host_index} "
        f"mask 0x{REPORT03_MASKS[args.host_index - 1]:02x}; press and release the mapped button"
    )
    with Report03Reader(args.input_hidraw) as reader:
        reader.drain()
        confirmed, frames = reader.wait_for_host_index_cycle(args.host_index, args.timeout)
    document = {
        "schema": "c658-report03-monitor/v1",
        "time": _utc_now(),
        "input_hidraw": args.input_hidraw,
        "host_index": args.host_index,
        "mask": f"0x{REPORT03_MASKS[args.host_index - 1]:02x}",
        "confirmed_press_release": confirmed,
        "frames": [_frame_dict(frame) for frame in frames],
    }
    _write_audit(args.audit, document)
    return 0 if confirmed else 1


def _cmd_audit_receiver_input(args: argparse.Namespace) -> int:
    """Read-only physical input check before unpair and after pairing."""
    if args.seconds <= 0:
        raise RuntimeError("capture time must be positive")
    candidates = discover_receiver_c658_handles(args.input_hidraw)
    if len(candidates) != 1 or str(candidates[0].path) != args.input_hidraw:
        raise RuntimeError("input path is not a validated C652 paired-device handle")
    if Path(args.audit).exists():
        raise RuntimeError("choose a new audit path")
    fd = os.open(args.input_hidraw, os.O_RDONLY | os.O_CLOEXEC)
    try:
        descriptor_hash = hashlib.sha256(_read_descriptor(fd)).hexdigest()
    finally:
        os.close(fd)
    event_nodes = ([Path(value) for value in args.event] if args.event else
                   input_event_nodes_for_hidraw(args.input_hidraw))
    if not event_nodes:
        raise RuntimeError("no event nodes found for paired-device handle")
    events = [str(path) for path in event_nodes]
    audit: dict[str, object] = {
        "schema": "c652-physical-input/v1", "started_at": _utc_now(),
        **_audit_identity(args.input_hidraw, "audit-receiver-input",
                          {"seconds": args.seconds, "presses": args.presses}),
        "input_hidraw": args.input_hidraw, "event_paths": events,
        "hid_descriptor_sha256": descriptor_hash,
        "physical_button": "left", "expected_evdev_code": BTN_LEFT,
        "required_presses": args.presses, "capture_seconds": args.seconds,
        "raw_reports": [], "key_events": [], "failure": None, "success": False,
    }
    print(f"[input-check] press/release the mouse's left button at least {args.presses}"
          f" times during {args.seconds:g} seconds", flush=True)
    try:
        with MultiInputCapture([args.input_hidraw], events) as capture:
            observed = capture.capture(args.seconds)
        audit["raw_reports"] = list(observed.raw_reports)
        audit["key_events"] = list(observed.key_events)
        raw_press, by_path, confirmed = _grade_receiver_input(
            list(observed.raw_reports), list(observed.key_events), args.presses)
        audit["raw_left_press_transitions"] = raw_press
        audit["evdev_left_press_release_by_path"] = by_path
        audit["success"] = confirmed
        if not audit["success"]:
            audit["failure"] = "required raw and evdev left-button cycles not observed"
    except (Exception, KeyboardInterrupt) as exc:
        audit["failure"] = "interrupted by user" if isinstance(exc, KeyboardInterrupt) else str(exc)
    audit["finished_at"] = _utc_now()
    _write_audit(args.audit, audit)
    return 0 if audit["success"] else 1


def _grade_receiver_input(raw: list[dict[str, object]], keys: list[dict[str, object]],
                          required: int) -> tuple[int, dict[str, list[int]], bool]:
    raw_press = count_expected_press_transitions(raw, None, 0x01)
    by_path: dict[str, list[int]] = {}
    for event in keys:
        if event.get("code") != BTN_LEFT:
            continue
        pair = by_path.setdefault(str(event.get("path", "unknown")), [0, 0])
        if event.get("value") == 1:
            pair[0] += 1
        elif event.get("value") == 0:
            pair[1] += 1
    return raw_press, by_path, bool(raw_press >= required and
                                    any(min(pair) >= required for pair in by_path.values()))


def _cmd_probe_input_raw(args: argparse.Namespace) -> int:
    """Apply one host-routed button and capture every raw input report on many nodes."""
    if not args.commit:
        print("probe-input-raw requires --commit because it writes Report 0x10", file=sys.stderr)
        return 2
    validate_report10_target(args.device)
    paths = list(dict.fromkeys(args.input_hidraw))
    baseline = Report10Config.latest_software_baseline()
    buttons = list(baseline.buttons)
    buttons[args.slot - 1] = ButtonMapping.host_routed(args.host_index)
    test_config = replace(baseline, buttons=tuple(buttons))
    audit: dict[str, object] = {
        "schema": "c658-input-raw-probe/v1",
        "started_at": _utc_now(),
        "device": args.device,
        "input_hidraw": paths,
        "slot": args.slot,
        "host_index": args.host_index,
        "test_report_hex": test_config.to_wire_report().hex(" "),
        "reports": [],
        "failure": None,
    }
    fds: dict[int, str] = {}
    selector = selectors.DefaultSelector()
    try:
        for path in paths:
            fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
            fds[fd] = path
            selector.register(fd, selectors.EVENT_READ)
            while True:
                try:
                    if not os.read(fd, 4096):
                        break
                except BlockingIOError:
                    break
        with HidrawDevice(args.device) as device:
            try:
                device.apply_report10(test_config)
                print(
                    f"[raw-input-test] move the mouse, then press/release the "
                    f"{PHYSICAL_BUTTON_NAMES[args.slot - 1]} button and several other buttons "
                    f"within {args.timeout:g} seconds"
                )
                deadline = time.monotonic() + args.timeout
                while time.monotonic() < deadline:
                    events = selector.select(deadline - time.monotonic())
                    if not events:
                        break
                    for key, _mask in events:
                        try:
                            packet = os.read(key.fd, 4096)
                        except BlockingIOError:
                            continue
                        if packet:
                            audit["reports"].append(
                                {
                                    "time": time.monotonic(),
                                    "path": fds[key.fd],
                                    "length": len(packet),
                                    "report_id": f"0x{packet[0]:02x}",
                                    "raw_hex": packet.hex(" "),
                                }
                            )
            finally:
                device.apply_report10(baseline)
    except Exception as exc:
        audit["failure"] = str(exc)
    finally:
        selector.close()
        for fd in fds:
            os.close(fd)
    audit["finished_at"] = _utc_now()
    audit["success"] = audit["failure"] is None and bool(audit["reports"])
    _write_audit(args.audit, audit)
    return 0 if audit["success"] else 1


def _probe_baseline(args: argparse.Namespace) -> bytes:
    supplied = getattr(args, "baseline_report10_hex", None)
    supplied_file = getattr(args, "baseline_report10_file", None)
    if supplied and supplied_file:
        raise RuntimeError("supply only one baseline Report 0x10 source")
    if supplied_file:
        try:
            supplied = Path(supplied_file).read_text(encoding="ascii")
        except (OSError, UnicodeError) as exc:
            raise RuntimeError("unable to read baseline Report 0x10 file") from exc
    if supplied:
        try:
            report = bytes.fromhex(supplied)
        except ValueError as exc:
            raise RuntimeError("baseline Report 0x10 must be hex bytes") from exc
        if len(report) != 32 or report[0] != 0x10:
            raise RuntimeError("baseline Report 0x10 must contain 32 bytes beginning with 10")
        return report
    if getattr(args, "accept_test_fixture", False):
        return Report10Config.latest_software_baseline().to_wire_report()
    raise RuntimeError("supply --baseline-report10-hex or explicitly accept --accept-test-fixture")


def _parse_matrix_presses(value: str) -> int:
    try:
        presses = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("presses must be an integer 10..100") from exc
    if not 10 <= presses <= 100:
        raise argparse.ArgumentTypeError("presses must be in range 10..100")
    return presses


def _mapped_report(baseline: bytes, slot: int, mapping: ButtonMapping) -> bytes:
    report = bytearray(baseline)
    report[19 + slot - 1] = mapping.wire_value
    return bytes(report)


def _baseline_expected_code(baseline: bytes, slot: int) -> int:
    wire = baseline[19 + slot - 1]
    try:
        return EXPECTED_LINUX_CODES[DirectAction(wire - 0x09)]
    except (ValueError, KeyError) as exc:
        raise RuntimeError("selected baseline physical button needs a known direct mapping for restore check") from exc


def _matrix_phases(profile: str) -> list[dict[str, object]]:
    """Factorized mandatory trials; exhaustive adds the remaining Cartesian pairs."""
    if profile not in ("handle", "transition", "smoke", "core", "exhaustive"):
        raise ValueError("profile must be handle, transition, smoke, core or exhaustive")
    phases: list[dict[str, object]] = []

    def add(name: str, slot: int, index: int, group: str) -> None:
        phases.append({"name": name, "slot": slot, "mapping": ButtonMapping.host_routed(index),
                       "negative_control": index in (0, 215), "group": group})

    if profile == "handle":
        add("handle-radial-host-index-1", 7, 1, "handle")
        return phases

    if profile == "transition":
        for repeat in (1, 2):
            add(f"radial-host-index-6-repeat-{repeat}", 7, 6, "transition")
            add(f"radial-host-index-7-repeat-{repeat}", 7, 7, "transition")
        return phases

    add("radial-host-index-1-before-index-0", 7, 1, "controls")
    add("radial-host-index-0", 7, 0, "controls")
    add("radial-host-index-1-between-negatives", 7, 1, "controls")
    add("radial-host-index-215", 7, 215, "controls")
    add("radial-host-index-1-after-index-215", 7, 1, "controls")
    if profile in ("core", "exhaustive"):
        for index in range(2, 8):
            add(f"radial-host-index-{index}", 7, index, "radial-indices")
        for slot in range(1, 7):
            add(f"{PHYSICAL_BUTTON_NAMES[slot - 1]}-host-index-1", slot, 1, "physical-buttons")
    if profile == "exhaustive":
        for slot in range(1, 7):
            for index in range(2, 8):
                add(f"{PHYSICAL_BUTTON_NAMES[slot - 1]}-host-index-{index}",
                    slot, index, "exhaustive-only")
    return phases


def _baseline_check_button(baseline: bytes) -> tuple[int, int]:
    for slot in range(1, 8):
        try:
            return slot, _baseline_expected_code(baseline, slot)
        except RuntimeError:
            continue
    raise RuntimeError("baseline needs one known direct physical button for restoration check")


MATRIX_CONTEXT_KEYS = (
    "profile", "transport", "vid", "pid", "device", "input_hidraw", "event",
    "hid_descriptor_sha256", "tool_git_commit", "requested_presses_per_phase",
    "capture_seconds_per_phase", "settle_seconds_after_write",
    "post_write_motion_timeout", "pre_motion_seconds", "baseline_report10_hex", "required_phase_count",
    "planned_phase_names", "baseline_expected_evdev_code", "baseline_check_physical_button",
)


def _resume_matrix_audit(existing: dict[str, object], expected: dict[str, object],
                         planned: list[dict[str, object]]) -> int:
    if existing.get("schema") != "c658-report03-matrix/v3":
        raise RuntimeError("resume requires a v3 matrix audit")
    for key in MATRIX_CONTEXT_KEYS:
        if existing.get(key) != expected.get(key):
            raise RuntimeError(f"resume context differs: {key}")
    if existing.get("success"):
        raise RuntimeError("audit already completed successfully")
    records = existing.get("phases")
    if not isinstance(records, list) or len(records) > len(planned):
        raise RuntimeError("resume audit has an invalid phase list")
    for index, record in enumerate(records):
        if not isinstance(record, dict) or record.get("name") != planned[index]["name"]:
            raise RuntimeError("resume audit phase plan differs")
    keep = 0
    for index, record in enumerate(records):
        if record.get("phase_result") != "PASS" or evaluate_phase(record)["phase_result"] != "PASS":
            break
        if record.get("negative_control") and not (
            index > 0 and index + 1 < len(records)
            and records[index - 1].get("phase_result") == "PASS"
            and records[index + 1].get("phase_result") == "PASS"
            and records[index - 1].get("mapping_wire_value") == "0x29"
            and records[index + 1].get("mapping_wire_value") == "0x29"
        ):
            break
        keep += 1
    previous = existing.setdefault("previous_attempts", [])
    if not isinstance(previous, list):
        raise RuntimeError("resume audit has an invalid attempt history")
    previous.append({"at": _utc_now(), "failure": existing.get("failure"),
                     "discarded_phases": records[keep:],
                     "baseline_restored": existing.get("baseline_restored"),
                     "baseline_operation_confirmed": existing.get("baseline_operation_confirmed")})
    existing["phases"] = records[:keep]
    existing["resume_count"] = int(existing.get("resume_count", 0)) + 1
    existing["active_phase"] = None
    existing["finished_at"] = None
    existing["failure"] = None
    existing["success"] = False
    existing["baseline_restored"] = False
    existing["baseline_transfer_wait_completed"] = False
    existing["baseline_operation_confirmed"] = False
    return keep


def _matrix_time_ceiling(remaining: list[dict[str, object]], args: argparse.Namespace) -> int:
    return math.ceil((len(remaining) * (args.motion_timeout + args.settle_seconds + args.phase_seconds)
                      + args.motion_timeout + args.phase_seconds
                      + sum(getattr(args, "pre_motion_seconds", 0) for item in remaining
                            if getattr(args, "profile", None) == "transition"
                            and item["mapping"].wire_value == 0x2f)) / 60)


def _expected_report03_mask(mapping: ButtonMapping) -> int | None:
    # Hardware observation: host index 1 -> bit 0; index 2 -> bit 1.
    # Index 0 produced no Report 0x03. Indices above 7 remain exploratory.
    value = mapping.wire_value
    if 0x29 <= value <= 0x2F:
        return 1 << (value - 0x29)
    return None


def _capture_until_expected(
    capture: MultiInputCapture,
    mapping: ButtonMapping,
    requested_presses: int,
    timeout_seconds: float,
    expected_evdev_code: int | None = None,
    *,
    early_exit: bool = False,
) -> tuple[list[dict[str, object]], list[dict[str, object]], int, bool]:
    raw: list[dict[str, object]] = []
    keys: list[dict[str, object]] = []
    report03_mask = _expected_report03_mask(mapping)
    has_expected_input = report03_mask is not None or expected_evdev_code is not None
    deadline = time.monotonic() + timeout_seconds
    observed = 0
    while time.monotonic() < deadline:
        result = capture.capture(min(0.25, deadline - time.monotonic()))
        raw.extend(result.raw_reports)
        keys.extend(result.key_events)
        if has_expected_input and early_exit:
            sample = {"raw_reports": raw, "key_events": keys,
                      "expected_report03_mask": (
                          None if report03_mask is None else f"0x{report03_mask:02x}"),
                      "expected_evdev_code": expected_evdev_code,
                      "required_presses": requested_presses,
                      "transfer_wait_completed": True, "expected_input_complete": True}
            result_grade = evaluate_phase(sample)
            observed = int(result_grade["observed_expected_presses"])
            if result_grade["phase_result"] == "FAIL":
                return raw, keys, observed, False
            if result_grade["phase_result"] == "PASS":
                grace = min(0.25, max(0.0, deadline - time.monotonic()))
                if grace > 0:
                    tail = capture.capture(grace)
                    raw.extend(tail.raw_reports)
                    keys.extend(tail.key_events)
                final_grade = evaluate_phase({**sample, "raw_reports": raw, "key_events": keys})
                return raw, keys, int(final_grade["observed_expected_presses"]), (
                    final_grade["observed_expected_presses"] >= requested_presses
                    and final_grade["observed_expected_releases"] >= requested_presses)
    if has_expected_input:
        final_grade = evaluate_phase({"raw_reports": raw, "key_events": keys,
            "expected_report03_mask": None if report03_mask is None else f"0x{report03_mask:02x}",
            "expected_evdev_code": expected_evdev_code, "required_presses": requested_presses,
            "transfer_wait_completed": True, "expected_input_complete": True})
        observed = int(final_grade["observed_expected_presses"])
        return raw, keys, observed, (
            final_grade["observed_expected_presses"] >= requested_presses
            and final_grade["observed_expected_releases"] >= requested_presses)
    return raw, keys, 0, True


def _cmd_probe_report03_matrix(args: argparse.Namespace) -> int:
    if not args.commit:
        print("probe-report03-matrix requires --commit because it writes Report 0x10", file=sys.stderr)
        return 2
    if (args.phase_seconds <= 0 or args.motion_timeout <= 0 or args.settle_seconds < 0
            or args.pre_motion_seconds <= 0):
        raise RuntimeError("phase and motion timeouts must be positive; settle time cannot be negative")
    target = validate_report10_target(args.device)
    phases = _matrix_phases(args.profile)
    if args.profile in ("handle", "transition") and args.accept_test_fixture:
        raise RuntimeError("this profile requires a user-supplied baseline Report 0x10")
    if args.profile == "transition" and target.product_id != 0xC652:
        raise RuntimeError("transition profile requires a Receiver target")
    if args.profile == "transition" and (args.early_exit or args.resume):
        raise RuntimeError("transition profile requires full-window capture and a new audit")
    baseline = _probe_baseline(args)
    if args.profile in ("handle", "transition"):
        if args.profile == "handle" and baseline[25] == ButtonMapping.host_routed(1).wire_value:
            raise RuntimeError("handle profile would not change the selected button mapping")
        baseline_slot = 7
        baseline_code = _baseline_expected_code(baseline, baseline_slot)
    else:
        baseline_slot, baseline_code = _baseline_check_button(baseline)
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = "unknown"
    descriptor_hashes = {}
    for path in dict.fromkeys([args.device, *args.input_hidraw]):
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
        try:
            descriptor_hashes[Path(path).name] = hashlib.sha256(_read_descriptor(fd)).hexdigest()
        finally:
            os.close(fd)
    audit: dict[str, object] = {
        "schema": "c658-report03-matrix/v3",
        "tool_git_commit": revision,
        "started_at": _utc_now(),
        "transport": "wired" if target.product_id == 0xC658 else "receiver",
        "vid": f"{target.vendor_id:04x}",
        "pid": f"{target.product_id:04x}",
        "hid_descriptor_sha256": descriptor_hashes,
        "subcommand": "probe-report03-matrix",
        "device": args.device,
        "input_hidraw": list(dict.fromkeys(args.input_hidraw)),
        "event": list(dict.fromkeys(args.event)),
        "profile": args.profile,
        "requested_presses_per_phase": args.presses,
        "required_phase_count": len(phases),
        "planned_phase_names": [item["name"] for item in phases],
        "capture_seconds_per_phase": args.phase_seconds,
        "capture_policy_for_new_phases": "early-exit" if args.early_exit else "full-window",
        "settle_seconds_after_write": args.settle_seconds,
        "post_write_motion_timeout": args.motion_timeout,
        "pre_motion_seconds": args.pre_motion_seconds if args.profile == "transition" else None,
        "evidence_note": "Report 0x17 byte2 remains UNKNOWN_CHARGING_STATE_CANDIDATE",
        "phases": [],
        "baseline_restored": False,
        "baseline_report10_hex": baseline.hex(" "),
        "baseline_expected_evdev_code": baseline_code,
        "baseline_check_physical_button": PHYSICAL_BUTTON_NAMES[baseline_slot - 1],
        "baseline_source": (
            "provided-report10-file" if args.baseline_report10_file else
            "provided-report10-hex" if args.baseline_report10_hex else "explicit-test-fixture"
        ),
        "baseline_transfer_wait_completed": False,
        "baseline_operation_confirmed": False,
        "failure": None,
        "success": False,
        "active_phase": None,
        "active_phase_observation": None,
        "resume_count": 0,
        "previous_attempts": [],
    }
    audit_path = Path(args.audit)
    if args.resume:
        if not audit_path.is_file():
            raise RuntimeError("--resume requires an existing audit JSON")
        existing = json.loads(audit_path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            raise RuntimeError("resume audit must be a JSON object")
        start_index = _resume_matrix_audit(existing, audit, phases)
        audit = existing
        audit["capture_policy_for_new_phases"] = (
            "early-exit" if args.early_exit else "full-window")
    else:
        if audit_path.exists():
            raise RuntimeError("audit already exists; use --resume or choose a new path")
        start_index = 0
    remaining = phases[start_index:]
    positive = sum(not item["negative_control"] for item in remaining)
    negative = len(remaining) - positive
    print(f"[plan] {args.profile}: {len(remaining)} remaining phases "
          f"({positive} positive, {negative} negative); at least "
          f"{(positive + 1) * args.presses} press/release cycles including restoration"
          + (" plus 2 immediate cycles for each index 7 phase;"
             if args.profile == "transition" else ";") + " "
          f"configured upper bound about {_matrix_time_ceiling(remaining, args)} minutes. "
          + ("Positive phases may end early when complete or unexpected input is captured."
             if args.early_exit else "Every phase uses its full capture window."))
    _write_audit(args.audit, audit, quiet=True)
    try:
        with MultiInputCapture(args.input_hidraw, args.event) as capture, HidrawDevice(args.device) as device:
            try:
                for number, specification in enumerate(phases[start_index:], start_index + 1):
                    slot = int(specification["slot"])
                    button_name = PHYSICAL_BUTTON_NAMES[slot - 1]
                    mapping = specification["mapping"]
                    config = _mapped_report(baseline, slot, mapping)
                    negative = bool(specification.get("negative_control"))
                    audit["active_phase"] = specification["name"]
                    _write_audit(args.audit, audit, quiet=True)
                    print(
                        f"[matrix {number}/{len(phases)} {specification['group']}] "
                        f"applying {specification['name']} for {button_name}", flush=True
                    )
                    capture.drain()
                    send_started_at = _utc_now()
                    send_started_monotonic = time.monotonic()
                    ioctl_result = device.set_feature(config)
                    send_finished_monotonic = time.monotonic()
                    send_finished_at = _utc_now()
                    early_result = None
                    early_started_at = None
                    early_started_monotonic = None
                    early_finished_at = None
                    early_finished_monotonic = None
                    if args.profile == "transition" and mapping.wire_value == 0x2f:
                        print(
                            f"[before requested motion] keep the mouse still; immediately press/release "
                            f"{button_name} twice within {args.pre_motion_seconds:g} seconds",
                            flush=True,
                        )
                        early_started_at = _utc_now()
                        early_started_monotonic = time.monotonic()
                        early_result = capture.capture(args.pre_motion_seconds)
                        early_finished_monotonic = time.monotonic()
                        early_finished_at = _utc_now()
                    else:
                        capture.drain()
                    if early_result is not None:
                        audit["active_phase_observation"] = {
                            "before_requested_motion_started_at": early_started_at,
                            "before_requested_motion_started_monotonic": early_started_monotonic,
                            "before_requested_motion_finished_at": early_finished_at,
                            "before_requested_motion_finished_monotonic": early_finished_monotonic,
                            "before_requested_motion_raw_reports": list(early_result.raw_reports),
                            "before_requested_motion_key_events": list(early_result.key_events),
                        }
                        _write_audit(args.audit, audit, quiet=True)
                    motion_requested_at = _utc_now()
                    motion_requested_monotonic = time.monotonic()
                    print(
                        "[transfer-wait] move the mouse now without pressing any button; "
                        "completion is automatic", flush=True
                    )
                    try:
                        motion_result = capture.wait_for_mouse_motion(args.motion_timeout)
                        transfer_ok = True
                    except TimeoutError:
                        motion_result = capture.capture(0.01)
                        transfer_ok = False
                    settle_result = None
                    if args.settle_seconds > 0:
                        print(
                            f"[settle] movement observed; keep moving without pressing buttons for "
                            f"{args.settle_seconds:g} seconds"
                        )
                        settle_result = capture.capture(args.settle_seconds)
                        capture.drain()
                    input_requested_at = _utc_now()
                    input_requested_monotonic = time.monotonic()
                    print(f"[capture] NOW press/release {button_name} at least {args.presses} times "
                          f"within {args.phase_seconds:g} seconds")
                    started = _utc_now()
                    capture_start = time.monotonic()
                    evdev_code = BTN_RIGHT if mapping.wire_value == 0x0B else None
                    raw, keys, observed_presses, expected_complete = _capture_until_expected(
                        capture, mapping, args.presses, args.phase_seconds, evdev_code,
                        early_exit=args.early_exit,
                    )
                    phase_record = {
                        "sequence": number,
                        "group": specification["group"],
                        "name": specification["name"],
                        "slot": slot,
                        "physical_button": button_name,
                        "required": True,
                        "negative_control": negative,
                        "required_presses": args.presses,
                        "expected_evdev_code": evdev_code,
                        "expected_report03_mask": (
                            None if _expected_report03_mask(mapping) is None
                            else f"0x{_expected_report03_mask(mapping):02x}"
                        ),
                        "mapping_wire_value": f"0x{mapping.wire_value:02x}",
                        "report10_hex": config.hex(" "),
                        "set_feature_started_at": send_started_at,
                        "set_feature_finished_at": send_finished_at,
                        "set_feature_started_monotonic": send_started_monotonic,
                        "set_feature_finished_monotonic": send_finished_monotonic,
                        "ioctl_result": ioctl_result,
                        "motion_requested_at": motion_requested_at,
                        "motion_requested_monotonic": motion_requested_monotonic,
                        "post_motion_input_requested_at": input_requested_at,
                        "post_motion_input_requested_monotonic": input_requested_monotonic,
                        "before_requested_motion_started_at": early_started_at,
                        "before_requested_motion_started_monotonic": early_started_monotonic,
                        "before_requested_motion_finished_at": early_finished_at,
                        "before_requested_motion_finished_monotonic": early_finished_monotonic,
                        "before_requested_motion_raw_reports": (
                            [] if early_result is None else list(early_result.raw_reports)
                        ),
                        "before_requested_motion_key_events": (
                            [] if early_result is None else list(early_result.key_events)
                        ),
                        "before_requested_motion_summary": (
                            None if early_result is None else summarize_capture(
                                list(early_result.raw_reports), _expected_report03_mask(mapping))
                        ),
                        "capture_started_at": started,
                        "capture_finished_at": _utc_now(),
                        "capture_duration_seconds": round(time.monotonic() - capture_start, 3),
                        "capture_policy": "early-exit" if args.early_exit else "full-window",
                        "transfer_wait_completed": transfer_ok,
                        "activity_confirmed": transfer_ok,
                        "transfer_wait_raw_reports": list(motion_result.raw_reports),
                        "transfer_wait_key_events": list(motion_result.key_events),
                        "settle_raw_reports": (
                            [] if settle_result is None else list(settle_result.raw_reports)
                        ),
                        "settle_key_events": (
                            [] if settle_result is None else list(settle_result.key_events)
                        ),
                        "raw_reports": raw,
                        "key_events": keys,
                        "observed_expected_presses": observed_presses,
                        "expected_input_complete": expected_complete,
                        "observation_window_complete": not args.early_exit or negative,
                        "capture_interrupted": False,
                        "summary": summarize_capture(raw, _expected_report03_mask(mapping)),
                    }
                    phase_record.update(evaluate_phase(phase_record))
                    audit["phases"].append(phase_record)
                    audit["active_phase"] = None
                    audit["active_phase_observation"] = None
                    if len(audit["phases"]) >= 3:
                        prior = audit["phases"][-2]
                        if prior["negative_control"]:
                            prior["positive_controls_passed"] = bool(
                                audit["phases"][-3]["phase_result"] == "PASS"
                                and phase_record["phase_result"] == "PASS")
                            prior.update(evaluate_phase(prior))
                    _write_audit(args.audit, audit, quiet=True)
                    if (phase_record["phase_result"] != "PASS" and not negative
                            and args.profile != "transition"):
                        raise RuntimeError(f"phase {specification['name']} was {phase_record['phase_result']}")
                    if len(audit["phases"]) >= 2:
                        prior = audit["phases"][-2]
                        if prior["negative_control"] and prior.get("positive_controls_passed") is not None:
                            if prior["phase_result"] != "PASS":
                                raise RuntimeError(f"negative control {prior['name']} was {prior['phase_result']}")
                if args.profile == "transition" and any(
                    item["phase_result"] != "PASS" for item in audit["phases"]
                ):
                    audit["failure"] = "one or more transition phases did not PASS"
            finally:
                audit["baseline_restore_set_feature_started_at"] = _utc_now()
                _write_audit(args.audit, audit, quiet=True)
                audit["baseline_restore_ioctl_result"] = device.set_feature(baseline)
                audit["baseline_restore_set_feature_finished_at"] = _utc_now()
                audit["baseline_restored"] = True
                capture.drain()
                print(
                    "[restore-transfer-wait] software baseline was sent; move the mouse "
                    "without pressing any button; completion is automatic"
                )
                restore_motion = capture.wait_for_mouse_motion(args.motion_timeout)
                audit["baseline_transfer_wait_completed"] = True
                audit["baseline_transfer_wait_raw_reports"] = list(restore_motion.raw_reports)
                audit["baseline_transfer_wait_key_events"] = list(restore_motion.key_events)
                print(f"[restore-check] press/release {PHYSICAL_BUTTON_NAMES[baseline_slot - 1]} "
                      f"{args.presses} times within {args.phase_seconds:g} seconds")
                restore_mapping = ButtonMapping.direct(DirectAction(baseline[19 + baseline_slot - 1] - 0x09))
                restore_raw, restore_keys, _, _ = _capture_until_expected(
                    capture, restore_mapping, args.presses, args.phase_seconds, baseline_code)
                audit["baseline_check_raw_reports"] = restore_raw
                audit["baseline_check_key_events"] = restore_keys
                restore_counts: dict[str, list[int]] = {}
                for event in restore_keys:
                    if event["code"] != baseline_code:
                        continue
                    pair = restore_counts.setdefault(str(event["path"]), [0, 0])
                    if event["value"] == 1:
                        pair[0] += 1
                    elif event["value"] == 0:
                        pair[1] += 1
                audit["baseline_observed_presses_releases"] = restore_counts
                audit["baseline_operation_confirmed"] = (
                    any(pair[0] >= args.presses and pair[1] >= args.presses
                        for pair in restore_counts.values())
                )
                _write_audit(args.audit, audit, quiet=True)
    except KeyboardInterrupt:
        audit["failure"] = "interrupted by user"
    except Exception as exc:
        audit["failure"] = str(exc)
    if audit.get("active_phase") and len(audit["phases"]) < len(phases):
        pending = phases[len(audit["phases"])]
        pending_mapping = pending["mapping"]
        audit["phases"].append({
            "sequence": len(audit["phases"]) + 1,
            "group": pending["group"], "name": pending["name"],
            "slot": pending["slot"],
            "physical_button": PHYSICAL_BUTTON_NAMES[int(pending["slot"]) - 1],
            "required": True, "phase_result": "INCONCLUSIVE",
            "negative_control": pending["negative_control"],
            "required_presses": args.presses,
            "expected_report03_mask": (
                None if _expected_report03_mask(pending_mapping) is None
                else f"0x{_expected_report03_mask(pending_mapping):02x}"),
            "mapping_wire_value": f"0x{pending_mapping.wire_value:02x}",
            "report10_hex": _mapped_report(baseline, int(pending["slot"]), pending_mapping).hex(" "),
            "reasons": [str(audit["failure"] or "capture interrupted")],
            "capture_interrupted": True, "transfer_wait_completed": False,
            "expected_input_complete": False, "raw_reports": [], "key_events": [],
            "observed_expected_presses": 0, "observed_expected_releases": 0,
            "unexpected_input": [],
        })
    audit["active_phase"] = None
    audit["finished_at"] = _utc_now()
    summaries = [phase["summary"] for phase in audit["phases"] if "summary" in phase]
    audit["report03_seen_anywhere"] = any(item["report03_seen"] for item in summaries)
    audit["success"] = matrix_success(audit)
    _write_audit(args.audit, audit)
    return 0 if audit["success"] else 1


def _cmd_probe_report03(args: argparse.Namespace) -> int:
    if not args.commit:
        print("probe-report03 requires --commit because it writes Report 0x10", file=sys.stderr)
        return 2
    validate_report10_target(args.device)
    if not discover_report03_inputs(args.input_hidraw):
        raise RuntimeError(f"{args.input_hidraw} does not declare Input Report 0x03")
    baseline = Report10Config.latest_software_baseline()
    buttons = list(baseline.buttons)
    buttons[args.slot - 1] = ButtonMapping.host_routed(args.host_index)
    test_config = replace(baseline, buttons=tuple(buttons))
    baseline_code = EXPECTED_LINUX_CODES[BASELINE_SLOT_ACTIONS[args.slot - 1]]
    audit: dict[str, object] = {
        "schema": "c658-report03-single-cycle-exploratory/v2",
        "evidence_status": "OBSERVED; insufficient for matrix confirmation",
        "started_at": _utc_now(),
        "device": args.device,
        "input_hidraw": args.input_hidraw,
        "event": args.event,
        "slot": args.slot,
        "physical_button": PHYSICAL_BUTTON_NAMES[args.slot - 1],
        "mask": f"0x{REPORT03_MASKS[args.host_index - 1]:02x}",
        "host_index": args.host_index,
        "test_report_hex": test_config.to_wire_report().hex(" "),
        "frames": [],
        "report03_single_cycle_observed": False,
        "baseline_restore_observed": False,
    }
    failure: str | None = None
    with Report03Reader(args.input_hidraw) as reader, HidrawDevice(args.device) as device:
        try:
            _prompt_activity(args.non_interactive, "report03-test")
            reader.drain()
            device.apply_report10(test_config)
            print(
                f"[report03-test] press and release {PHYSICAL_BUTTON_NAMES[args.slot - 1]} button; "
                f"expect host-index bitmap mask 0x{REPORT03_MASKS[args.host_index - 1]:02x}"
            )
            confirmed, frames = reader.wait_for_host_index_cycle(args.host_index, args.timeout)
            audit["frames"] = [_frame_dict(frame) for frame in frames]
            audit["report03_single_cycle_observed"] = confirmed
            if not confirmed:
                failure = "Report 0x03 press/release cycle was not confirmed"
        except KeyboardInterrupt:
            failure = "interrupted by user"
        except Exception as exc:
            failure = str(exc)
        finally:
            try:
                _prompt_activity(args.non_interactive, "baseline-restore")
                device.apply_report10(baseline)
                print(
                    f"[baseline-restore] press {PHYSICAL_BUTTON_NAMES[args.slot - 1]} button; "
                    f"expect {KEY_NAMES.get(baseline_code, baseline_code)}"
                )
                observation = wait_for_key_press([args.event], baseline_code, args.timeout)
                audit["baseline_restore_observed"] = observation is not None
                if observation is None and failure is None:
                    failure = "baseline restoration was not physically confirmed"
            except Exception as exc:
                if failure is None:
                    failure = f"baseline restoration failed: {exc}"
    audit["finished_at"] = _utc_now()
    audit["failure"] = failure
    audit["success"] = (
        failure is None
        and bool(audit["report03_single_cycle_observed"])
        and bool(audit["baseline_restore_observed"])
    )
    _write_audit(args.audit, audit)
    return 0 if audit["success"] else 1


def _cmd_probe_cache(args: argparse.Namespace) -> int:
    if not args.commit:
        print("probe-cache requires --commit because it writes Report 0x10", file=sys.stderr)
        return 2
    validate_report10_target(args.device)
    baseline = Report10Config.latest_software_baseline()
    buttons = list(baseline.buttons)
    buttons[args.slot - 1] = ButtonMapping.direct(DirectAction.HID_MOUSE_RIGHT)
    changed = replace(baseline, buttons=tuple(buttons))
    cache = Report10SendCache()
    actions: list[dict[str, object]] = []

    def record(label: str, config: Report10Config, transport) -> None:
        try:
            result = cache.send(config, transport)
            actions.append(
                {
                    "label": label,
                    "disposition": result.disposition,
                    "transport_result": result.transport_result,
                    "cache_present": cache.last_successful_blob is not None,
                }
            )
        except Exception as exc:
            actions.append(
                {
                    "label": label,
                    "disposition": "transport-failed-cache-cleared",
                    "error": str(exc),
                    "cache_present": cache.last_successful_blob is not None,
                }
            )

    with HidrawDevice(args.device) as device:
        try:
            _prompt_activity(args.non_interactive, "cache-probe")
            record("baseline-first", baseline, device.set_feature)
            record("baseline-identical", baseline, device.set_feature)
            record("changed-first", changed, device.set_feature)

            def injected_failure(_report: bytes) -> int:
                raise OSError("intentional SDK fault injection; no ioctl issued")

            cache.clear()
            cache.send(changed, lambda _report: 0)
            record("changed-injected-failure", baseline, injected_failure)
            record("baseline-after-failure", baseline, device.set_feature)
        finally:
            cache.clear()
            record("baseline-final-restore", baseline, device.set_feature)
    expected = [
        "sent-and-cached",
        "suppressed-identical",
        "sent-and-cached",
        "transport-failed-cache-cleared",
        "sent-and-cached",
        "sent-and-cached",
    ]
    observed = [str(item["disposition"]) for item in actions]
    document = {
        "schema": "linux-report10-cache-probe/v1",
        "time": _utc_now(),
        "device": args.device,
        "scope": "Linux SDK cache; not introspection of Windows 3DxWare cache",
        "failure_mode": "intentional host-side exception; no failing ioctl sent to hardware",
        "actions": actions,
        "success": observed == expected,
    }
    _write_audit(args.audit, document)
    return 0 if document["success"] else 1


def _single_management_path(preferred: str | None = None) -> str:
    candidates = discover_receiver_management()
    if preferred:
        for item in candidates:
            if str(item.path) == preferred:
                return preferred
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected exactly one receiver management node, found {len(candidates)}"
        )
    return str(candidates[0].path)


def _cmd_pair(args: argparse.Namespace) -> int:
    if args.timeout <= 0 or args.poll_interval <= 0:
        raise ValueError("timeout and poll interval must be greater than zero")
    if not 0 <= args.expect_type <= 0xFF:
        raise ValueError("expected device type must be in range 0x00..0xff")
    validate_receiver_management(args.device, require_pairing_report=True)
    before = read_receiver_slots(args.device)
    if not any(not slot.occupied for slot in before):
        raise RuntimeError("receiver has no empty slot; refusing to start pairing")
    preview = {
        "device": args.device,
        "start_packet": PAIR_START.hex(" "),
        "stop_packet": PAIR_STOP.hex(" "),
        "before": [slot.to_dict() for slot in before],
        "evidence": "manual success reported; reproducible raw success audit absent",
    }
    if not args.commit_experimental_pairing:
        print(json.dumps(preview, indent=2, ensure_ascii=False))
        print("dry-run: add --commit-experimental-pairing to write Report 0x41")
        return 0
    if not args.non_interactive:
        answer = input(
            "Experimental pairing will write 41 02 02 00 00. "
            "Type PAIR to continue: "
        )
        if answer != "PAIR":
            print("pairing cancelled")
            return 2

    audit: dict[str, object] = {
        "schema": "c652-experimental-pairing/v1",
        "started_at": _utc_now(),
        **_audit_identity(args.device, "pair", {"timeout": args.timeout,
                                             "poll_interval": args.poll_interval,
                                             "expect_type": args.expect_type}),
        **preview,
        "snapshots": [],
        "new_slots": [],
        "stop_sent": False,
        "success": False,
    }
    start_sent = False
    failure: str | None = None
    current_path = args.device
    new_slots = []
    try:
        print("[pair] starting experimental receiver pairing mode", flush=True)
        set_pairing_mode(current_path, True)
        start_sent = True
        print(
            "[pair] place the intended mouse into its pairing procedure now; polling slots ...",
            flush=True,
        )
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            try:
                current_path = _single_management_path(current_path)
                snapshot = read_receiver_slots(current_path)
                audit["snapshots"].append(  # type: ignore[union-attr]
                    {
                        "time": _utc_now(),
                        "device": current_path,
                        "slots": [slot.to_dict() for slot in snapshot],
                    }
                )
                new_slots = newly_occupied_slots(before, snapshot)
                if new_slots:
                    break
            except (OSError, RuntimeError):
                pass
            time.sleep(args.poll_interval)
        if not new_slots:
            failure = "timeout without a newly occupied slot"
        else:
            audit["new_slots"] = [slot.to_dict() for slot in new_slots]
            unexpected = [slot for slot in new_slots if slot.device_type != args.expect_type]
            if unexpected:
                failure = "new slot device_type did not match expected type"
    except KeyboardInterrupt:
        failure = "interrupted by user"
    except Exception as exc:
        failure = str(exc)
    finally:
        if start_sent:
            stop_deadline = time.monotonic() + 10.0
            while time.monotonic() < stop_deadline:
                try:
                    current_path = _single_management_path(current_path)
                    set_pairing_mode(current_path, False)
                    audit["stop_sent"] = True
                    print("[pair] pairing stop packet sent", flush=True)
                    break
                except (OSError, RuntimeError):
                    time.sleep(0.5)
            if not audit["stop_sent"] and failure is None:
                failure = "unable to send pairing stop packet"
    audit["finished_at"] = _utc_now()
    audit["failure"] = failure
    audit["success"] = failure is None and bool(new_slots) and bool(audit["stop_sent"])
    try:
        audit["paired_c658_handles"] = [
            str(item.path) for item in discover_receiver_c658_handles()
        ]
    except Exception:
        audit["paired_c658_handles"] = []
    _write_audit(args.audit, audit)
    if audit["success"]:
        print("PAIRING BOND DETECTED: new occupied slot found and pairing mode stopped")
        print("Next: verify mouse input and Report 0x10 on the paired-device handle")
        return 0
    print(f"PAIRING FAILED: {failure}", file=sys.stderr)
    return 1


def _parse_raw_slot(value: str) -> bytes:
    try:
        raw = bytes.fromhex(value.replace(":", " ").replace("-", " "))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected raw slot value must be hexadecimal") from exc
    if len(raw) != 8:
        raise argparse.ArgumentTypeError("expected raw slot value must contain exactly 8 bytes")
    return raw


def _cmd_unpair(args: argparse.Namespace) -> int:
    if args.timeout <= 0 or args.poll_interval <= 0:
        raise ValueError("timeout and poll interval must be greater than zero")
    validate_receiver_management(args.device, require_pairing_report=True)
    before = read_receiver_slots(args.device)
    target = before[args.slot]
    if not target.occupied:
        raise RuntimeError(f"receiver slot {args.slot} is already empty; refusing unpair")
    packet = build_unpair_packet(args.slot)
    preview = {
        "device": args.device,
        "slot": args.slot,
        "packet": packet.hex(" "),
        "target_before": target.to_dict(),
        "required_expect_raw": target.raw.hex(" "),
        "evidence": "manual success reported; reproducible raw success audit absent",
    }
    if not args.commit_experimental_unpair:
        print(json.dumps(preview, indent=2, ensure_ascii=False))
        print(
            "dry-run: repeat with --expect-raw exactly as shown and "
            "--commit-experimental-unpair"
        )
        return 0
    if args.expect_raw is None:
        raise RuntimeError("committing unpair requires --expect-raw from the dry-run")
    if args.expect_raw != target.raw:
        raise RuntimeError(
            "slot changed or --expect-raw does not match; no unpair packet was sent"
        )
    if not args.non_interactive:
        answer = input(
            f"Destructive unpair targets slot {args.slot} raw "
            f"{target.raw.hex(' ')}. Type UNPAIR {args.slot} to continue: "
        )
        if answer != f"UNPAIR {args.slot}":
            print("unpair cancelled")
            return 2

    audit: dict[str, object] = {
        "schema": "c652-experimental-unpair/v2",
        "started_at": _utc_now(),
        **_audit_identity(args.device, "unpair", {"slot": args.slot,
                                               "timeout": args.timeout,
                                               "poll_interval": args.poll_interval}),
        **preview,
        "before": [slot.to_dict() for slot in before],
        "snapshots": [],
        "unpair_request_attempted": False,
        "packet_sent": False,
        "ioctl_error": None,
        "target_empty_confirmed": False,
        "success": False,
    }
    failure: str | None = None
    current_path = args.device
    try:
        print(f"[unpair] sending explicit slot {args.slot} removal packet", flush=True)
        audit["unpair_request_attempted"] = True
        try:
            unpair_slot(current_path, args.slot)
            audit["packet_sent"] = True
        except OSError as exc:
            if exc.errno != errno.EPIPE:
                raise
            audit["ioctl_error"] = {
                "errno": exc.errno,
                "name": "EPIPE",
                "message": str(exc),
                "interpretation": (
                    "transport completion is ambiguous; continue polling slot state "
                    "because successful unpair can disconnect or re-enumerate the endpoint"
                ),
            }
            print(
                "[unpair] ioctl returned EPIPE; continuing slot polling because receiver "
                "disconnect/re-enumeration can occur after an applied request",
                flush=True,
            )
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            try:
                current_path = _single_management_path(current_path)
                snapshot = read_receiver_slots(current_path)
                audit["snapshots"].append({
                    "time": _utc_now(),
                    "device": current_path,
                    "slots": [slot.to_dict() for slot in snapshot],
                })
                if not snapshot[args.slot].occupied:
                    audit["target_empty_confirmed"] = True
                    audit["after"] = [slot.to_dict() for slot in snapshot]
                    break
            except (OSError, RuntimeError):
                pass
            time.sleep(args.poll_interval)
        if not audit["target_empty_confirmed"]:
            failure = "timeout before the target slot became empty"
    except KeyboardInterrupt:
        failure = "interrupted by user after unpair may have been sent"
    except Exception as exc:
        failure = str(exc)
    audit["finished_at"] = _utc_now()
    audit["failure"] = failure
    audit["success"] = (
        failure is None
        and bool(audit["unpair_request_attempted"])
        and bool(audit["target_empty_confirmed"])
    )
    _write_audit(args.audit, audit)
    if audit["success"]:
        print(f"UNPAIR CONFIRMED: receiver slot {args.slot} is empty")
        print("Next: run the guarded pair command to validate recovery")
        return 0
    print(f"UNPAIR RESULT UNCERTAIN: {failure}", file=sys.stderr)
    return 1


def _cmd_build(args: argparse.Namespace) -> int:
    report = _config_from_args(args).to_wire_report()
    print(report.hex(" "))
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    report = config.to_wire_report()
    print(f"target: {args.device}")
    print(f"report: {report.hex(' ')}")
    if not args.commit:
        print("dry-run: no Feature Report was written; add --commit to write")
        return 0
    validate_report10_target(args.device)
    with HidrawDevice(args.device) as device:
        result = device.apply_report10(config)
    print(f"HIDIOCSFEATURE returned {result}; physical application is not yet confirmed")
    return 0


def _cmd_restore_report10(args: argparse.Namespace) -> int:
    if not args.commit:
        print("restore-report10 requires --commit", file=sys.stderr)
        return 2
    if not args.baseline_report10_hex:
        raise RuntimeError("restore-report10 requires --baseline-report10-hex")
    report = _probe_baseline(args)
    target = validate_report10_target(args.device)
    audit = {
        "schema": "c658-report10-restore/v1", "started_at": _utc_now(),
        **_audit_identity(args.device, "restore-report10", {},
                          "wired" if target.product_id == 0xC658 else "receiver",
                          f"{target.product_id:04x}"),
        "report10_hex": report.hex(" "), "ioctl_result": None,
        "physical_operation_confirmed": False, "failure": None, "success": False,
    }
    try:
        with HidrawDevice(args.device) as device:
            audit["ioctl_result"] = device.set_feature(report)
        audit["success"] = True
    except Exception as exc:
        audit["failure"] = str(exc)
    audit["finished_at"] = _utc_now()
    _write_audit(args.audit, audit)
    print("Report 0x10 submitted; physically verify restored controls")
    return 0 if audit["success"] else 1


def _prompt_activity(non_interactive: bool, phase: str) -> None:
    if non_interactive:
        return
    print(f"[{phase}] Move the mouse to keep it awake; sending Report 0x10 now")


def _event_paths(args: argparse.Namespace) -> list[Path]:
    if args.event:
        return [Path(value) for value in args.event]
    paths = input_event_nodes_for_hidraw(args.device)
    if not paths:
        raise RuntimeError("no input event node resolved; specify --event /dev/input/eventN")
    return paths


def _observe_phase(
    *,
    device: HidrawDevice,
    config: Report10Config | bytes,
    phase: str,
    expected_code: int | None,
    event_paths: Sequence[Path],
    timeout: float,
    non_interactive: bool,
    raw_paths: Sequence[str] = (),
) -> dict[str, object]:
    _prompt_activity(non_interactive, phase)
    report = config if isinstance(config, bytes) else config.to_wire_report()
    ioctl_result = device.set_feature(report)
    expected_name = KEY_NAMES.get(expected_code, f"KEY_{expected_code}") if expected_code is not None else "UNKNOWN"
    print(f"[{phase}] sent; press/release the selected physical button")
    if expected_code is None:
        with MultiInputCapture(list(raw_paths), [str(p) for p in event_paths]) as capture:
            observed = capture.capture(timeout)
        return {
            "phase": phase, "time": _utc_now(), "report_hex": report.hex(" "),
            "ioctl_result": ioctl_result, "expected_linux_code": None,
            "hardware_effect": "UNKNOWN", "raw_reports": list(observed.raw_reports),
            "key_events": list(observed.key_events), "confirmed": False,
            "capture_complete": True,
            "phase_result": "INCONCLUSIVE",
        }
    observation = wait_for_key_press(event_paths, expected_code, timeout)
    return {
        "phase": phase,
        "time": _utc_now(),
        "report_hex": report.hex(" "),
        "ioctl_result": ioctl_result,
        "expected_linux_code": expected_code,
        "expected_linux_name": expected_name,
        "confirmed": observation is not None,
        "event_path": str(observation.event_path) if observation else None,
    }


def _write_audit(path: str | None, document: dict[str, object], *, quiet: bool = False) -> None:
    serial_tokens: dict[str, str] = {}

    def redact(value):
        if isinstance(value, list):
            return [redact(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: redact(item) for key, item in value.items()}
        serial = value.get("serial_raw_hex")
        if isinstance(serial, str) and serial.strip(" 0"):
            token = serial_tokens.setdefault(serial, f"<ANONYMIZED:DEVICE_{len(serial_tokens) + 1}>")
            result["serial_raw_hex"] = token
            raw = value.get("raw_hex")
            if isinstance(raw, str):
                result["raw_hex"] = " ".join(raw.split()[:2]) + " " + token
        if "required_expect_raw" in result and isinstance(result["required_expect_raw"], str):
            raw = result["required_expect_raw"].split()
            if len(raw) == 8:
                serial = " ".join(raw[2:])
                token = serial_tokens.setdefault(serial, f"<ANONYMIZED:DEVICE_{len(serial_tokens) + 1}>")
                result["required_expect_raw"] = " ".join(raw[:2]) + " " + token
        return result

    payload = json.dumps(redact(document), indent=2, ensure_ascii=False) + "\n"
    if path:
        target = Path(path)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent,
                                             prefix=f".{target.name}.", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        if not quiet:
            print(f"audit: {path}")
    else:
        print(payload, end="")


def _cmd_probe_direct(args: argparse.Namespace) -> int:
    if args.action == DirectAction.UNKNOWN_DIRECT_CODE_6:
        return _cmd_probe_direct6_controlled(args)
    if not args.commit:
        print("probe-direct requires --commit because it performs controlled writes", file=sys.stderr)
        return 2
    print(f"[setup] validating Report 0x10 target {args.device} ...", flush=True)
    target = validate_report10_target(args.device)
    print("[setup] target validation passed", flush=True)
    print("[setup] resolving Linux input event node ...", flush=True)
    event_paths = _event_paths(args)
    print(
        "[setup] input event node(s): " + ", ".join(str(path) for path in event_paths),
        flush=True,
    )
    slot_index = args.slot - 1
    baseline = _probe_baseline(args)
    test_config = _mapped_report(baseline, args.slot, ButtonMapping.direct(args.action))
    baseline_code = _baseline_expected_code(baseline, args.slot)
    if args.action == DirectAction.UNKNOWN_DIRECT_CODE_6 and args.expect_code is not None:
        raise RuntimeError("code 6 has no expected Linux event; omit --expect-code")
    test_code = args.expect_code if args.expect_code is not None else EXPECTED_LINUX_CODES.get(args.action)
    if test_code is None and not args.input_hidraw:
        raise RuntimeError("unknown code 6 requires --input-hidraw for raw HID capture")

    audit: dict[str, object] = {
        "schema": "c658-report10-probe/v1",
        "started_at": _utc_now(),
        **_audit_identity(args.device, "probe-direct", {"slot": args.slot,
            "action": args.action.name, "timeout": args.timeout},
            "wired" if target.product_id == 0xC658 else "receiver",
            f"{target.product_id:04x}"),
        "device": args.device,
        "transport": "wired" if target.product_id == 0xC658 else "receiver",
        "vid": f"{target.vendor_id:04x}", "pid": f"{target.product_id:04x}",
        "baseline_report10_hex": baseline.hex(" "),
        "baseline_source": "provided-host-snapshot" if args.baseline_report10_hex else "explicit-test-fixture",
        "event_paths": [str(path) for path in event_paths],
        "input_hidraw": list(args.input_hidraw),
        "keep_open_hidraw": list(args.keep_open),
        "slot": args.slot,
        "test_action": args.action.name,
        "physical_button": PHYSICAL_BUTTON_NAMES[slot_index],
        "hardware_effect": "UNKNOWN" if test_code is None else "subject to physical confirmation",
        "code6_name_is_unknown": args.action == DirectAction.UNKNOWN_DIRECT_CODE_6,
        "phases": [],
        "success": False,
    }
    phases: list[dict[str, object]] = audit["phases"]  # type: ignore[assignment]
    failure: str | None = None
    held_fds: list[tuple[str, int]] = []
    try:
        for path in args.keep_open:
            fd = os.open(path, os.O_RDWR | os.O_CLOEXEC | os.O_NONBLOCK)
            held_fds.append((path, fd))
            print(f"[setup] holding {path} open (fd={fd})", flush=True)
        if held_fds:
            print("[setup] keep-open handles will remain open through baseline restoration", flush=True)

        with HidrawDevice(args.device) as device:
            failure = _run_direct_probe_phases(
                args=args,
                device=device,
                event_paths=event_paths,
                baseline=baseline,
                test_config=test_config,
                baseline_code=baseline_code,
                test_code=test_code,
                phases=phases,
            )
    finally:
        for path, fd in reversed(held_fds):
            os.close(fd)
            print(f"[setup] released keep-open handle {path}", flush=True)

    audit["finished_at"] = _utc_now()
    audit["failure"] = failure
    audit["success"] = failure is None and len(phases) == 3 and all(
        bool(phase.get("confirmed")) for phase in (phases[0], phases[2])
    ) and bool(phases[1].get("capture_complete") if test_code is None else phases[1].get("confirmed"))
    _write_audit(args.audit, audit)
    if audit["success"]:
        print("CAPTURE COMPLETE: baseline restored; code 6 hardware effect remains UNKNOWN"
              if test_code is None else "PASS: Report 0x10 application and baseline restoration were physically confirmed")
        return 0
    print(f"FAIL: {failure}", file=sys.stderr)
    return 1


def _direct6_phase(args, capture: MultiInputCapture, device: HidrawDevice,
                   audit: dict[str, object], name: str, report: bytes,
                   known_code: int | None) -> dict[str, object]:
    """Record one complete physical-input window after a timed Report 0x10 send."""
    record: dict[str, object] = {"phase": name, "report10_hex": report.hex(" "),
                                 "required_presses": args.presses, "known_evdev_code": known_code}
    capture.drain()
    record["set_feature_started_at"] = _utc_now()
    record["set_feature_started_monotonic"] = time.monotonic()
    try:
        record["ioctl_result"] = device.set_feature(report)
        record["set_feature_finished_monotonic"] = time.monotonic()
        record["set_feature_finished_at"] = _utc_now()
        print(f"[{name}] move the mouse without pressing buttons", flush=True)
        try:
            motion = capture.wait_for_mouse_motion(args.motion_timeout)
            record["transfer_wait_completed"] = True
        except TimeoutError:
            motion = capture.capture(0.01)
            record["transfer_wait_completed"] = False
        record["transfer_wait_raw_reports"] = list(motion.raw_reports)
        record["transfer_wait_key_events"] = list(motion.key_events)
        print(f"[{name}] NOW press/release {PHYSICAL_BUTTON_NAMES[args.slot - 1]}"
              f" at least {args.presses} times within {args.timeout:g} seconds", flush=True)
        record["capture_started_at"] = _utc_now()
        record["capture_started_monotonic"] = time.monotonic()
        observed = capture.capture(args.timeout)
        record["capture_finished_monotonic"] = time.monotonic()
        record["capture_finished_at"] = _utc_now()
        record["raw_reports"] = list(observed.raw_reports)
        record["key_events"] = list(observed.key_events)
        record["capture_complete"] = True
        if known_code is not None:
            presses = sum(e["code"] == known_code and e["value"] == 1
                          for e in observed.key_events)
            releases = sum(e["code"] == known_code and e["value"] == 0
                           for e in observed.key_events)
            record["known_presses"] = presses
            record["known_releases"] = releases
            record["known_input_confirmed"] = bool(
                record["ioctl_result"] == 32 and record["transfer_wait_completed"]
                and presses >= args.presses
                and releases >= args.presses)
        else:
            record["hardware_effect"] = "UNKNOWN"
    except BaseException as exc:
        record["error"] = "interrupted by user" if isinstance(exc, KeyboardInterrupt) else str(exc)
        raise
    finally:
        audit["phases"].append(record)
        _write_audit(args.audit, audit, quiet=True)
    return record


def _cmd_probe_direct6_controlled(args: argparse.Namespace) -> int:
    if not args.commit:
        print("probe-direct requires --commit because it writes Report 0x10", file=sys.stderr)
        return 2
    if args.expect_code is not None or not args.input_hidraw or not args.audit:
        raise RuntimeError("code 6 requires --input-hidraw and --audit, without --expect-code")
    if args.timeout <= 0 or args.motion_timeout <= 0:
        raise RuntimeError("capture and motion timeouts must be positive")
    target = validate_report10_target(args.device)
    if not all(discover_report03_inputs(path) for path in args.input_hidraw):
        raise RuntimeError("raw input must declare Report 0x03")
    event_paths = _event_paths(args)
    baseline = _probe_baseline(args)
    baseline_code = _baseline_expected_code(baseline, args.slot)
    code6_report = _mapped_report(baseline, args.slot, ButtonMapping.direct(args.action))
    if baseline == code6_report:
        raise RuntimeError("known control and code 6 must have different mappings")
    if Path(args.audit).exists():
        raise RuntimeError("choose a new audit path")
    descriptor_hashes = {}
    for path in dict.fromkeys([args.device, *args.input_hidraw]):
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
        try:
            descriptor_hashes[Path(path).name] = hashlib.sha256(_read_descriptor(fd)).hexdigest()
        finally:
            os.close(fd)
    audit: dict[str, object] = {
        "schema": "c658-direct6-controlled/v1", "started_at": _utc_now(),
        **_audit_identity(args.device, "probe-direct", {"slot": args.slot,
            "action": args.action.name, "timeout": args.timeout},
            "wired" if target.product_id == 0xC658 else "receiver",
            f"{target.product_id:04x}"),
        "device": args.device,
        "transport": "wired" if target.product_id == 0xC658 else "receiver",
        "hid_descriptor_sha256": descriptor_hashes,
        "input_hidraw": list(args.input_hidraw),
        "event_paths": [str(p) for p in event_paths],
        "baseline_report10_hex": baseline.hex(" "),
        "baseline_source": (
            "provided-report10-file" if args.baseline_report10_file else
            "provided-report10-hex" if args.baseline_report10_hex else "explicit-test-fixture"),
        "test_report10_hex": code6_report.hex(" "),
        "slot": args.slot, "physical_button": PHYSICAL_BUTTON_NAMES[args.slot - 1],
        "known_evdev_code": baseline_code,
        "requested_presses_per_phase": args.presses,
        "capture_seconds_per_phase": args.timeout,
        "motion_timeout_seconds": args.motion_timeout,
        "phases": [], "restore_attempted": False, "baseline_restored": False,
        "baseline_operation_confirmed": False,
        "hardware_effect": "UNKNOWN", "failure": None, "success": False,
    }
    print(f"[plan] target {args.device}, slot {args.slot}: known direct"
          f" 0x{baseline[18 + args.slot]:02x} -> code 6 0x0f -> known direct;"
          f" 3 transfer checks and at least {3 * args.presses} press/release cycles;"
          f" configured limit about {math.ceil(3 * (args.motion_timeout + args.timeout) / 60)} minutes",
          flush=True)
    _write_audit(args.audit, audit, quiet=True)
    failure = None
    try:
        with MultiInputCapture(args.input_hidraw, [str(p) for p in event_paths]) as capture, HidrawDevice(args.device) as device:
            try:
                before = _direct6_phase(args, capture, device, audit, "known-before", baseline, baseline_code)
                if not before.get("known_input_confirmed"):
                    raise RuntimeError("known mapping before code 6 was not confirmed")
                _direct6_phase(args, capture, device, audit, "code6", code6_report, None)
            finally:
                audit["restore_attempted"] = True
                _write_audit(args.audit, audit, quiet=True)
                after = _direct6_phase(args, capture, device, audit, "known-after", baseline, baseline_code)
                audit["baseline_restored"] = after.get("ioctl_result") == 32
                audit["baseline_operation_confirmed"] = after.get("known_input_confirmed", False)
    except (Exception, KeyboardInterrupt) as exc:
        failure = "interrupted by user" if isinstance(exc, KeyboardInterrupt) else str(exc)
    audit["finished_at"] = _utc_now()
    audit["failure"] = failure
    audit["success"] = bool(
        failure is None and len(audit["phases"]) == 3
        and all(p.get("transfer_wait_completed") and p.get("capture_complete")
                for p in audit["phases"])
        and all(p.get("ioctl_result") == 32 for p in audit["phases"])
        and audit["phases"][0].get("known_input_confirmed")
        and audit["baseline_restored"] and audit["baseline_operation_confirmed"])
    _write_audit(args.audit, audit)
    return 0 if audit["success"] else 1


def _run_direct_probe_phases(
    *,
    args: argparse.Namespace,
    device: HidrawDevice,
    event_paths: Sequence[Path],
    baseline: bytes,
    test_config: bytes,
    baseline_code: int,
    test_code: int | None,
    phases: list[dict[str, object]],
) -> str | None:
    failure: str | None = None
    try:
        preflight = _observe_phase(
            device=device,
            config=baseline,
            phase="baseline-preflight",
            expected_code=baseline_code,
            event_paths=event_paths,
            timeout=args.timeout,
            non_interactive=args.non_interactive,
        )
        phases.append(preflight)
        if not preflight["confirmed"]:
            raise RuntimeError("baseline preflight input was not confirmed")

        test = _observe_phase(
            device=device,
            config=test_config,
            phase="test-mapping",
            expected_code=test_code,
            event_paths=event_paths,
            timeout=args.timeout,
            non_interactive=args.non_interactive,
            raw_paths=args.input_hidraw,
        )
        phases.append(test)
        if test_code is not None and not test["confirmed"]:
            raise RuntimeError("test mapping input was not confirmed")
    except KeyboardInterrupt:
        failure = "interrupted by user"
    except Exception as exc:
        failure = str(exc)
    finally:
        try:
            restored = _observe_phase(
                device=device,
                config=baseline,
                phase="baseline-restore",
                expected_code=baseline_code,
                event_paths=event_paths,
                timeout=args.timeout,
                non_interactive=args.non_interactive,
            )
            phases.append(restored)
            if not restored["confirmed"] and failure is None:
                failure = "baseline restoration was not physically confirmed"
        except Exception as exc:
            phases.append(
                {
                    "phase": "baseline-restore",
                    "time": _utc_now(),
                    "confirmed": False,
                    "error": str(exc),
                }
            )
            if failure is None:
                failure = f"baseline restoration failed: {exc}"
    return failure


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="c658-report10ctl",
        description="C658/C652 Report 0x10 builder, writer and physical verifier",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="read-only validated target discovery")
    scan.add_argument("--pattern", default="/dev/hidraw*")
    scan.add_argument("--json", action="store_true")
    scan.add_argument("--all", action="store_true", help="include every 256f hidraw node")
    scan.set_defaults(func=_cmd_scan)

    read_paths = subparsers.add_parser(
        "audit-read-paths", help="read-only descriptor and bounded GET audit for one HID node"
    )
    read_paths.add_argument("--device", required=True, help="one verified C658/C652 hidraw node")
    read_paths.add_argument("--audit", required=True, help="private JSON audit path")
    read_paths.add_argument(
        "--report10-readback", action="store_true",
        help="bounded GET 0x10 audit on C658 MI_01 or C652 MI_02",
    )
    read_paths.set_defaults(func=_cmd_audit_read_paths)

    slots = subparsers.add_parser(
        "receiver-slots", help="read-only GET_FEATURE 0x43..0x47 slot snapshot"
    )
    slots.add_argument("--device", required=True, help="C652 management hidraw node")
    slots.add_argument("--audit", help="write JSON snapshot to this path")
    slots.set_defaults(func=_cmd_receiver_slots)

    hold_open = subparsers.add_parser(
        "hold-open",
        help="keep every wired C658 hidraw interface open across reconnects",
    )
    hold_open.add_argument("--pattern", default="/dev/hidraw*")
    hold_open.add_argument("--poll-interval", type=float, default=1.0)
    hold_open.add_argument(
        "--once", action="store_true",
        help="diagnose matching/open permissions once and exit",
    )
    hold_open.set_defaults(func=_cmd_hold_open)

    monitor03 = subparsers.add_parser(
        "monitor-report03", help="read-only Report 0x03 bitmap monitor"
    )
    monitor03.add_argument("--input-hidraw", required=True)
    monitor03.add_argument("--host-index", type=int, choices=range(1, 8), default=1)
    monitor03.add_argument("--timeout", type=float, default=30.0)
    monitor03.add_argument("--audit")
    monitor03.set_defaults(func=_cmd_monitor_report03)

    receiver_input = subparsers.add_parser(
        "audit-receiver-input", help="read-only raw HID and evdev left-button audit"
    )
    receiver_input.add_argument("--input-hidraw", required=True,
                                help="validated C652 paired-device hidraw node")
    receiver_input.add_argument("--event", action="append",
                                help="matching evdev node; omit to discover from hidraw sysfs")
    receiver_input.add_argument("--seconds", type=float, default=30.0)
    receiver_input.add_argument("--presses", type=_parse_matrix_presses, default=10)
    receiver_input.add_argument("--audit", required=True)
    receiver_input.set_defaults(func=_cmd_audit_receiver_input)

    raw_input = subparsers.add_parser(
        "probe-input-raw",
        help="apply host routing and capture unfiltered raw reports from multiple hidraw nodes",
    )
    raw_input.add_argument("--device", required=True, help="Report 0x10 target")
    raw_input.add_argument(
        "--input-hidraw", action="append", required=True,
        help="hidraw input candidate; repeat for simultaneous capture",
    )
    raw_input.add_argument("--slot", type=int, choices=range(1, 8), default=7)
    raw_input.add_argument("--host-index", type=_parse_host_index, default=1, metavar="0..215")
    raw_input.add_argument("--timeout", type=float, default=30.0)
    raw_input.add_argument("--audit", required=True)
    raw_input.add_argument("--commit", action="store_true")
    raw_input.set_defaults(func=_cmd_probe_input_raw)

    matrix = subparsers.add_parser(
        "probe-report03-matrix",
        help="controlled Report 0x03 profiles with checkpoint and resume",
    )
    matrix.add_argument("--device", required=True, help="Report 0x10 target")
    matrix.add_argument("--input-hidraw", action="append", required=True,
                        help="raw input candidate; repeat for simultaneous capture")
    matrix.add_argument("--event", action="append", required=True,
                        help="evdev input node; repeat when needed")
    matrix.add_argument("--profile", choices=("handle", "transition", "smoke", "core", "exhaustive"),
                        default="core", help="test scope; core is the release prerequisite")
    matrix.add_argument("--presses", type=_parse_matrix_presses, default=10,
                        help="required press/release cycles for each positive phase (10..100)")
    matrix.add_argument("--phase-seconds", type=float, default=30.0)
    matrix.add_argument("--pre-motion-seconds", type=float, default=8.0,
                        help="transition profile: capture index 7 immediately before requested movement")
    matrix.add_argument("--early-exit", action="store_true",
                        help="opt in to shorter positive phases; full-window capture is the default")
    matrix.add_argument(
        "--motion-timeout", type=float, default=30.0,
        help="maximum wait for post-write Report 0x1b mouse movement",
    )
    matrix.add_argument(
        "--settle-seconds", type=float, default=2.0,
        help="wait after each write before accepting button input (default: 2.0)",
    )
    matrix.add_argument("--baseline-report10-hex", help="owner-provided complete 32-byte restoration target")
    matrix.add_argument("--baseline-report10-file", help="private text file with complete 32-byte restoration target")
    matrix.add_argument("--accept-test-fixture", action="store_true",
                        help="explicitly overwrite settings with historical test fixture")
    matrix.add_argument("--audit", required=True)
    matrix.add_argument("--resume", action="store_true",
                        help="continue a matching incomplete audit from its first non-PASS phase")
    matrix.add_argument("--non-interactive", action="store_true")
    matrix.add_argument("--commit", action="store_true")
    matrix.set_defaults(func=_cmd_probe_report03_matrix)

    build = subparsers.add_parser("build", help="build and print a report without writing")
    _add_config_arguments(build)
    build.set_defaults(func=_cmd_build)

    apply = subparsers.add_parser("apply", help="validate a target and optionally write")
    apply.add_argument("--device", required=True)
    apply.add_argument("--commit", action="store_true", help="perform HIDIOCSFEATURE")
    _add_config_arguments(apply)
    apply.set_defaults(func=_cmd_apply)

    restore = subparsers.add_parser("restore-report10", help="resend an owner-saved full snapshot")
    restore.add_argument("--device", required=True)
    restore.add_argument("--baseline-report10-hex", required=True)
    restore.add_argument("--audit", required=True)
    restore.add_argument("--commit", action="store_true")
    restore.set_defaults(func=_cmd_restore_report10)

    probe = subparsers.add_parser(
        "probe-direct",
        help="baseline/test/restore with Linux input-event confirmation",
    )
    probe.add_argument("--device", required=True)
    probe.add_argument("--event", action="append", help="explicit /dev/input/eventN; repeatable")
    probe.add_argument("--input-hidraw", action="append", default=[],
                       help="raw HID input node; required for unknown code 6")
    probe.add_argument(
        "--keep-open",
        action="append",
        default=[],
        metavar="/dev/hidrawN",
        help="hold an additional hidraw node open until baseline restoration; repeatable",
    )
    probe.add_argument("--slot", type=int, choices=range(1, 8), default=7)
    probe.add_argument(
        "--action",
        type=_parse_direct_action,
        default=DirectAction.UNKNOWN_DIRECT_CODE_6,
        metavar="left|right|middle|backward|forward|unknown6",
    )
    probe.add_argument(
        "--expect-code",
        type=lambda value: int(value, 0),
        help="override expected Linux input code (decimal or 0xNN)",
    )
    probe.add_argument("--timeout", type=float, default=15.0)
    probe.add_argument("--motion-timeout", type=float, default=30.0)
    probe.add_argument("--presses", type=_parse_matrix_presses, default=10)
    probe.add_argument("--baseline-report10-hex", help="owner-saved complete 32-byte snapshot")
    probe.add_argument("--baseline-report10-file", help="private text file with complete restoration target")
    probe.add_argument("--accept-test-fixture", action="store_true",
                       help="explicitly overwrite settings with historical test fixture")
    probe.add_argument("--audit", help="write JSON audit log to this path")
    probe.add_argument("--non-interactive", action="store_true")
    probe.add_argument("--commit", action="store_true", help="required safety acknowledgement")
    probe.set_defaults(func=_cmd_probe_direct)

    probe03 = subparsers.add_parser(
        "probe-report03",
        help="exploratory single-cycle observation; full validation uses matrix probe",
    )
    probe03.add_argument("--device", required=True, help="Report 0x10 target")
    probe03.add_argument("--input-hidraw", required=True, help="raw C658 input node")
    probe03.add_argument("--event", required=True, help="evdev node used to verify restoration")
    probe03.add_argument("--slot", type=int, choices=range(1, 8), default=7)
    probe03.add_argument("--host-index", type=int, choices=range(1, 8), default=1,
                         help="Report 0x03 candidate bitmap index 1..7 (hardware validation pending)")
    probe03.add_argument("--timeout", type=float, default=30.0)
    probe03.add_argument("--audit")
    probe03.add_argument("--non-interactive", action="store_true")
    probe03.add_argument("--commit", action="store_true")
    probe03.set_defaults(func=_cmd_probe_report03)

    cache = subparsers.add_parser(
        "probe-cache",
        help="verify Linux SDK identical suppression and failure-clear policy",
    )
    cache.add_argument("--device", required=True)
    cache.add_argument("--slot", type=int, choices=range(1, 8), default=7)
    cache.add_argument("--audit")
    cache.add_argument("--non-interactive", action="store_true")
    cache.add_argument("--commit", action="store_true")
    cache.set_defaults(func=_cmd_probe_cache)

    pair = subparsers.add_parser(
        "pair",
        help="guarded experimental C652 pairing with slot snapshots and forced stop",
    )
    pair.add_argument("--device", required=True, help="C652 management hidraw node")
    pair.add_argument("--timeout", type=float, default=60.0)
    pair.add_argument("--poll-interval", type=float, default=1.0)
    pair.add_argument("--expect-type", type=lambda value: int(value, 0), default=0x59)
    pair.add_argument("--audit")
    pair.add_argument("--non-interactive", action="store_true")
    pair.add_argument("--commit-experimental-pairing", action="store_true")
    pair.set_defaults(func=_cmd_pair)

    unpair = subparsers.add_parser(
        "unpair",
        help="guarded experimental removal of one explicitly verified receiver slot",
    )
    unpair.add_argument("--device", required=True, help="C652 management hidraw node")
    unpair.add_argument("--slot", type=int, choices=range(0, 5), required=True)
    unpair.add_argument(
        "--expect-raw", type=_parse_raw_slot,
        help="exact 8-byte raw slot value printed by the dry-run",
    )
    unpair.add_argument("--timeout", type=float, default=15.0)
    unpair.add_argument("--poll-interval", type=float, default=0.5)
    unpair.add_argument("--audit", required=True)
    unpair.add_argument("--non-interactive", action="store_true")
    unpair.add_argument("--commit-experimental-unpair", action="store_true")
    unpair.set_defaults(func=_cmd_unpair)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        return int(args.func(args))
    except KeyError as exc:
        parser.error(f"unknown action token: {exc.args[0]}")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
