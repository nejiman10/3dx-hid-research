"""Simultaneous hidraw and evdev capture for controlled Report 0x03 tests."""

from __future__ import annotations

import os
import selectors
import time
from dataclasses import dataclass
from pathlib import Path

from .input_events import EV_KEY, INPUT_EVENT


@dataclass(frozen=True)
class CaptureResult:
    raw_reports: tuple[dict[str, object], ...]
    key_events: tuple[dict[str, object], ...]


class MultiInputCapture:
    def __init__(self, hidraw_paths: list[str], event_paths: list[str]) -> None:
        self.hidraw_paths = list(dict.fromkeys(hidraw_paths))
        self.event_paths = list(dict.fromkeys(event_paths))
        self._selector = selectors.DefaultSelector()
        self._fds: dict[int, tuple[str, str]] = {}
        self._pending: dict[int, bytearray] = {}

    def __enter__(self) -> "MultiInputCapture":
        try:
            for kind, paths in (("hidraw", self.hidraw_paths), ("evdev", self.event_paths)):
                for path in paths:
                    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
                    self._fds[fd] = (kind, path)
                    self._pending[fd] = bytearray()
                    self._selector.register(fd, selectors.EVENT_READ)
            self.drain()
            return self
        except Exception:
            self.close()
            raise

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        self._selector.close()
        for fd in list(self._fds):
            os.close(fd)
        self._fds.clear()

    def drain(self) -> None:
        for fd in self._fds:
            while True:
                try:
                    if not os.read(fd, 4096):
                        break
                except BlockingIOError:
                    break
            self._pending[fd].clear()

    def capture(self, seconds: float) -> CaptureResult:
        if seconds <= 0:
            raise ValueError("capture duration must be greater than zero")
        raw: list[dict[str, object]] = []
        keys: list[dict[str, object]] = []
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            events = self._selector.select(deadline - time.monotonic())
            if not events:
                break
            for key, _mask in events:
                fd = int(key.fd)
                kind, path = self._fds[fd]
                try:
                    chunk = os.read(fd, 4096)
                except BlockingIOError:
                    continue
                if not chunk:
                    continue
                now = time.monotonic()
                if kind == "hidraw":
                    raw.append({
                        "time": now,
                        "path": path,
                        "length": len(chunk),
                        "report_id": f"0x{chunk[0]:02x}",
                        "raw_hex": chunk.hex(" "),
                    })
                    continue
                self._pending[fd].extend(chunk)
                while len(self._pending[fd]) >= INPUT_EVENT.size:
                    record = bytes(self._pending[fd][:INPUT_EVENT.size])
                    del self._pending[fd][:INPUT_EVENT.size]
                    sec, usec, event_type, code, value = INPUT_EVENT.unpack(record)
                    if event_type == EV_KEY:
                        keys.append({
                            "time": now,
                            "kernel_time": f"{sec}.{usec:06d}",
                            "path": path,
                            "type": event_type,
                            "code": code,
                            "value": value,
                        })
        return CaptureResult(tuple(raw), tuple(keys))

    def wait_for_mouse_motion(self, timeout_seconds: float) -> CaptureResult:
        """Capture until a Report 0x1b frame contains non-zero X/Y movement."""
        if timeout_seconds <= 0:
            raise ValueError("mouse-motion timeout must be greater than zero")
        raw: list[dict[str, object]] = []
        keys: list[dict[str, object]] = []
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            result = self.capture(min(0.25, deadline - time.monotonic()))
            raw.extend(result.raw_reports)
            keys.extend(result.key_events)
            if any(is_mouse_motion_report(item) for item in result.raw_reports):
                return CaptureResult(tuple(raw), tuple(keys))
        raise TimeoutError("no post-write mouse movement was observed")


def is_mouse_motion_report(item: dict[str, object]) -> bool:
    data = bytes.fromhex(str(item["raw_hex"]))
    return len(data) >= 6 and data[0] == 0x1B and any(data[2:6])


def count_expected_press_transitions(
    raw_reports: list[dict[str, object]],
    report03_mask: int | None,
    report1b_mask: int | None,
) -> int:
    """Count rising edges for the expected host or direct mapping."""
    previous: dict[tuple[str, int], bool] = {}
    count = 0
    for item in raw_reports:
        data = bytes.fromhex(str(item["raw_hex"]))
        if len(data) < 2:
            continue
        mask = None
        if data[0] == 0x03 and report03_mask is not None:
            mask = report03_mask
        elif data[0] == 0x1B and report1b_mask is not None:
            mask = report1b_mask
        if mask is None:
            continue
        key = (str(item["path"]), data[0])
        pressed = bool(data[1] & mask)
        if pressed and not previous.get(key, False):
            count += 1
        previous[key] = pressed
    return count


