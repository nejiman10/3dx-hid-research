import sys
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
from validate_public import validate_audit, validate_claims, validate_matrix, validate_repository
from threedx_report10.matrix_probe import evaluate_phase
from threedx_report10.cli import _matrix_phases


class ValidatorTests(unittest.TestCase):
    def test_private_source_audits_are_not_public_repository_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "SPEC.md").write_text("- [UNKNOWN] undecided.\n")
            private = root / "evidence/source-private-not-in-repository"
            private.mkdir(parents=True)
            audit = private / "incomplete.json"
            audit.write_text(json.dumps({"schema": "c658-report03-matrix/v3",
                                         "success": False, "phases": []}))
            self.assertEqual(validate_repository(root), [])
            self.assertTrue(validate_audit(audit))

    def test_rejects_missing_referenced_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.json"
            path.write_text(json.dumps({"evidence_files": ["missing.json"]}))
            self.assertTrue(any("missing evidence file" in error
                                for error in validate_audit(path)))

    def test_rejects_claim_without_existing_source(self):
        self.assertTrue(validate_claims("- [CONFIRMED] invented. (source: missing.json)", ROOT))
        self.assertFalse(validate_claims("- [UNKNOWN] undecided.", ROOT))

    def test_rejects_missing_records_and_false_success(self):
        audit = dict(schema="c658-report03-matrix/v3", profile="core", phases=[],
                     required_phase_count=1, requested_presses_per_phase=10,
                     baseline_restored=False, success=True)
        errors = validate_matrix(audit)
        self.assertTrue(any("missing phases" in item for item in errors))
        self.assertTrue(any("baseline" in item for item in errors))

    def test_accepts_complete_context_for_failed_partial_run(self):
        phase = dict(name="radial-host-index-1-before-index-0", required=True,
                     physical_button="radial", report10_hex="10 00",
                     expected_report03_mask="0x01", required_presses=10,
                     transfer_wait_completed=True, expected_input_complete=False,
                     raw_reports=[], key_events=[], settle_raw_reports=[],
                     settle_key_events=[])
        phase.update(evaluate_phase(phase))
        audit = dict(schema="c658-report03-matrix/v3", profile="core",
                     tool_git_commit="abc123", started_at="2026-01-01T00:00:00Z",
                     finished_at="2026-01-01T00:01:00Z", transport="wired",
                     vid="256f", pid="c658", hid_descriptor_sha256={"hidraw0": "abc"},
                     subcommand="probe-report03-matrix", device="/dev/hidraw0",
                     input_hidraw=["/dev/hidraw1"], event=["/dev/input/event0"],
                     baseline_report10_hex="10 00",
                     planned_phase_names=[item["name"] for item in _matrix_phases("core")],
                     required_phase_count=17, requested_presses_per_phase=10,
                     phases=[phase], baseline_restored=True,
                     baseline_transfer_wait_completed=True,
                     baseline_operation_confirmed=True,
                     baseline_expected_evdev_code=272,
                     baseline_check_key_events=[
                         {"path": "/dev/input/event0", "code": 272, "value": value}
                         for _ in range(10) for value in (1, 0)],
                     failure="phase was INCONCLUSIVE", success=False)
        self.assertEqual(validate_matrix(audit), [])

    def test_rejects_forged_phase_counters(self):
        phase = dict(name="left-host-1", required=True,
                     expected_report03_mask="0x01", required_presses=10,
                     transfer_wait_completed=True, expected_input_complete=True,
                     raw_reports=[{"raw_hex": "03 01"}, {"raw_hex": "03 00"}],
                     key_events=[], settle_raw_reports=[], settle_key_events=[])
        phase.update(evaluate_phase(phase))
        phase["observed_expected_presses"] = 10
        phase["phase_result"] = "PASS"
        audit = dict(phases=[phase], required_phase_count=1,
                     requested_presses_per_phase=10, baseline_restored=True,
                     baseline_transfer_wait_completed=True,
                     baseline_operation_confirmed=True, success=True, failure=None)
        errors = validate_matrix(audit)
        self.assertTrue(any("contradicts raw capture" in item for item in errors))
        self.assertTrue(any("count unmet" in item for item in errors))

    def test_negative_needs_actual_adjacent_positive_passes(self):
        negative = dict(name="radial-host-index-0", negative_control=True,
                        positive_controls_passed=True, activity_confirmed=True,
                        observation_window_complete=True, transfer_wait_completed=True,
                        raw_reports=[], key_events=[], required_presses=10,
                        phase_result="PASS", unexpected_input=[])
        negative.update(evaluate_phase(negative))
        audit = dict(phases=[{"name": "before", "phase_result": "FAIL"}, negative,
                             {"name": "after", "phase_result": "PASS"}],
                     required_phase_count=3, requested_presses_per_phase=10)
        self.assertTrue(any("positive-control flag contradicts" in error
                            for error in validate_matrix(audit)))


if __name__ == "__main__":
    unittest.main()
