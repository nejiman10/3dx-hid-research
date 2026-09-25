"""Small HID report-descriptor parser for report-length discovery."""

from __future__ import annotations

from dataclasses import dataclass, replace


class HidDescriptorError(ValueError):
    pass


@dataclass
class _Globals:
    report_size: int = 0
    report_count: int = 0
    report_id: int = 0


def _main_report_wire_lengths(descriptor: bytes, wanted_main_tag: int) -> dict[int, int]:
    """Return selected main-item report wire lengths keyed by Report ID.

    Long items are skipped.  Global PUSH/POP, Report Size, Report ID and Report
    Count are tracked.  Multiple Feature main items for one report are summed.
    """

    current = _Globals()
    stack: list[_Globals] = []
    report_bits: dict[int, int] = {}
    offset = 0
    while offset < len(descriptor):
        prefix = descriptor[offset]
        offset += 1
        if prefix == 0xFE:
            if offset + 2 > len(descriptor):
                raise HidDescriptorError("truncated HID long-item header")
            size = descriptor[offset]
            offset += 2  # size and long-item tag
            if offset + size > len(descriptor):
                raise HidDescriptorError("truncated HID long item")
            offset += size
            continue
        size_code = prefix & 0x03
        size = 4 if size_code == 3 else size_code
        item_type = (prefix >> 2) & 0x03
        tag = (prefix >> 4) & 0x0F
        if offset + size > len(descriptor):
            raise HidDescriptorError("truncated HID short item")
        data = descriptor[offset : offset + size]
        offset += size
        value = int.from_bytes(data, "little", signed=False)

        if item_type == 1:  # global
            if tag == 7:
                current.report_size = value
            elif tag == 8:
                if value == 0:
                    raise HidDescriptorError("Report ID zero is invalid")
                current.report_id = value
            elif tag == 9:
                current.report_count = value
            elif tag == 10:  # PUSH
                stack.append(replace(current))
            elif tag == 11:  # POP
                if not stack:
                    raise HidDescriptorError("global POP without PUSH")
                current = stack.pop()
        elif item_type == 0 and tag == wanted_main_tag:
            bits = current.report_size * current.report_count
            report_bits[current.report_id] = report_bits.get(current.report_id, 0) + bits

    return {
        report_id: ((bits + 7) // 8) + (1 if report_id else 0)
        for report_id, bits in report_bits.items()
    }


def feature_report_wire_lengths(descriptor: bytes) -> dict[int, int]:
    """Return Feature Report wire lengths keyed by Report ID."""

    return _main_report_wire_lengths(descriptor, 11)


def input_report_wire_lengths(descriptor: bytes) -> dict[int, int]:
    """Return Input Report wire lengths keyed by Report ID."""

    return _main_report_wire_lengths(descriptor, 8)


def top_level_usages(descriptor: bytes) -> list[tuple[int, int]]:
    """Return Usage Page and Usage for top-level collections."""
    page = 0
    usage: int | None = None
    stack: list[int] = []
    depth = 0
    found: list[tuple[int, int]] = []
    offset = 0
    while offset < len(descriptor):
        prefix = descriptor[offset]
        offset += 1
        if prefix == 0xFE:
            if offset + 2 > len(descriptor):
                raise HidDescriptorError("truncated HID long-item header")
            size = descriptor[offset]
            offset += 2
            if offset + size > len(descriptor):
                raise HidDescriptorError("truncated HID long item")
            offset += size
            continue
        size = (0, 1, 2, 4)[prefix & 0x03]
        if offset + size > len(descriptor):
            raise HidDescriptorError("truncated HID short item")
        value = int.from_bytes(descriptor[offset:offset + size], "little")
        offset += size
        kind = (prefix >> 2) & 3
        tag = (prefix >> 4) & 15
        if kind == 1 and tag == 0:
            page = value
        elif kind == 1 and tag == 10:
            stack.append(page)
        elif kind == 1 and tag == 11:
            if not stack:
                raise HidDescriptorError("global POP without PUSH")
            page = stack.pop()
        elif kind == 2 and tag == 0:
            usage = value
        elif kind == 0 and tag == 10:
            if depth == 0 and usage is not None:
                found.append((page, usage))
            depth += 1
            usage = None
        elif kind == 0 and tag == 12:
            if depth == 0:
                raise HidDescriptorError("END_COLLECTION without COLLECTION")
            depth -= 1
        elif kind == 0:
            usage = None
    return found
