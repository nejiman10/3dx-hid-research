"""Parser and Linux hidraw monitor for C658 Input Report 0x03."""

from __future__ import annotations

import os
import selectors
import time
from dataclasses import dataclass
from pathlib import Path

REPORT03_ID = 0x03
# Hardware-confirmed so far: host-routed index 1 produces bit 0 and index 2
# produces bit 1. These masks describe host action indices, not physical slots.
REPORT03_MASKS = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40)


class Report03Error(ValueError):
    pass


@dataclass(frozen=True)
class Report03Frame:
    raw: bytes
    bitmap: int
    previous_bitmap: int
    pressed_mask: int
    released_mask: int
    monotonic_time: float

    def host_index_pressed(self, host_index: int) -> bool:
        return bool(self.pressed_mask & REPORT03_MASKS[host_index - 1])

    def host_index_released(self, host_index: int) -> bool:
        return bool(self.released_mask & REPORT03_MASKS[host_index - 1])


def parse_report03(packet: bytes, previous_bitmap: int = 0) -> Report03Frame:
    if len(packet) < 2:
        raise Report03Error("Report 0x03 packet must contain an ID and bitmap")
    if packet[0] != REPORT03_ID:
        raise Report03Error("packet is not Input Report 0x03")
    bitmap = int.from_bytes(packet[1:5], "little") & 0x7F
    changed = bitmap ^ (previous_bitmap & 0x7F)
    return Report03Frame(
        raw=bytes(packet),
        bitmap=bitmap,
        previous_bitmap=previous_bitmap & 0x7F,
        pressed_mask=changed & bitmap,
        released_mask=changed & previous_bitmap,
        monotonic_time=time.monotonic(),
    )


class Report03Reader:
    """Keep a raw input hidraw node open and decode Report 0x03 transitions."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._fd: int | None = None
        self._previous_bitmap = 0

    def __enter__(self) -> "Report03Reader":
        self._fd = os.open(self.path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    @property
    def fd(self) -> int:
        if self._fd is None:
            raise RuntimeError("Report03Reader is not open")
        return self._fd

    def drain(self) -> None:
        while True:
            try:
                if not os.read(self.fd, 4096):
                    return
            except BlockingIOError:
                return

    def wait_for_host_index_cycle(
        self, host_index: int, timeout_seconds: float
    ) -> tuple[bool, list[Report03Frame]]:
        if not 1 <= host_index <= 7:
            raise ValueError("host index must be in range 1..7 for Report 0x03 bitmap verification")
        if timeout_seconds <= 0:
            raise ValueError("timeout must be greater than zero")
        target = REPORT03_MASKS[host_index - 1]
        saw_press = False
        frames: list[Report03Frame] = []
        selector = selectors.DefaultSelector()
        selector.register(self.fd, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout_seconds
        try:
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                events = selector.select(remaining)
                if not events:
                    break
                for _key, _mask in events:
                    try:
                        packet = os.read(self.fd, 4096)
                    except BlockingIOError:
                        continue
                    if not packet or packet[0] != REPORT03_ID:
                        continue
                    frame = parse_report03(packet, self._previous_bitmap)
                    self._previous_bitmap = frame.bitmap
                    frames.append(frame)
                    if frame.pressed_mask & target:
                        saw_press = True
                    if saw_press and frame.released_mask & target:
                        return True, frames
            return False, frames
        finally:
            selector.close()

    def wait_for_slot_cycle(
        self, slot: int, timeout_seconds: float
    ) -> tuple[bool, list[Report03Frame]]:
        """Compatibility alias; argument is a host index, not a physical slot."""
        return self.wait_for_host_index_cycle(slot, timeout_seconds)
