"""Command-line hardware tool connected to the Report 0x10 SDK."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import selectors
import sys
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


def _parse_stages(value: str) -> tuple[int, ...]:
    try:
        stages = tuple(dict.fromkeys(int(item.strip()) for item in value.split(",")))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("stages must be comma-separated numbers 1..4") from exc
    if not stages or any(stage not in (1, 2, 3, 4) for stage in stages):
        raise argparse.ArgumentTypeError("stages must contain only 1,2,3,4")
    return stages


def _probe_baseline(args: argparse.Namespace) -> bytes:
    supplied = getattr(args, "baseline_report10_hex", None)
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


def _matrix_phases(stages: tuple[int, ...], selected_slot: int) -> list[dict[str, object]]:
    phases: list[dict[str, object]] = []
    if 1 in stages:
        phases.extend([
            {"stage": 1, "name": "direct-right-control", "slot": selected_slot,
             "mapping": ButtonMapping.direct(DirectAction.HID_MOUSE_RIGHT)},
            {"stage": 1, "name": "host-index-0", "slot": selected_slot,
             "mapping": ButtonMapping.host_routed(0), "negative_control": True},
            {"stage": 1, "name": "host-index-1", "slot": selected_slot,
             "mapping": ButtonMapping.host_routed(1)},
            {"stage": 1, "name": "unknown-direct-code-6", "slot": selected_slot,
             "mapping": ButtonMapping.direct(DirectAction.UNKNOWN_DIRECT_CODE_6)},
        ])
    if 2 in stages:
        phases.extend([
            {"stage": 2, "name": "wired-or-selected-direct-right-control", "slot": selected_slot,
             "mapping": ButtonMapping.direct(DirectAction.HID_MOUSE_RIGHT)},
            {"stage": 2, "name": "wired-or-selected-host-index-1-repeat", "slot": selected_slot,
             "mapping": ButtonMapping.host_routed(1)},
        ])
    if 3 in stages:
        for index in range(0, 8):
            if index == 0:
                phases.append({"stage": 3, "name": "before-host-index-0-control", "slot": selected_slot,
                               "mapping": ButtonMapping.host_routed(1)})
            phases.append({"stage": 3, "name": f"host-index-{index}", "slot": selected_slot,
                           "mapping": ButtonMapping.host_routed(index), "negative_control": index == 0})
            if index == 0:
                phases.append({"stage": 3, "name": "after-host-index-0-control", "slot": selected_slot,
                               "mapping": ButtonMapping.host_routed(1)})
    if 4 in stages:
        for slot in range(1, 8):
            button = PHYSICAL_BUTTON_NAMES[slot - 1]
            for index in range(1, 8):
                for label, mapping in (
                    ("before-control", ButtonMapping.direct(DirectAction.HID_MOUSE_RIGHT)),
                    ("host", ButtonMapping.host_routed(index)),
                    ("after-control", ButtonMapping.direct(DirectAction.HID_MOUSE_RIGHT)),
                ):
                    phases.append({"stage": 4, "name": f"{button}-{label}-index-{index}",
                                   "slot": slot, "mapping": mapping})
    return phases


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
        if has_expected_input:
            observed = count_expected_press_transitions(raw, report03_mask, None)
            releases = sum(
                bytes.fromhex(str(item["raw_hex"]))[0] == 0x03
                and bytes.fromhex(str(item["raw_hex"]))[1] == 0
                for item in raw if len(bytes.fromhex(str(item["raw_hex"]))) >= 2
            ) if report03_mask is not None else 0
            if expected_evdev_code is not None:
                observed = sum(e["code"] == expected_evdev_code and e["value"] == 1 for e in keys)
                releases = sum(e["code"] == expected_evdev_code and e["value"] == 0 for e in keys)
    return raw, keys, observed, bool(
        has_expected_input and observed >= requested_presses and releases >= requested_presses
    )


def _cmd_probe_report03_matrix(args: argparse.Namespace) -> int:
    if not args.commit:
        print("probe-report03-matrix requires --commit because it writes Report 0x10", file=sys.stderr)
        return 2
    target = validate_report10_target(args.device)
    phases = _matrix_phases(args.stages, args.slot)
    baseline = _probe_baseline(args)
    baseline_code = _baseline_expected_code(baseline, args.slot)
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
        "schema": "c658-report03-matrix/v2",
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
        "stages": list(args.stages),
        "selected_slot": args.slot,
        "requested_presses_per_phase": args.presses,
        "required_phase_count": len(phases),
        "capture_seconds_per_phase": args.phase_seconds,
        "settle_seconds_after_write": args.settle_seconds,
        "post_write_motion_timeout": args.motion_timeout,
        "evidence_note": "Report 0x17 byte2 remains UNKNOWN_CHARGING_STATE_CANDIDATE",
        "phases": [],
        "baseline_restored": False,
        "baseline_report10_hex": baseline.hex(" "),
        "baseline_expected_evdev_code": baseline_code,
        "baseline_source": "provided-host-snapshot" if args.baseline_report10_hex else "explicit-test-fixture",
        "baseline_transfer_wait_completed": False,
        "baseline_operation_confirmed": False,
        "failure": None,
    }
    try:
        with MultiInputCapture(args.input_hidraw, args.event) as capture, HidrawDevice(args.device) as device:
            try:
                for number, specification in enumerate(phases, 1):
                    slot = int(specification["slot"])
                    button_name = PHYSICAL_BUTTON_NAMES[slot - 1]
                    mapping = specification["mapping"]
                    config = _mapped_report(baseline, slot, mapping)
                    negative = bool(specification.get("negative_control"))
                    print(
                        f"[matrix {number}/{len(phases)} stage {specification['stage']}] "
                        f"applying {specification['name']} for {button_name} button"
                    )
                    device.set_feature(config)
                    capture.drain()
                    print(
                        "[transfer-wait] move the mouse now without pressing any button; "
                        "completion is automatic"
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
                    print(f"[capture] NOW press/release {button_name} at least {args.presses} times "
                          f"within {args.phase_seconds:g} seconds")
                    started = _utc_now()
                    evdev_code = BTN_RIGHT if mapping.wire_value == 0x0B else None
                    raw, keys, observed_presses, expected_complete = _capture_until_expected(
                        capture, mapping, args.presses, args.phase_seconds, evdev_code
                    )
                    phase_record = {
                        "sequence": number,
                        "stage": specification["stage"],
                        "name": specification["name"],
                        "slot": slot,
                        "physical_button": button_name,
                        "required": mapping.wire_value != 0x0F,
                        "negative_control": negative,
                        "required_presses": args.presses,
                        "expected_evdev_code": evdev_code,
                        "expected_report03_mask": (
                            None if _expected_report03_mask(mapping) is None
                            else f"0x{_expected_report03_mask(mapping):02x}"
                        ),
                        "mapping_wire_value": f"0x{mapping.wire_value:02x}",
                        "report10_hex": config.hex(" "),
                        "capture_started_at": started,
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
                        "observation_window_complete": negative,
                        "capture_interrupted": False,
                        "summary": summarize_capture(raw, _expected_report03_mask(mapping)),
                    }
                    phase_record.update(evaluate_phase(phase_record))
                    audit["phases"].append(phase_record)
                for index, phase in enumerate(audit["phases"]):
                    if phase["negative_control"]:
                        before = audit["phases"][index - 1] if index else None
                        after = audit["phases"][index + 1] if index + 1 < len(audit["phases"]) else None
                        phase["positive_controls_passed"] = bool(
                            before and after and
                            evaluate_phase(before)["phase_result"] == "PASS" and
                            evaluate_phase(after)["phase_result"] == "PASS"
                        )
                    phase.update(evaluate_phase(phase))
            finally:
                device.set_feature(baseline)
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
                print(f"[restore-check] press/release {PHYSICAL_BUTTON_NAMES[args.slot - 1]} "
                      f"{args.presses} times within {args.phase_seconds:g} seconds")
                restore_result = capture.capture(args.phase_seconds)
                audit["baseline_check_raw_reports"] = list(restore_result.raw_reports)
                audit["baseline_check_key_events"] = list(restore_result.key_events)
                restore_counts: dict[str, list[int]] = {}
                for event in restore_result.key_events:
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
    except KeyboardInterrupt:
        audit["failure"] = "interrupted by user"
    except Exception as exc:
        audit["failure"] = str(exc)
    if len(audit["phases"]) < len(phases):
        pending = phases[len(audit["phases"])]
        audit["phases"].append({
            "sequence": len(audit["phases"]) + 1,
            "stage": pending["stage"], "name": pending["name"],
            "physical_button": PHYSICAL_BUTTON_NAMES[int(pending["slot"]) - 1],
            "required": True, "phase_result": "INCONCLUSIVE",
            "reasons": [str(audit["failure"] or "capture interrupted")],
            "capture_interrupted": True, "transfer_wait_completed": False,
            "expected_input_complete": False, "raw_reports": [], "key_events": [],
            "observed_expected_presses": 0, "observed_expected_releases": 0,
            "unexpected_input": [],
        })
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


def _write_audit(path: str | None, document: dict[str, object]) -> None:
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
        Path(path).write_text(payload, encoding="utf-8")
        print(f"audit: {path}")
    else:
        print(payload, end="")


def _cmd_probe_direct(args: argparse.Namespace) -> int:
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
        help="controlled direct/host-index/all-slot Report 0x03 investigation",
    )
    matrix.add_argument("--device", required=True, help="Report 0x10 target")
    matrix.add_argument("--input-hidraw", action="append", required=True,
                        help="raw input candidate; repeat for simultaneous capture")
    matrix.add_argument("--event", action="append", required=True,
                        help="evdev input node; repeat when needed")
    matrix.add_argument("--stages", type=_parse_stages, default=(3, 4),
                        help="comma-separated stages (default: 3,4; full matrix)")
    matrix.add_argument("--slot", type=int, choices=range(1, 8), default=7,
                        help="selected slot for stages 1..3")
    matrix.add_argument("--presses", type=int, choices=range(10, 101), default=10)
    matrix.add_argument("--phase-seconds", type=float, default=30.0)
    matrix.add_argument(
        "--motion-timeout", type=float, default=30.0,
        help="maximum wait for post-write Report 0x1b mouse movement",
    )
    matrix.add_argument(
        "--settle-seconds", type=float, default=2.0,
        help="wait after each write before accepting button input (default: 2.0)",
    )
    matrix.add_argument("--baseline-report10-hex", help="owner-saved complete 32-byte snapshot")
    matrix.add_argument("--accept-test-fixture", action="store_true",
                        help="explicitly overwrite settings with historical test fixture")
    matrix.add_argument("--audit", required=True)
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
    probe.add_argument("--baseline-report10-hex", help="owner-saved complete 32-byte snapshot")
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
