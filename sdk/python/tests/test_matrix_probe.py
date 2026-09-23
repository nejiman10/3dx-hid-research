import unittest

from threedx_report10.matrix_probe import (
    count_expected_press_transitions,
    evaluate_phase,
    is_mouse_motion_report,
    matrix_success,
    summarize_capture,
)


class MatrixProbeTests(unittest.TestCase):
    def _phase(self):
        return {
            "name": "left-host-index-1", "required": True,
            "expected_report03_mask": "0x01", "required_presses": 10,
            "transfer_wait_completed": True, "expected_input_complete": True,
            "raw_reports": [
                {"raw_hex": value} for _ in range(10) for value in ("03 01", "03 00")
            ], "key_events": [], "settle_raw_reports": [], "settle_key_events": [],
        }

    def test_positive_requires_all_press_and_release_transitions(self):
        phase = self._phase()
        self.assertEqual(evaluate_phase(phase)["phase_result"], "PASS")
        phase["raw_reports"].pop()
        self.assertEqual(evaluate_phase(phase)["observed_expected_releases"], 9)
        self.assertEqual(evaluate_phase(phase)["phase_result"], "INCONCLUSIVE")
        phase["expected_input_complete"] = False
        self.assertEqual(evaluate_phase(phase)["phase_result"], "INCONCLUSIVE")

    def test_old_bitmap_and_transfer_failure_prevent_pass(self):
        phase = self._phase()
        phase["raw_reports"].insert(0, {"raw_hex": "03 02"})
        self.assertEqual(evaluate_phase(phase)["phase_result"], "FAIL")
        self.assertIn("0x2", evaluate_phase(phase)["unexpected_input"])
        phase = self._phase()
        phase["transfer_wait_completed"] = False
        self.assertEqual(evaluate_phase(phase)["phase_result"], "INCONCLUSIVE")

    def test_duplicate_event_nodes_do_not_double_physical_count(self):
        phase = self._phase()
        phase.update(expected_report03_mask=None, expected_evdev_code=0x111,
                     raw_reports=[], key_events=[
                         {"path": path, "type": 1, "code": 0x111, "value": value}
                         for path in ("event1", "event2")
                         for _ in range(5) for value in (1, 0)
                     ])
        result = evaluate_phase(phase)
        self.assertEqual(result["observed_expected_presses"], 5)
        self.assertEqual(result["phase_result"], "INCONCLUSIVE")

    def test_negative_requires_activity_controls_and_full_window(self):
        phase = self._phase()
        phase.update(negative_control=True, raw_reports=[], activity_confirmed=True,
                     positive_controls_passed=True, observation_window_complete=True)
        self.assertEqual(evaluate_phase(phase)["phase_result"], "PASS")
        phase["positive_controls_passed"] = False
        self.assertEqual(evaluate_phase(phase)["phase_result"], "INCONCLUSIVE")
        phase["positive_controls_passed"] = True
        phase["raw_reports"] = [{"raw_hex": "03 00"}]
        self.assertEqual(evaluate_phase(phase)["phase_result"], "FAIL")

    def test_overall_rejects_incomplete_phase_or_restore(self):
        phase = self._phase()
        phase.update(evaluate_phase(phase))
        audit = dict(phases=[phase], required_phase_count=1, failure=None,
                     baseline_restored=True, baseline_transfer_wait_completed=True,
                     baseline_operation_confirmed=True)
        self.assertTrue(matrix_success(audit))
        phase["phase_result"] = "INCONCLUSIVE"
        self.assertFalse(matrix_success(audit))
        phase["phase_result"] = "PASS"
        audit["baseline_operation_confirmed"] = False
        self.assertFalse(matrix_success(audit))

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
