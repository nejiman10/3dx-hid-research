"""Linux hidraw transport and descriptor-based device discovery.

This module performs no writes during discovery.  `set_feature` is the explicit
write boundary.  A successful ioctl confirms host-side submission only; it does
not prove that a sleeping wireless mouse applied the configuration.
"""

from __future__ import annotations

import fcntl
import glob
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .hid_descriptor import (
    HidDescriptorError,
    feature_report_wire_lengths,
    input_report_wire_lengths,
)
from .report10 import REPORT_ID, WIRE_LENGTH, Report10Config, Report10Error

BUS_USB = 0x03
C658_VID = 0x256F
C658_PID = 0xC658
C652_PID = 0xC652
HID_MAX_DESCRIPTOR_SIZE = 4096

_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14
_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS
_IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
_IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS
_IOC_WRITE = 1
_IOC_READ = 2


def _ioc(direction: int, kind: int, number: int, size: int) -> int:
    return (
        (direction << _IOC_DIRSHIFT)
        | (kind << _IOC_TYPESHIFT)
        | (number << _IOC_NRSHIFT)
        | (size << _IOC_SIZESHIFT)
    )


def _ior(kind: int, number: int, size: int) -> int:
    return _ioc(_IOC_READ, kind, number, size)


def _iowr(kind: int, number: int, size: int) -> int:
    return _ioc(_IOC_READ | _IOC_WRITE, kind, number, size)


_H = ord("H")
HIDIOCGRDESCSIZE = _ior(_H, 0x01, struct.calcsize("i"))
HIDIOCGRDESC = _ior(_H, 0x02, 4 + HID_MAX_DESCRIPTOR_SIZE)
HIDIOCGRAWINFO = _ior(_H, 0x03, 8)


def HIDIOCSFEATURE(length: int) -> int:
    return _iowr(_H, 0x06, length)


def HIDIOCGFEATURE(length: int) -> int:
    return _iowr(_H, 0x07, length)


@dataclass(frozen=True)
class HidrawInfo:
    path: Path
    bus_type: int
    vendor_id: int
    product_id: int
    feature_report_lengths: dict[int, int]
    input_report_lengths: dict[int, int]


class HidrawDevice:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._fd: int | None = None

    def __enter__(self) -> "HidrawDevice":
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def open(self) -> None:
        if self._fd is None:
            self._fd = os.open(self.path, os.O_RDWR | os.O_CLOEXEC | os.O_NONBLOCK)

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    @property
    def fd(self) -> int:
        if self._fd is None:
            raise RuntimeError("hidraw device is not open")
        return self._fd

    def get_feature(self, report_id: int, length: int) -> bytes:
        if not 1 <= length <= HID_MAX_DESCRIPTOR_SIZE:
            raise ValueError("invalid feature-report length")
        buffer = bytearray(length)
        buffer[0] = report_id
        fcntl.ioctl(self.fd, HIDIOCGFEATURE(length), buffer, True)
        return bytes(buffer)

    def set_feature(self, report: bytes | bytearray | memoryview) -> int:
        buffer = bytearray(report)
        if not buffer:
            raise ValueError("feature report cannot be empty")
        return int(fcntl.ioctl(self.fd, HIDIOCSFEATURE(len(buffer)), buffer, True))

    def apply_report10(self, config: Report10Config) -> int:
        report = config.to_wire_report()
        if report[0] != REPORT_ID or len(report) != WIRE_LENGTH:
            raise Report10Error("refusing malformed Report 0x10")
        return self.set_feature(report)

    def apply_report10_bounded(
        self,
        config: Report10Config,
        *,
        confirm: Callable[[], bool],
        before_retry_activity: Callable[[], None] | None = None,
        max_attempts: int = 2,
    ) -> int:
        """Apply with caller-supplied physical confirmation and bounded retry.

        No timing, wake gesture or confirmation mechanism is invented here.
        The caller owns those hardware-specific operations.
        """

        if not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts must be in range 1..3")
        for attempt in range(1, max_attempts + 1):
            self.apply_report10(config)
            if confirm():
                return attempt
            if attempt < max_attempts and before_retry_activity is not None:
                before_retry_activity()
        raise RuntimeError("Report 0x10 application was not confirmed")


def _read_raw_info(fd: int) -> tuple[int, int, int]:
    buffer = bytearray(8)
    fcntl.ioctl(fd, HIDIOCGRAWINFO, buffer, True)
    bus_type, vendor_id, product_id = struct.unpack("Ihh", buffer)
    return bus_type, vendor_id & 0xFFFF, product_id & 0xFFFF


