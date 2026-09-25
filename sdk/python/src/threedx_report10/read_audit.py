"""Bounded, read-only audit of HID descriptor and receiver GET paths."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from .hid_descriptor import feature_report_wire_lengths, input_report_wire_lengths, top_level_usages
from .input_events import input_event_nodes_for_hidraw
from .linux_hidraw import (
    BUS_USB, C652_PID, C658_PID, C658_VID, HidrawDevice, _read_descriptor, _read_raw_info,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def planned_gets(pid: int, feature_lengths: dict[int, int]) -> list[tuple[int, int, str]]:
    """Only request the bounded receiver reads used by the earlier audit."""
    if pid != C652_PID:
        return []
    requests: list[tuple[int, int, str]] = []
    if feature_lengths.get(0x10) == 32:
        requests.append((0x08, 8, "C652 Report 0x10 candidate; explicit 8-byte GET probe"))
    for report_id in (*range(0x43, 0x48), 0x50, 0x60):
        if feature_lengths.get(report_id) == 8:
            requests.append((report_id, 8, "descriptor declares an 8-byte Feature report"))
    return requests


def planned_report10_readback_gets(
    pid: int, feature_lengths: dict[int, int], interface: str | None,
) -> list[tuple[int, int, str]]:
    """Select a declared Report 0x10 interface; its MI number may change."""
    if interface is None:
        raise RuntimeError("USB interface number is unavailable")
    if feature_lengths.get(0x10) != 32:
        raise RuntimeError("interface does not declare a 32-byte Feature Report 0x10")
    requests = []
    if pid == C652_PID:
        if feature_lengths.get(0x08) != 8:
            raise RuntimeError("receiver interface does not declare an 8-byte Feature Report 0x08")
        requests.append((0x08, 8, "control GET on paired-device interface"))
    requests.append((0x10, 32, "Report 0x10 readback probe"))
    return requests


def _interface_metadata(path: Path) -> dict[str, object]:
    hid_device = (Path("/sys/class/hidraw") / path.name / "device").resolve()
    result: dict[str, object] = {"hid_sysfs_path": str(hid_device)}
    for ancestor in (hid_device, *hid_device.parents):
        number = ancestor / "bInterfaceNumber"
        if number.is_file():
            result["usb_interface"] = number.read_text(encoding="ascii").strip()
            result["usb_interface_sysfs_path"] = str(ancestor)
            break
    return result


def audit_read_paths(path: str, *, report10_readback: bool = False) -> dict[str, object]:
    """Read one explicit device; record every attempted GET and its result."""
    document: dict[str, object] = {
        "schema": "3dx-read-path-audit/v1", "started_at": _now(),
        "device": path, "write_performed": False, "gets": [],
    }
    try:
        with HidrawDevice(path) as device:
            bus, vid, pid = _read_raw_info(device.fd)
            if (vid != C658_VID or pid not in (C652_PID, C658_PID)
                    or (report10_readback and bus != BUS_USB)):
                raise RuntimeError(f"unexpected device bus={bus} {vid:04x}:{pid:04x}")
            descriptor = _read_descriptor(device.fd)
            features = feature_report_wire_lengths(descriptor)
            inputs = input_report_wire_lengths(descriptor)
            document.update({
                "bus_type": bus, "vid": f"{vid:04x}", "pid": f"{pid:04x}",
                "descriptor_hex": descriptor.hex(" "),
                "descriptor_sha256": hashlib.sha256(descriptor).hexdigest(),
                "top_level_usages": [
                    {"page": f"0x{page:04x}", "usage": f"0x{usage:04x}"}
                    for page, usage in top_level_usages(descriptor)
                ],
                "feature_wire_lengths": {f"0x{k:02x}": v for k, v in features.items()},
                "input_wire_lengths": {f"0x{k:02x}": v for k, v in inputs.items()},
                "input_event_nodes": [str(node) for node in input_event_nodes_for_hidraw(path)],
                "interface": _interface_metadata(Path(path)),
            })
            if report10_readback:
                document["readback_probe"] = True
                requests = planned_report10_readback_gets(
                    pid, features, document["interface"].get("usb_interface")
                )
            else:
                requests = planned_gets(pid, features)
            document["planned_gets"] = [f"0x{rid:02x}" for rid, _, _ in requests]
            if not report10_readback:
                document["skipped_gets"] = [
                    {"report_id": f"0x{rid:02x}", "reason": "8-byte Feature report not declared"}
                    for rid in (*range(0x43, 0x48), 0x50, 0x60)
                    if pid == C652_PID and features.get(rid) != 8
                ]
            for report_id, length, reason in requests:
                entry: dict[str, object] = {
                    "time": _now(), "report_id": f"0x{report_id:02x}",
                    "request_length": length, "reason": reason,
                }
                try:
                    if report10_readback:
                        raw, ioctl_result = device.get_feature_with_result(report_id, length)
                        entry["ioctl_result"] = ioctl_result
                    else:
                        raw = device.get_feature(report_id, length)
                    entry.update({"response_hex": raw.hex(" "), "response_length": len(raw),
                                  "report_id_matches": bool(raw and raw[0] == report_id),
                                  "response_sha256": hashlib.sha256(raw).hexdigest()})
                except OSError as exc:
                    entry.update({"errno": exc.errno, "error": str(exc)})
                document["gets"].append(entry)
                if report10_readback and pid == C652_PID and report_id == 0x08:
                    if "response_hex" in entry and not (
                        len(raw) == 8 and raw[:2] == b"\x08\x59"
                    ):
                        document["failure"] = "GET 0x08 did not match the observed C658 candidate"
                        break
    except (OSError, RuntimeError, ValueError) as exc:
        document["failure"] = str(exc)
    document["finished_at"] = _now()
    return document
