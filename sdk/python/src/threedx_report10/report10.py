"""Typed construction and inspection of C658 Feature Report 0x10.

The report is a 32-byte wire buffer: report ID 0x10 followed by a complete
31-byte configuration snapshot.  It is not a patch or read/modify/write format.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Iterable, Sequence

REPORT_ID = 0x10
WIRE_LENGTH = 32
BLOB_LENGTH = 31
BUTTON_COUNT = 7
BUTTON_BLOB_OFFSET = 18
FIXED_WHEEL_RELATED_VALUE = 0x1E


class Report10Error(ValueError):
    """The requested configuration cannot be represented safely."""


class DirectAction(IntEnum):
    """Direct actions reachable in the normal C658 configuration path.

    Code 6 is deliberately not called RadialMenu: the static evidence proves
    that the C658 default initializer writes it, but does not prove its formal
    enum name.
    """

    HID_MOUSE_LEFT = 1
    HID_MOUSE_RIGHT = 2
    HID_MOUSE_MIDDLE_OR_WHEEL_BUTTON = 3
    HID_MOUSE_BACKWARD = 4
    HID_MOUSE_FORWARD = 5
    UNKNOWN_DIRECT_CODE_6 = 6

    @property
    def wire_value(self) -> int:
        return 0x09 + int(self)


@dataclass(frozen=True)
class ButtonMapping:
    """One button entry in the seven-entry Report 0x10 button table."""

    _wire_value: int
    _description: str

    @classmethod
    def direct(cls, action: DirectAction) -> "ButtonMapping":
        if not isinstance(action, DirectAction):
            raise Report10Error("direct action must be a DirectAction value")
        return cls(action.wire_value, action.name)

    @classmethod
    def host_routed(cls, action_index: int) -> "ButtonMapping":
        """Create host-routed mapping encoded as 0x28 + action_index.

        The recovered native generator uses an 8-bit result.  This SDK rejects
        overflow instead of silently wrapping it, so valid indices are 0..215.
        End-to-end Report 0x03 behaviour still requires hardware validation.
        """

        if isinstance(action_index, bool) or not isinstance(action_index, int):
            raise Report10Error("host action index must be an integer")
        if not 0 <= action_index <= 0xD7:
            raise Report10Error("host action index must be in range 0..215")
        return cls(0x28 + action_index, f"HOST_ROUTED_INDEX_{action_index}")

    @property
    def wire_value(self) -> int:
        return self._wire_value

    @property
    def description(self) -> str:
        return self._description


class WheelMode(Enum):
    NORMAL = bytes((0x01, 0xFF, 0x00, 0x00))
    INERTIAL = bytes((0x00, 0x00, 0x00, 0x01))


class PollingRate(IntEnum):
    HZ_1000 = 1000
    HZ_500 = 500
    HZ_250 = 250
    HZ_125 = 125

    @property
    def divider(self) -> int:
        return {1000: 1, 500: 2, 250: 4, 125: 8}[int(self)]


@dataclass(frozen=True)
class LiftDetection:
    """Generic Report 0x10 lift-threshold field.

    C658 3DxSmartUI hides Lift Detection (the recovered UI gate enables it for
    c650 only).  This type implements the generator field because it was
    explicitly requested; it must be treated as an experimental C658 control,
    not as a verified vendor-supported C658 UI feature.
    """

    enabled: bool
    raw_threshold_low_byte: int = 0x1F

    @classmethod
    def disabled(cls) -> "LiftDetection":
        return cls(False, 0x1F)

    @classmethod
    def enabled_with_threshold(cls, raw_threshold_low_byte: int) -> "LiftDetection":
        if isinstance(raw_threshold_low_byte, bool) or not isinstance(raw_threshold_low_byte, int):
            raise Report10Error("lift threshold must be an integer")
        if not 0 <= raw_threshold_low_byte <= 0xFF:
            raise Report10Error("lift threshold low byte must be in range 0..255")
        return cls(True, raw_threshold_low_byte)

    @property
    def encoded_byte(self) -> int:
        if not self.enabled:
            return 0x1F
        if not 0 <= self.raw_threshold_low_byte <= 0xFF:
            raise Report10Error("lift threshold low byte must be in range 0..255")
        return self.raw_threshold_low_byte


def encode_dpi(dpi: int) -> int:
    """Encode DPI using the recovered clamp and floor behaviour."""

    if isinstance(dpi, bool) or not isinstance(dpi, int):
        raise Report10Error("DPI must be an integer")
    if dpi <= 50:
        return 0x01
    if dpi >= 8200:
        return 0xA4
    return dpi // 50


@dataclass(frozen=True)
class Report10Config:
    dpi: int
    lift_detection: LiftDetection
    wheel_mode: WheelMode
    buttons: tuple[ButtonMapping, ...]
    polling_rate: PollingRate

    def __post_init__(self) -> None:
        if len(self.buttons) != BUTTON_COUNT:
            raise Report10Error(f"exactly {BUTTON_COUNT} button mappings are required")
        if not all(isinstance(item, ButtonMapping) for item in self.buttons):
            raise Report10Error("every button mapping must be a ButtonMapping")
        if not isinstance(self.lift_detection, LiftDetection):
            raise Report10Error("lift_detection must be a LiftDetection")
        if not isinstance(self.wheel_mode, WheelMode):
            raise Report10Error("wheel_mode must be a WheelMode")
        if not isinstance(self.polling_rate, PollingRate):
            raise Report10Error("polling_rate must be a PollingRate")
        encode_dpi(self.dpi)

    @classmethod
    def create(
        cls,
        *,
        dpi: int,
        lift_detection: LiftDetection,
        wheel_mode: WheelMode,
        buttons: Sequence[ButtonMapping] | Iterable[ButtonMapping],
        polling_rate: PollingRate,
    ) -> "Report10Config":
        return cls(dpi, lift_detection, wheel_mode, tuple(buttons), polling_rate)

    @classmethod
    def latest_software_baseline(cls) -> "Report10Config":
        """Static-analysis-derived test starting point, not a saved or factory setting."""

        direct = ButtonMapping.direct
        return cls.create(
            dpi=1400,
            lift_detection=LiftDetection.disabled(),
            wheel_mode=WheelMode.NORMAL,
            buttons=(
                direct(DirectAction.HID_MOUSE_LEFT),
                direct(DirectAction.HID_MOUSE_RIGHT),
                direct(DirectAction.HID_MOUSE_MIDDLE_OR_WHEEL_BUTTON),
                direct(DirectAction.HID_MOUSE_MIDDLE_OR_WHEEL_BUTTON),
                direct(DirectAction.HID_MOUSE_FORWARD),
                direct(DirectAction.HID_MOUSE_BACKWARD),
                direct(DirectAction.HID_MOUSE_MIDDLE_OR_WHEEL_BUTTON),
            ),
            polling_rate=PollingRate.HZ_1000,
        )

    def to_blob(self) -> bytes:
        """Build the complete 31-byte payload with all reserved bytes zeroed."""

        blob = bytearray(BLOB_LENGTH)
        blob[1] = encode_dpi(self.dpi)
        blob[2] = self.lift_detection.encoded_byte
        blob[3:7] = self.wheel_mode.value
        for index, mapping in enumerate(self.buttons):
            blob[BUTTON_BLOB_OFFSET + index] = mapping.wire_value
        blob[26] = FIXED_WHEEL_RELATED_VALUE
        blob[30] = self.polling_rate.divider
        return bytes(blob)

    def to_wire_report(self) -> bytes:
        """Build Report ID 0x10 plus the complete 31-byte payload."""

        report = bytes((REPORT_ID,)) + self.to_blob()
        if len(report) != WIRE_LENGTH:  # defensive invariant
            raise AssertionError("Report 0x10 must be exactly 32 bytes")
        return report


@dataclass(frozen=True)
class InspectedButton:
    wire_value: int
    name: str
    supported_for_encoding: bool


@dataclass(frozen=True)
class InspectedReport10:
    dpi_encoded: int
    nominal_dpi: int
    lift_detection: LiftDetection
    wheel_mode: WheelMode
    buttons: tuple[InspectedButton, ...]
    polling_divider: int
    reserved_bytes_are_zero: bool
    fixed_field_is_valid: bool


def _inspect_button(wire: int) -> InspectedButton:
    if 0x0A <= wire <= 0x0F:
        action = DirectAction(wire - 0x09)
        return InspectedButton(wire, action.name, True)
    if 0x10 <= wire <= 0x27:
        return InspectedButton(wire, f"UNKNOWN_UNREACHABLE_DIRECT_WIRE_0x{wire:02X}", False)
    if wire >= 0x28:
        return InspectedButton(wire, f"HOST_ROUTED_INDEX_{wire - 0x28}", True)
    return InspectedButton(wire, f"UNKNOWN_INVALID_WIRE_0x{wire:02X}", False)


def inspect_wire_report(report: bytes | bytearray | memoryview) -> InspectedReport10:
    """Inspect a captured/test vector without claiming device readback support."""

    raw = bytes(report)
    if len(raw) != WIRE_LENGTH:
        raise Report10Error("Report 0x10 wire buffer must be exactly 32 bytes")
    if raw[0] != REPORT_ID:
        raise Report10Error("wire buffer does not start with Report ID 0x10")
    blob = raw[1:]
    wheel_bytes = blob[3:7]
    try:
        wheel_mode = WheelMode(wheel_bytes)
    except ValueError as exc:
        raise Report10Error(f"unknown wheel mode bytes: {wheel_bytes.hex(' ')}") from exc
    divider = blob[30]
    if divider not in (1, 2, 4, 8):
        raise Report10Error(f"unknown polling divider: {divider}")
    reserved = tuple(range(0, 1)) + tuple(range(7, 18)) + (25,) + tuple(range(27, 30))
    return InspectedReport10(
        dpi_encoded=blob[1],
        nominal_dpi=blob[1] * 50,
        lift_detection=(
            LiftDetection.disabled()
            if blob[2] == 0x1F
            else LiftDetection.enabled_with_threshold(blob[2])
        ),
        wheel_mode=wheel_mode,
        buttons=tuple(_inspect_button(value) for value in blob[18:25]),
        polling_divider=divider,
        reserved_bytes_are_zero=all(blob[index] == 0 for index in reserved),
        fixed_field_is_valid=blob[26] == FIXED_WHEEL_RELATED_VALUE,
    )