def _read_descriptor(fd: int) -> bytes:
    size_buffer = bytearray(struct.calcsize("i"))
    fcntl.ioctl(fd, HIDIOCGRDESCSIZE, size_buffer, True)
    size = struct.unpack("i", size_buffer)[0]
    if not 0 < size <= HID_MAX_DESCRIPTOR_SIZE:
        raise OSError(f"invalid hidraw descriptor size: {size}")
    buffer = bytearray(4 + HID_MAX_DESCRIPTOR_SIZE)
    struct.pack_into("I", buffer, 0, size)
    fcntl.ioctl(fd, HIDIOCGRDESC, buffer, True)
    returned_size = struct.unpack_from("I", buffer, 0)[0]
    if returned_size > HID_MAX_DESCRIPTOR_SIZE:
        raise OSError(f"kernel returned invalid descriptor size: {returned_size}")
    return bytes(buffer[4 : 4 + returned_size])


def enumerate_hidraw(pattern: str = "/dev/hidraw*") -> list[HidrawInfo]:
    """Enumerate hidraw nodes; unreadable or malformed nodes are skipped."""

    results: list[HidrawInfo] = []
    for name in sorted(glob.glob(pattern)):
        fd: int | None = None
        try:
            fd = os.open(name, os.O_RDWR | os.O_CLOEXEC | os.O_NONBLOCK)
            bus, vendor, product = _read_raw_info(fd)
            descriptor = _read_descriptor(fd)
            feature_lengths = feature_report_wire_lengths(descriptor)
            input_lengths = input_report_wire_lengths(descriptor)
            results.append(
                HidrawInfo(Path(name), bus, vendor, product, feature_lengths, input_lengths)
            )
        except (OSError, HidDescriptorError):
            continue
        finally:
            if fd is not None:
                os.close(fd)
    return results


def discover_wired_c658(pattern: str = "/dev/hidraw*") -> list[HidrawInfo]:
    return [
        item
        for item in enumerate_hidraw(pattern)
        if item.vendor_id == C658_VID
        and item.product_id == C658_PID
        and item.feature_report_lengths.get(REPORT_ID) == WIRE_LENGTH
    ]


def discover_report03_inputs(pattern: str = "/dev/hidraw*") -> list[HidrawInfo]:
    return [
        item
        for item in enumerate_hidraw(pattern)
        if item.vendor_id == C658_VID
        and item.product_id in (C658_PID, C652_PID)
        and item.input_report_lengths.get(0x03, 0) >= 2
    ]


def discover_receiver_c658_handles(pattern: str = "/dev/hidraw*") -> list[HidrawInfo]:
    """Probe C652 candidates using the Linux-observed GET 0x08 byte1 == 0x59.

    This rule is hardware-confirmed on the tested receiver but was not found as
    a reachable normal-path GET 0x08 call in the independently analysed DLL.
    """

    matches: list[HidrawInfo] = []
    candidates = [
        item
        for item in enumerate_hidraw(pattern)
        if item.vendor_id == C658_VID
        and item.product_id == C652_PID
        and item.feature_report_lengths.get(REPORT_ID) == WIRE_LENGTH
    ]
    for item in candidates:
        try:
            with HidrawDevice(item.path) as device:
                response = device.get_feature(0x08, 8)
            if len(response) == 8 and response[0] == 0x08 and response[1] == 0x59:
                matches.append(item)
        except OSError:
            continue
    return matches


def validate_report10_target(path: str | os.PathLike[str]) -> HidrawInfo:
    """Validate one explicit path before a Report 0x10 write.

    A wired C658 must expose a 32-byte Feature Report 0x10.  A C652 node must
    additionally pass the hardware-observed GET 0x08 / byte1 0x59 probe.
    """

    requested = Path(path)
    candidates = enumerate_hidraw(str(requested))
    if len(candidates) != 1 or candidates[0].path != requested:
        raise RuntimeError(f"unable to inspect hidraw target: {requested}")
    item = candidates[0]
    if item.vendor_id != C658_VID:
        raise RuntimeError(f"refusing non-3Dconnexion VID on {requested}")
    if item.feature_report_lengths.get(REPORT_ID) != WIRE_LENGTH:
        raise RuntimeError(f"{requested} does not declare a 32-byte Feature Report 0x10")
    if item.product_id == C658_PID:
        return item
    if item.product_id != C652_PID:
        raise RuntimeError(f"refusing unsupported PID 0x{item.product_id:04x}")
    try:
        with HidrawDevice(requested) as device:
            response = device.get_feature(0x08, 8)
    except OSError as exc:
        raise RuntimeError(f"C652 paired-device probe failed on {requested}: {exc}") from exc
    if len(response) != 8 or response[0] != 0x08 or response[1] != 0x59:
        raise RuntimeError(
            f"C652 node {requested} is not the observed C658 paired-device handle"
        )
    return item