def evaluate_phase(phase: dict[str, object]) -> dict[str, object]:
    """Grade one bounded trial from its recorded frames, never from ioctl success."""
    raw = phase.get("raw_reports", [])
    if not isinstance(raw, list):
        return {"phase_result": "FAIL", "reasons": ["raw capture is missing"]}
    mask_text = phase.get("expected_report03_mask")
    mask = int(mask_text, 16) if isinstance(mask_text, str) else None
    negative = bool(phase.get("negative_control"))
    requested = phase.get("required_presses")
    requested = requested if isinstance(requested, int) and requested >= 1 else 0
    counts: dict[str, list[int | bool]] = {}
    unexpected: list[str] = []
    for frame in raw:
        data = bytes.fromhex(str(frame.get("raw_hex", "")))
        if len(data) < 2 or data[0] != 0x03:
            continue
        bitmap = int.from_bytes(data[1:], "little")
        if negative:
            unexpected.append(f"0x{bitmap:x}")
            continue
        if mask is None or bitmap not in (0, mask):
            unexpected.append(f"0x{bitmap:x}")
            continue
        path = str(frame.get("path", "unknown"))
        counters = counts.setdefault(path, [0, 0, False])
        active = bitmap == mask
        if active and not counters[2]:
            counters[0] += 1
        if counters[2] and not active:
            counters[1] += 1
        counters[2] = active
    presses, releases = max(((int(c[0]), int(c[1])) for c in counts.values()),
                            default=(0, 0), key=lambda pair: min(pair))
    if mask is None and not negative:
        code = phase.get("expected_evdev_code")
        if isinstance(code, int):
            evdev_counts: dict[str, list[int]] = {}
            for event in phase.get("key_events", []):
                if event.get("code") != code:
                    continue
                pair = evdev_counts.setdefault(str(event.get("path", "unknown")), [0, 0])
                if event.get("value") == 1:
                    pair[0] += 1
                elif event.get("value") == 0:
                    pair[1] += 1
            presses, releases = max(evdev_counts.values(), default=[0, 0],
                                    key=lambda pair: min(pair))
    expected_code = phase.get("expected_evdev_code")
    for event in phase.get("key_events", []):
        if event.get("type") == EV_KEY and event.get("value") in (0, 1):
            if negative or expected_code is None or event.get("code") != expected_code:
                unexpected.append(f"EV_KEY:{event.get('code')}")
    for frame in phase.get("settle_raw_reports", []):
        data = bytes.fromhex(str(frame.get("raw_hex", "")))
        if data and data[0] == 0x03 and any(data[1:]):
            unexpected.append(f"settle:{data.hex()}")
    if phase.get("settle_key_events"):
        unexpected.append("settle:EV_KEY")
    for frame in phase.get("transfer_wait_raw_reports", []):
        data = bytes.fromhex(str(frame.get("raw_hex", "")))
        if data and data[0] == 0x03 and any(data[1:]):
            unexpected.append(f"transfer:{data.hex()}")
    if phase.get("transfer_wait_key_events"):
        unexpected.append("transfer:EV_KEY")
    reasons = []
    if not phase.get("transfer_wait_completed"):
        reasons.append("transfer wait incomplete")
    if phase.get("capture_interrupted"):
        reasons.append("capture interrupted")
    if unexpected:
        reasons.append("unexpected Report 0x03 bitmap")
    if negative:
        if not phase.get("activity_confirmed"):
            reasons.append("transfer activity absent")
        if not phase.get("positive_controls_passed"):
            reasons.append("bracketing positive controls did not pass")
        if not phase.get("observation_window_complete"):
            reasons.append("negative observation window incomplete")
        result = "PASS" if not reasons else ("FAIL" if unexpected else "INCONCLUSIVE")
    else:
        if presses < requested or releases < requested or not phase.get("expected_input_complete"):
            reasons.append("required press/release transitions incomplete")
        result = "PASS" if not reasons else ("FAIL" if unexpected else "INCONCLUSIVE")
    return {
        "phase_result": result, "reasons": reasons,
        "observed_expected_presses": presses, "observed_expected_releases": releases,
        "unexpected_input": sorted(set(unexpected)),
    }


def matrix_success(audit: dict[str, object]) -> bool:
    phases = audit.get("phases", [])
    return bool(
        audit.get("failure") is None
        and phases
        and len(phases) == audit.get("required_phase_count")
        and all(p.get("phase_result") == "PASS" for p in phases if p.get("required", True))
        and audit.get("baseline_restored")
        and audit.get("baseline_transfer_wait_completed")
        and audit.get("baseline_operation_confirmed")
    )


def summarize_capture(
    raw_reports: list[dict[str, object]], expected_report03_mask: int | None
) -> dict[str, object]:
    ids: dict[str, int] = {}
    report03 = []
    report1b_button_values: dict[str, int] = {}
    for item in raw_reports:
        report_id = str(item["report_id"])
        ids[report_id] = ids.get(report_id, 0) + 1
        data = bytes.fromhex(str(item["raw_hex"]))
        if data and data[0] == 0x03 and len(data) >= 2:
            report03.append(data[1] & 0x7F)
        if data and data[0] == 0x1B and len(data) >= 2:
            token = f"0x{data[1]:02x}"
            report1b_button_values[token] = report1b_button_values.get(token, 0) + 1
    return {
        "report_counts": ids,
        "report03_seen": bool(report03),
        "expected_report03_mask": (
            None if expected_report03_mask is None else f"0x{expected_report03_mask:02x}"
        ),
        "report03_expected_mask_seen": (
            False if expected_report03_mask is None
            else any(value & expected_report03_mask for value in report03)
        ),
        "report03_bitmaps": [f"0x{value:02x}" for value in sorted(set(report03))],
        "report1b_button_values": report1b_button_values,
    }
