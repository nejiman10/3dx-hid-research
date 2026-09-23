import unittest

from threedx_report10 import (
    ButtonMapping,
    DirectAction,
    LiftDetection,
    PollingRate,
    Report10Config,
    Report10Error,
    WheelMode,
    encode_dpi,
    inspect_wire_report,
)


BASELINE = bytes.fromhex(
    "10 00 1c 1f 01 ff 00 00 00 00 00 00 00 00 00 00 "
    "00 00 00 0a 0b 0c 0c 0e 0d 0c 00 1e 00 00 00 01"
)


class Report10Tests(unittest.TestCase):
    def test_software_baseline_golden_vector(self):
        self.assertEqual(Report10Config.latest_software_baseline().to_wire_report(), BASELINE)

    def test_dpi_boundaries(self):
        expected = {
            -1: 0x01,
            0: 0x01,
            50: 0x01,
            51: 0x01,
            99: 0x01,
            100: 0x02,
            8199: 0xA3,
            8200: 0xA4,
            99999: 0xA4,
        }
        for dpi, encoded in expected.items():
            with self.subTest(dpi=dpi):
                self.assertEqual(encode_dpi(dpi), encoded)

    def test_all_supported_direct_codes_including_unknown_code_6(self):
        wires = [ButtonMapping.direct(action).wire_value for action in DirectAction]
        self.assertEqual(wires, [0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F])
        self.assertEqual(DirectAction.UNKNOWN_DIRECT_CODE_6.name, "UNKNOWN_DIRECT_CODE_6")

    def test_lift_detection_enabled_and_disabled(self):
        base = Report10Config.latest_software_baseline()
        disabled = base.to_blob()
        enabled_config = Report10Config.create(
            dpi=base.dpi,
            lift_detection=LiftDetection.enabled_with_threshold(0x07),
            wheel_mode=base.wheel_mode,
            buttons=base.buttons,
            polling_rate=base.polling_rate,
        )
        self.assertEqual(disabled[2], 0x1F)
        self.assertEqual(enabled_config.to_blob()[2], 0x07)

    def test_inertial_wheel_and_polling(self):
        base = Report10Config.latest_software_baseline()
        config = Report10Config.create(
            dpi=base.dpi,
            lift_detection=base.lift_detection,
            wheel_mode=WheelMode.INERTIAL,
            buttons=base.buttons,
            polling_rate=PollingRate.HZ_125,
        )
        blob = config.to_blob()
        self.assertEqual(blob[3:7], bytes.fromhex("00 00 00 01"))
        self.assertEqual(blob[30], 8)

    def test_host_routed_boundaries(self):
        self.assertEqual(ButtonMapping.host_routed(0).wire_value, 0x28)
        self.assertEqual(ButtonMapping.host_routed(215).wire_value, 0xFF)
        with self.assertRaises(Report10Error):
            ButtonMapping.host_routed(216)

    def test_reserved_and_fixed_fields(self):
        blob = Report10Config.latest_software_baseline().to_blob()
        reserved = [0, *range(7, 18), 25, *range(27, 30)]
        self.assertTrue(all(blob[index] == 0 for index in reserved))
        self.assertEqual(blob[26], 0x1E)

    def test_exactly_seven_buttons_required(self):
        with self.assertRaises(Report10Error):
            Report10Config.create(
                dpi=1400,
                lift_detection=LiftDetection.disabled(),
                wheel_mode=WheelMode.NORMAL,
                buttons=[ButtonMapping.direct(DirectAction.HID_MOUSE_LEFT)],
                polling_rate=PollingRate.HZ_1000,
            )

    def test_inspection_uses_unknown_name_for_unreachable_direct_wire(self):
        report = bytearray(BASELINE)
        report[19] = 0x10
        inspected = inspect_wire_report(report)
        self.assertEqual(inspected.buttons[0].name, "UNKNOWN_UNREACHABLE_DIRECT_WIRE_0x10")
        self.assertFalse(inspected.buttons[0].supported_for_encoding)


if __name__ == "__main__":
    unittest.main()

