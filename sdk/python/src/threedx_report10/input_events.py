"""Minimal Linux input-event observation for physical Report 0x10 checks."""

from __future__ import annotations

import glob
import os
import selectors
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

EV_KEY = 0x01
KEY_PRESS = 1

BTN_LEFT = 0x110
BTN_RIGHT = 0x111
BTN_MIDDLE = 0x112
BTN_SIDE = 0x113
BTN_EXTRA = 0x114
BTN_FORWARD = 0x115
BTN_BACK = 0x116

INPUT_EVENT = struct.Struct("@llHHi")

KEY_NAMES = {
    BTN_LEFT: "BTN_LEFT",
    BTN_RIGHT: "BTN_RIGHT",
    BTN_MIDDLE: "BTN_MIDDLE",
    BTN_SIDE: "BTN_SIDE",
    BTN_EXTRA: "BTN_EXTRA",
    BTN_FORWARD: "BTN_FORWARD",
    BTN_BACK: "BTN_BACK",
}


@dataclass(frozen=True)
class KeyObservation:
    event_path: Path
    code: int
    name: str
    value: int
    monotonic_time: float


def input_event_nodes_for_hidraw(hidraw_path: str | os.PathLike[str]) -> list[Path]:
    """Resolve input event nodes belonging to a hidraw HID device via sysfs.

    The search is deliberately bounded.  Recursive globbing below a sysfs HID
    node can enter a large symlink graph and appear to hang before the first
    user prompt.
    """

    name = Path(hidraw_path).name
    device_root = Path("/sys/class/hidraw") / name / "device"
    if not device_root.exists():
        return []
    return _input_event_nodes_from_device_root(device_root)


def _input_event_nodes_from_device_root(device_root: Path) -> list[Path]:
    """Bounded sysfs layouts used by HID and receiver child nodes."""

    try:
        root = device_root.resolve(strict=True)
    except OSError:
        return []
    patterns = (
        root / "input" / "input*" / "event*",
        root / "input*" / "event*",
        root / "*" / "input" / "input*" / "event*",
        root / "*" / "input*" / "event*",
    )
    names: set[str] = set()
    for pattern in patterns:
        for match in glob.glob(str(pattern)):
            event_name = Path(match).name
            if event_name.startswith("event"):
                names.add(event_name)
    return [Path("/dev/input") / event_name for event_name in sorted(names)]


def wait_for_key_press(
    event_paths: Iterable[str | os.PathLike[str]],
    expected_code: int,
    timeout_seconds: float,
) -> KeyObservation | None:
    """Wait for an expected EV_KEY press across the supplied event devices."""

    if timeout_seconds <= 0:
        raise ValueError("timeout must be greater than zero")
    selector = selectors.DefaultSelector()
    opened: list[int] = []
    try:
        for value in event_paths:
            path = Path(value)
            try:
                fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
            except OSError:
                continue
            opened.append(fd)
            selector.register(fd, selectors.EVENT_READ, path)
        if not opened:
            raise RuntimeError("no readable Linux input event node was available")

        deadline = time.monotonic() + timeout_seconds
        pending: dict[int, bytearray] = {fd: bytearray() for fd in opened}
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            for key, _mask in selector.select(remaining):
                fd = int(key.fd)
                try:
                    chunk = os.read(fd, INPUT_EVENT.size * 32)
                except BlockingIOError:
                    continue
                if not chunk:
                    continue
                pending[fd].extend(chunk)
                while len(pending[fd]) >= INPUT_EVENT.size:
                    record = bytes(pending[fd][: INPUT_EVENT.size])
                    del pending[fd][: INPUT_EVENT.size]
                    _sec, _usec, event_type, code, value = INPUT_EVENT.unpack(record)
                    if event_type == EV_KEY and value == KEY_PRESS and code == expected_code:
                        return KeyObservation(
                            event_path=key.data,
                            code=code,
                            name=KEY_NAMES.get(code, f"KEY_{code}"),
                            value=value,
                            monotonic_time=time.monotonic(),
                        )
    finally:
        selector.close()
        for fd in opened:
            os.close(fd)
