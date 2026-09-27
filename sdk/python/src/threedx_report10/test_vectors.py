"""Export reproducible, synthetic SDK test vectors without hardware access."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .hid_descriptor import feature_report_wire_lengths, input_report_wire_lengths, top_level_usages
from .receiver import PAIR_START, PAIR_STOP, build_unpair_packet
from .report03 import parse_report03
from .report10 import ButtonMapping, DirectAction, LiftDetection, PollingRate, Report10Config, WheelMode, inspect_wire_report


def _hex(value: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError("hex input must be a string")
    return bytes.fromhex(value)


def _lengths(value: dict[int, int]) -> dict[str, int]:
    return {f"0x{key:02x}": length for key, length in sorted(value.items())}


def export_vectors(source: dict) -> dict:
    """Convert explicit, device-independent inputs using the SDK's public parsers."""

    wire = []
    for item in source["wire"]:
        config = item["config"]
        buttons = tuple(
            ButtonMapping.host_routed(button["host_index"])
            if "host_index" in button else ButtonMapping.direct(DirectAction[button["direct"]])
            for button in config["buttons"]
        )
        report = Report10Config.create(
            dpi=config["dpi"],
            lift_detection=(
                LiftDetection.disabled() if config["lift_threshold"] is None
                else LiftDetection.enabled_with_threshold(config["lift_threshold"])
            ),
            wheel_mode=WheelMode[config["wheel_mode"]],
            buttons=buttons,
            polling_rate=PollingRate(config["polling_hz"]),
        ).to_wire_report()
        inspected = inspect_wire_report(report)
        wire.append({
            "name": item["name"], "input": config, "wire_hex": report.hex(" "),
            "parsed": {
                "dpi_encoded": inspected.dpi_encoded,
                "nominal_dpi": inspected.nominal_dpi,
                "lift_enabled": inspected.lift_detection.enabled,
                "lift_threshold": inspected.lift_detection.raw_threshold_low_byte,
                "wheel_mode": inspected.wheel_mode.name,
                "buttons": [{"wire_value": f"0x{button.wire_value:02x}", "name": button.name,
                             "supported_for_encoding": button.supported_for_encoding}
                            for button in inspected.buttons],
                "polling_divider": inspected.polling_divider,
                "reserved_bytes_are_zero": inspected.reserved_bytes_are_zero,
                "fixed_field_is_valid": inspected.fixed_field_is_valid,
            },
        })

    descriptors = []
    for item in source["descriptors"]:
        raw = _hex(item["hex"])
        descriptors.append({
            "name": item["name"], "input_hex": raw.hex(" "),
            "feature_wire_lengths": _lengths(feature_report_wire_lengths(raw)),
            "input_wire_lengths": _lengths(input_report_wire_lengths(raw)),
            "top_level_usages": [{"page": f"0x{page:04x}", "usage": f"0x{usage:04x}"}
                                 for page, usage in top_level_usages(raw)],
        })

    report03 = []
    for item in source["report03"]:
        previous = item["previous_bitmap"]
        raw = _hex(item["hex"])
        frame = parse_report03(raw, previous)
        report03.append({
            "name": item["name"], "input_hex": raw.hex(" "),
            "previous_bitmap": previous, "bitmap": frame.bitmap,
            "pressed_mask": frame.pressed_mask, "released_mask": frame.released_mask,
        })

    receiver = []
    for item in source["receiver"]:
        operation = item["operation"]
        if operation == "pair_start":
            packet = PAIR_START
        elif operation == "pair_stop":
            packet = PAIR_STOP
        elif operation == "unpair":
            packet = build_unpair_packet(item["slot"])
        else:
            raise ValueError(f"unsupported receiver operation: {operation}")
        receiver.append({"input": item, "packet_hex": packet.hex(" ")})

    return {"format_version": 1, "wire": wire, "descriptors": descriptors,
            "report03": report03, "receiver": receiver}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="synthetic JSON input")
    parser.add_argument("--output", type=Path, required=True, help="output JSON path")
    args = parser.parse_args(argv)
    source = json.loads(args.input.read_text(encoding="utf-8"))
    result = export_vectors(source)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
