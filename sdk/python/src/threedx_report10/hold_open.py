"""Keep every wired C658 hidraw interface open across reconnects.

This is an evidence-bounded workaround for the observed Linux behaviour where
ordinary mouse input can stop when no process holds the wired HID interfaces
open.  It does not claim a firmware or kernel root cause.
"""

from __future__ import annotations

import os
import signal
import threading
from pathlib import Path
from typing import Callable, Iterable

from .linux_hidraw import C658_PID, C658_VID, HidrawInfo, enumerate_hidraw


class WiredC658HoldOpen:
    """Maintain O_RDWR handles for all currently enumerated wired C658 nodes."""

    def __init__(
        self,
        *,
        opener: Callable[[Path, int], int] | None = None,
        closer: Callable[[int], None] | None = None,
    ) -> None:
        self._opener = opener or (lambda path, flags: os.open(path, flags))
        self._closer = closer or os.close
        self._fds: dict[Path, int] = {}

    @property
    def held_paths(self) -> tuple[Path, ...]:
        return tuple(sorted(self._fds))

    def reconcile(self, devices: Iterable[HidrawInfo]) -> list[dict[str, object]]:
        targets = {
            item.path
            for item in devices
            if item.vendor_id == C658_VID and item.product_id == C658_PID
        }
        events: list[dict[str, object]] = []
        for path in sorted(set(self._fds) - targets):
            fd = self._fds.pop(path)
            try:
                self._closer(fd)
            except OSError as exc:
                events.append({"event": "close-error", "path": str(path), "error": str(exc)})
            else:
                events.append({"event": "released", "path": str(path)})
        flags = os.O_RDWR | os.O_CLOEXEC | os.O_NONBLOCK
        for path in sorted(targets - set(self._fds)):
            try:
                self._fds[path] = self._opener(path, flags)
            except OSError as exc:
                events.append({"event": "open-error", "path": str(path), "error": str(exc)})
            else:
                events.append({"event": "held", "path": str(path)})
        return events

    def close(self) -> list[dict[str, object]]:
        return self.reconcile(())


def run_wired_hold_open(
    *,
    pattern: str = "/dev/hidraw*",
    poll_interval: float = 1.0,
    once: bool = False,
    emit: Callable[[dict[str, object]], None] | None = None,
) -> int:
    """Run the reconnect-aware foreground keeper used by the systemd unit."""

    if poll_interval <= 0:
        raise ValueError("poll interval must be greater than zero")
    output = emit or (lambda _event: None)
    keeper = WiredC658HoldOpen()
    stop = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    previous: dict[int, object] = {}
    if not once:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, request_stop)
    try:
        while True:
            for event in keeper.reconcile(enumerate_hidraw(pattern)):
                output(event)
            if once or stop.wait(poll_interval):
                break
    finally:
        for event in keeper.close():
            output(event)
        for signum, handler in previous.items():
            signal.signal(signum, handler)  # type: ignore[arg-type]
    return 0
