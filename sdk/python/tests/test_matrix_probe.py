import unittest

from threedx_report10.matrix_probe import (
    count_expected_press_transitions,
    is_mouse_motion_report,
    summarize_capture,
)


class MatrixProbeTests(unittest.TestCase):
    def test_summary_separates_report03_and_mouse_report(self):
        reports = [
            {"report_id": "0x03", "raw_hex": "03 40"},
            {"report_id": "0x03", "raw_hex": "03 00"},
            {"report_id": "0x1b", "raw_hex": "1b 02 00 00 00 00 00 00 00"},
        ]
        summary = summarize_capture(reports, 0x40)
        self.assertTrue(summary["report03_seen"])
        self.assertTrue(summary["report03_expected_mask_seen"])
        self.assertEqual(summary["report_counts"], {"0x03": 2, "0x1b": 1})
        self.assertEqual(summary["report1b_button_values"], {"0x02": 1})

    def test_wrong_slot_does_not_confirm_target_mask(self):
        summary = summarize_capture(
            [{"report_id": "0x03", "raw_hex": "03 01"}], 0x40
        )
        self.assertFalse(summary["report03_expected_mask_seen"])

    def test_mouse_motion_detection_ignores_button_only(self):
        self.assertFalse(is_mouse_motion_report({"raw_hex": "1b 01 00 00 00 00 00 00 00"}))
        self.assertTrue(is_mouse_motion_report({"raw_hex": "1b 00 01 00 00 00 00 00 00"}))

    def test_expected_press_counter_counts_rising_edges(self):
        reports = [
            {"path": "/dev/hidraw5", "raw_hex": "03 01"},
            {"path": "/dev/hidraw5", "raw_hex": "03 01"},
            {"path": "/dev/hidraw5", "raw_hex": "03 00"},
            {"path": "/dev/hidraw5", "raw_hex": "03 01"},
            {"path": "/dev/hidraw5", "raw_hex": "03 00"},
        ]
        self.assertEqual(count_expected_press_transitions(reports, 0x01, None), 2)


if __name__ == "__main__":
    unittest.main()
