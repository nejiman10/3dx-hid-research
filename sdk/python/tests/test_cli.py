import argparse
import errno
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from threedx_report10 import DirectAction, Report10Config
from threedx_report10.cli import (
    EXPECTED_LINUX_CODES,
    _cmd_pair,
    _cmd_unpair,
    _matrix_phases,
    _probe_baseline,
    _resume_matrix_audit,
    _capture_until_expected,
    _matrix_time_ceiling,
    _write_audit,
    _config_from_args,
    _parse_buttons,
    _parse_direct_action,
    _parse_lift,
    build_parser,
)
from threedx_report10.receiver import ReceiverSlot
from threedx_report10.matrix_probe import CaptureResult
from threedx_report10.matrix_probe import evaluate_phase
from threedx_report10.report10 import ButtonMapping


class CliTests(unittest.TestCase):
    def test_positive_capture_ends_after_complete_cycles(self):
        class FakeCapture:
            def __init__(self):
                self.calls = 0

            def capture(self, _seconds):
                self.calls += 1
                if self.calls == 1:
                    return CaptureResult(tuple(
                        {"path": "hidraw1", "raw_hex": value}
                        for _ in range(10) for value in ("03 01", "03 00")
                    ), ())
                return CaptureResult((), ())

        capture = FakeCapture()
        _, _, count, complete = _capture_until_expected(
            capture, ButtonMapping.host_routed(1), 10, 30.0, early_exit=True)
        self.assertTrue(complete)
        self.assertEqual(count, 10)
        self.assertEqual(capture.calls, 2)

    def test_full_window_keeps_recording_after_old_bitmap_and_expected_cycles(self):
        clock = SimpleNamespace(now=0.0)

        class FakeCapture:
            def __init__(self):
                self.calls = 0

            def capture(self, seconds):
                clock.now += seconds
                self.calls += 1
                if self.calls == 1:
                    values = ("03 20", "03 00")
                elif self.calls == 2:
                    values = tuple(value for _ in range(10) for value in ("03 40", "03 00"))
                else:
                    values = ()
                return CaptureResult(tuple(
                    {"path": "hidraw1", "raw_hex": value} for value in values
                ), ())

        capture = FakeCapture()
        with patch("threedx_report10.cli.time.monotonic", side_effect=lambda: clock.now):
            raw, keys, count, complete = _capture_until_expected(
                capture, ButtonMapping.host_routed(7), 10, 1.0)
        self.assertEqual(capture.calls, 4)
        self.assertEqual(len(raw), 22)
        self.assertEqual(keys, [])
        self.assertEqual(count, 10)
        self.assertTrue(complete)
        grade = evaluate_phase({"raw_reports": raw, "key_events": keys,
                                "expected_report03_mask": "0x40", "required_presses": 10,
                                "expected_input_complete": complete,
                                "transfer_wait_completed": True})
        self.assertEqual(grade["phase_result"], "FAIL")
        self.assertEqual(grade["unexpected_input"], ["0x20"])

    def test_full_window_baseline_check_does_not_stop_on_stale_host_bitmap(self):
        clock = SimpleNamespace(now=0.0)

        class FakeCapture:
            def __init__(self):
                self.calls = 0

            def capture(self, seconds):
                clock.now += seconds
                self.calls += 1
                raw = ({"path": "hidraw1", "raw_hex": "03 20"},) if self.calls == 1 else ()
                keys = tuple({"path": "event1", "type": 1, "code": 272, "value": value}
                             for _ in range(10) for value in (1, 0)) if self.calls == 2 else ()
                return CaptureResult(raw, keys)

        capture = FakeCapture()
        with patch("threedx_report10.cli.time.monotonic", side_effect=lambda: clock.now):
            raw, keys, count, complete = _capture_until_expected(
                capture, ButtonMapping.direct(DirectAction.HID_MOUSE_LEFT), 10, 1.0, 272)
        self.assertEqual(capture.calls, 4)
        self.assertEqual(raw[0]["raw_hex"], "03 20")
        self.assertEqual(len(keys), 20)
        self.assertEqual(count, 10)
        self.assertTrue(complete)

    def test_audit_redacts_receiver_serial_consistently(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.json"
            serial = " ".join(f"{value:02x}" for value in range(1, 7))
            slot = "43 59 " + serial
            _write_audit(str(path), {"before": [{"serial_raw_hex": serial,
                "raw_hex": slot}], "required_expect_raw": slot})
            text = path.read_text()
            self.assertNotIn(serial, text)
            document = json.loads(text)
            self.assertEqual(document["before"][0]["serial_raw_hex"],
                             document["required_expect_raw"].split(" ", 2)[2])

    def test_profiles_keep_factorized_core_and_explicit_exhaustive(self):
        smoke = _matrix_phases("smoke")
        core = _matrix_phases("core")
        exhaustive = _matrix_phases("exhaustive")
        self.assertEqual((len(smoke), len(core), len(exhaustive)), (5, 17, 53))
        self.assertEqual([p["name"] for p in core[:5]], [p["name"] for p in smoke])
        trials = [p for p in exhaustive if not p["negative_control"]]
        self.assertEqual({(p["slot"], p["mapping"].wire_value) for p in trials},
                         {(slot, 0x28 + index) for slot in range(1, 8)
                          for index in range(1, 8)})
        self.assertEqual([p["mapping"].wire_value for p in core if p["negative_control"]],
                         [0x28, 0xff])
        core_pairs = {(p["slot"], p["mapping"].wire_value) for p in core}
        self.assertTrue({(7, 0x28 + index) for index in range(1, 8)} <= core_pairs)
        self.assertTrue({(slot, 0x29) for slot in range(1, 8)} <= core_pairs)
        estimate = _matrix_time_ceiling(core, SimpleNamespace(
            motion_timeout=30, settle_seconds=2, phase_seconds=30))
        self.assertGreaterEqual(estimate, 18)

    def test_resume_rejects_changed_context_and_keeps_passed_prefix(self):
        planned = _matrix_phases("smoke")
        expected = {key: "same" for key in (
            "profile", "transport", "vid", "pid", "device", "input_hidraw", "event",
            "hid_descriptor_sha256", "tool_git_commit", "requested_presses_per_phase",
            "capture_seconds_per_phase", "settle_seconds_after_write",
            "post_write_motion_timeout", "baseline_report10_hex")}
        passed = {"name": planned[0]["name"], "expected_report03_mask": "0x01",
                  "required_presses": 10, "transfer_wait_completed": True,
                  "expected_input_complete": True, "key_events": [],
                  "raw_reports": [
                      {"path": "hidraw1", "raw_hex": value}
                      for _ in range(10) for value in ("03 01", "03 00")
                  ]}
        passed.update(evaluate_phase(passed))
        existing = {**expected, "schema": "c658-report03-matrix/v3", "success": False,
                    "phases": [passed, {"name": planned[1]["name"],
                                        "phase_result": "INCONCLUSIVE"}],
                    "failure": "interrupted", "baseline_restored": True}
        changed = {**expected, "device": "different"}
        with self.assertRaises(RuntimeError):
            _resume_matrix_audit(existing, changed, planned)
        expected["capture_policy_for_new_phases"] = "full-window"
        self.assertEqual(_resume_matrix_audit(existing, expected, planned), 1)
        self.assertEqual(existing["phases"], [passed])
        self.assertEqual(existing["resume_count"], 1)
        self.assertEqual(len(existing["previous_attempts"][0]["discarded_phases"]), 1)

    def test_phase_checkpoint_replaces_complete_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "matrix.json"
            _write_audit(str(path), {"phases": [], "active_phase": "radial-host-index-1"},
                         quiet=True)
            self.assertEqual(json.loads(path.read_text())["active_phase"],
                             "radial-host-index-1")
            _write_audit(str(path), {"phases": [{"name": "radial-host-index-1"}],
                                     "active_phase": None}, quiet=True)
            self.assertEqual(len(json.loads(path.read_text())["phases"]), 1)

    def test_hardware_probe_requires_explicit_baseline_choice(self):
        args = build_parser().parse_args(["probe-report03-matrix", "--device", "/dev/hidraw1",
            "--input-hidraw", "/dev/hidraw2", "--event", "/dev/input/event1", "--audit", "a.json"])
        with self.assertRaises(RuntimeError):
            _probe_baseline(args)
        args.accept_test_fixture = True
        self.assertEqual(len(_probe_baseline(args)), 32)
        self.assertEqual(args.profile, "core")

    def test_restore_accepts_only_complete_saved_report(self):
        args = build_parser().parse_args(["restore-report10", "--device", "/dev/hidraw1",
            "--baseline-report10-hex", "10 00", "--audit", "restore.json"])
        with self.assertRaises(RuntimeError):
            _probe_baseline(args)
        args.baseline_report10_hex = Report10Config.latest_software_baseline().to_wire_report().hex(" ")
        self.assertEqual(len(_probe_baseline(args)), 32)

    def test_default_build_is_software_baseline(self):
        args = build_parser().parse_args(["build"])
        self.assertEqual(
            _config_from_args(args).to_wire_report(),
            Report10Config.latest_software_baseline().to_wire_report(),
        )

    def test_unknown6_token(self):
        mappings = _parse_buttons("left,right,middle,backward,forward,unknown6,host:0")
        self.assertEqual(mappings[5].wire_value, 0x0F)
        self.assertEqual(mappings[6].wire_value, 0x28)

    def test_lift_parser(self):
        self.assertFalse(_parse_lift("disabled").enabled)
        self.assertEqual(_parse_lift("0x07").encoded_byte, 7)

    def test_probe_defaults_to_unknown_code6_and_slot7(self):
        args = build_parser().parse_args(["probe-direct", "--device", "/dev/hidraw9"])
        self.assertEqual(args.action, DirectAction.UNKNOWN_DIRECT_CODE_6)
        self.assertEqual(args.slot, 7)
        self.assertEqual(args.keep_open, [])
        self.assertNotIn(DirectAction.UNKNOWN_DIRECT_CODE_6, EXPECTED_LINUX_CODES)

    def test_probe_accepts_repeatable_keep_open(self):
        args = build_parser().parse_args(
            [
                "probe-direct",
                "--device",
                "/dev/hidraw15",
                "--keep-open",
                "/dev/hidraw11",
                "--keep-open",
                "/dev/hidraw13",
            ]
        )
        self.assertEqual(args.keep_open, ["/dev/hidraw11", "/dev/hidraw13"])

    def test_direct_action_parser_rejects_unknown_name(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            _parse_direct_action("radialmenu")

    def test_exactly_seven_mappings(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            _parse_buttons("left,right")

    def test_new_subcommands_parse_without_writes(self):
        parser = build_parser()
        slots = parser.parse_args(["receiver-slots", "--device", "/dev/hidraw4"])
        self.assertEqual(slots.device, "/dev/hidraw4")
        hold = parser.parse_args(["hold-open", "--once"])
        self.assertTrue(hold.once)
        self.assertEqual(hold.poll_interval, 1.0)
        monitor = parser.parse_args(
            ["monitor-report03", "--input-hidraw", "/dev/hidraw13", "--host-index", "2"]
        )
        self.assertEqual(monitor.host_index, 2)
        raw = parser.parse_args(
            [
                "probe-input-raw", "--device", "/dev/hidraw15",
                "--input-hidraw", "/dev/hidraw15",
                "--input-hidraw", "/dev/hidraw14",
                "--audit", "raw.json",
            ]
        )
        self.assertEqual(raw.input_hidraw, ["/dev/hidraw15", "/dev/hidraw14"])
        matrix = parser.parse_args(
            [
                "probe-report03-matrix", "--device", "/dev/hidraw15",
                "--input-hidraw", "/dev/hidraw14", "--event", "/dev/input/event13",
                "--audit", "matrix.json", "--profile", "core", "--resume",
            ]
        )
        self.assertEqual(matrix.profile, "core")
        self.assertTrue(matrix.resume)
        self.assertEqual(matrix.presses, 10)
        self.assertEqual(matrix.settle_seconds, 2.0)
        self.assertEqual(matrix.motion_timeout, 30.0)
        self.assertFalse(matrix.early_exit)
        self.assertTrue(parser.parse_args([
            "probe-report03-matrix", "--device", "/dev/hidraw15",
            "--input-hidraw", "/dev/hidraw14", "--event", "/dev/input/event13",
            "--audit", "matrix.json", "--early-exit",
        ]).early_exit)
        pair = parser.parse_args(["pair", "--device", "/dev/hidraw4"])
        self.assertFalse(pair.commit_experimental_pairing)
        unpair = parser.parse_args([
            "unpair", "--device", "/dev/hidraw4", "--slot", "1", "--audit", "u.json"
        ])
        self.assertFalse(unpair.commit_experimental_unpair)

    def test_pair_always_sends_stop_after_new_slot(self):
        def make_slot(number, device_type):
            report_id = 0x43 + number
            raw = bytes((report_id, device_type, 1, 2, 3, 4, 5, 6))
            return ReceiverSlot(number, report_id, device_type, raw[2:], raw)

        before = [make_slot(index, 0) for index in range(5)]
        after = [make_slot(index, 0x59 if index == 1 else 0) for index in range(5)]
        args = argparse.Namespace(
            device="/dev/hidraw4",
            timeout=0.1,
            poll_interval=0.01,
            expect_type=0x59,
            audit=None,
            non_interactive=True,
            commit_experimental_pairing=True,
        )
        mode_calls = []
        with (
            patch("threedx_report10.cli.validate_receiver_management"),
            patch("threedx_report10.cli.read_receiver_slots", side_effect=[before, after]),
            patch("threedx_report10.cli._single_management_path", return_value=args.device),
            patch(
                "threedx_report10.cli.set_pairing_mode",
                side_effect=lambda path, enabled: mode_calls.append((path, enabled)) or 0,
            ),
            patch("threedx_report10.cli.discover_receiver_c658_handles", return_value=[]),
            patch("threedx_report10.cli._write_audit"),
        ):
            self.assertEqual(_cmd_pair(args), 0)
        self.assertEqual(mode_calls, [(args.device, True), (args.device, False)])

    def test_unpair_requires_matching_raw_and_confirms_empty_slot(self):
        def make_slot(number, device_type):
            report_id = 0x43 + number
            raw = bytes((report_id, device_type, 1, 2, 3, 4, 5, 6))
            return ReceiverSlot(number, report_id, device_type, raw[2:], raw)

        before = [make_slot(index, 0x59 if index == 1 else 0) for index in range(5)]
        after = [make_slot(index, 0) for index in range(5)]
        args = argparse.Namespace(
            device="/dev/hidraw4", slot=1, expect_raw=before[1].raw,
            timeout=0.1, poll_interval=0.01, audit="unpair.json",
            non_interactive=True, commit_experimental_unpair=True,
        )
        with (
            patch("threedx_report10.cli.validate_receiver_management"),
            patch("threedx_report10.cli.read_receiver_slots", side_effect=[before, after]),
            patch("threedx_report10.cli._single_management_path", return_value=args.device),
            patch("threedx_report10.cli.unpair_slot") as send,
            patch("threedx_report10.cli._write_audit"),
        ):
            self.assertEqual(_cmd_unpair(args), 0)
        send.assert_called_once_with(args.device, 1)

    def test_unpair_epipe_still_polls_and_accepts_confirmed_empty_slot(self):
        def make_slot(number, device_type):
            report_id = 0x43 + number
            raw = bytes((report_id, device_type, 1, 2, 3, 4, 5, 6))
            return ReceiverSlot(number, report_id, device_type, raw[2:], raw)

        before = [make_slot(index, 0x59 if index == 0 else 0) for index in range(5)]
        after = [make_slot(index, 0) for index in range(5)]
        args = argparse.Namespace(
            device="/dev/hidraw4", slot=0, expect_raw=before[0].raw,
            timeout=0.1, poll_interval=0.01, audit="unpair.json",
            non_interactive=True, commit_experimental_unpair=True,
        )
        written = {}
        with (
            patch("threedx_report10.cli.validate_receiver_management"),
            patch("threedx_report10.cli.read_receiver_slots", side_effect=[before, after]),
            patch("threedx_report10.cli._single_management_path", return_value=args.device),
            patch(
                "threedx_report10.cli.unpair_slot",
                side_effect=OSError(errno.EPIPE, "Broken pipe"),
            ),
            patch(
                "threedx_report10.cli._write_audit",
                side_effect=lambda _path, document: written.update(document),
            ),
        ):
            self.assertEqual(_cmd_unpair(args), 0)
        self.assertTrue(written["success"])
        self.assertFalse(written["packet_sent"])
        self.assertEqual(written["ioctl_error"]["name"], "EPIPE")
        self.assertTrue(written["target_empty_confirmed"])


if __name__ == "__main__":
    unittest.main()
