import argparse
import errno
import unittest
from unittest.mock import patch

from threedx_report10 import DirectAction, Report10Config
from threedx_report10.cli import (
    _cmd_pair,
    _cmd_unpair,
    _config_from_args,
    _parse_buttons,
    _parse_direct_action,
    _parse_lift,
    _parse_stages,
    build_parser,
)
from threedx_report10.receiver import ReceiverSlot


class CliTests(unittest.TestCase):
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
                "--audit", "matrix.json", "--stages", "1,3",
            ]
        )
        self.assertEqual(matrix.stages, (1, 3))
        self.assertEqual(matrix.presses, 10)
        self.assertEqual(matrix.settle_seconds, 2.0)
        self.assertEqual(matrix.motion_timeout, 30.0)
        pair = parser.parse_args(["pair", "--device", "/dev/hidraw4"])
        self.assertFalse(pair.commit_experimental_pairing)
        unpair = parser.parse_args([
            "unpair", "--device", "/dev/hidraw4", "--slot", "1", "--audit", "u.json"
        ])
        self.assertFalse(unpair.commit_experimental_unpair)

    def test_matrix_stage_parser_rejects_out_of_range(self):
        self.assertEqual(_parse_stages("4,1,4"), (4, 1))
        with self.assertRaises(argparse.ArgumentTypeError):
            _parse_stages("1,5")

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
