"""Universal Receiver management operations with strict evidence labels."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .linux_hidraw import C652_PID, C658_VID, HidrawDevice, HidrawInfo, enumerate_hidraw

PAIR_START = bytes((0x41, 0x02, 0x02, 0x00, 0x00))
PAIR_STOP = bytes((0x41, 0x02, 0x00, 0x00, 0x00))
UNPAIR_SUBCOMMAND = 0x04
SLOT_BASE_REPORT_ID = 0x43
SLOT_COUNT = 5


@dataclass(frozen=True)
class ReceiverSlot:
    slot: int
    report_id: int
    device_type: int
    serial_raw: bytes
    raw: bytes

    @property
    def occupied(self) -> bool:
        return self.device_type != 0

    def to_dict(self) -> dict[str, object]:
        return {
            "slot": self.slot,
            "report_id": f"0x{self.report_id:02x}",
            "device_type": f"0x{self.device_type:02x}",
            "occupied": self.occupied,
            "serial_raw_hex": self.serial_raw.hex(" "),
            "raw_hex": self.raw.hex(" "),
            "layout_evidence": "prior-static for device_type/serial interpretation",
        }


def discover_receiver_management(pattern: str = "/dev/hidraw*") -> list[HidrawInfo]:
    """Find C652 nodes declaring the independently confirmed slot report."""

    return [
        item
        for item in enumerate_hidraw(pattern)
        if item.vendor_id == C658_VID
        and item.product_id == C652_PID
        and item.feature_report_lengths.get(SLOT_BASE_REPORT_ID, 0) >= 2
    ]


def validate_receiver_management(
    path: str | os.PathLike[str], *, require_pairing_report: bool = False
) -> HidrawInfo:
    requested = Path(path)
    candidates = discover_receiver_management(str(requested))
    if len(candidates) != 1 or candidates[0].path != requested:
        raise RuntimeError(f"not a validated C652 management node: {requested}")
    item = candidates[0]
    slot_length = item.feature_report_lengths.get(SLOT_BASE_REPORT_ID)
    if slot_length != 8:
        raise RuntimeError(
            f"slot Report 0x43 length is {slot_length}, expected 8 on {requested}"
        )
    if require_pairing_report and item.feature_report_lengths.get(0x41) != 5:
        raise RuntimeError(
            f"pairing Report 0x41 is not declared with length 5 on {requested}"
        )
    return item


def read_receiver_slots(path: str | os.PathLike[str]) -> list[ReceiverSlot]:
    info = validate_receiver_management(path)
    length = info.feature_report_lengths[SLOT_BASE_REPORT_ID]
    slots: list[ReceiverSlot] = []
    with HidrawDevice(path) as device:
        for slot in range(SLOT_COUNT):
            report_id = SLOT_BASE_REPORT_ID + slot
            raw = device.get_feature(report_id, length)
            if len(raw) != length or raw[0] != report_id:
                raise RuntimeError(
                    f"unexpected slot {slot} response: {raw.hex(' ')}"
                )
            slots.append(
                ReceiverSlot(
                    slot=slot,
                    report_id=report_id,
                    device_type=raw[1],
                    serial_raw=raw[2:8],
                    raw=raw,
                )
            )
    return slots


def newly_occupied_slots(
    before: list[ReceiverSlot], after: list[ReceiverSlot]
) -> list[ReceiverSlot]:
    before_map = {item.slot: item for item in before}
    return [
        item
        for item in after
        if not before_map[item.slot].occupied and item.occupied
    ]


def set_pairing_mode(path: str | os.PathLike[str], enabled: bool) -> int:
    validate_receiver_management(path, require_pairing_report=True)
    packet = PAIR_START if enabled else PAIR_STOP
    with HidrawDevice(path) as device:
        return device.set_feature(packet)


def build_unpair_packet(slot: int) -> bytes:
    """Build the prior-static Report 0x41 packet for one explicit slot."""

    if not 0 <= slot < SLOT_COUNT:
        raise ValueError(f"receiver slot must be 0..{SLOT_COUNT - 1}")
    return bytes((0x41, UNPAIR_SUBCOMMAND, slot, 0x00, 0x00))


def unpair_slot(path: str | os.PathLike[str], slot: int) -> int:
    """Send the guarded, prior-static unpair packet for one slot."""

    validate_receiver_management(path, require_pairing_report=True)
    with HidrawDevice(path) as device:
        return device.set_feature(build_unpair_packet(slot))
