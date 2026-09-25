import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from threedx_report10.hold_open_audit import (
    WiredNode, _hold, _run_phase, discover_wired, run,
)


class HoldOpenAuditTests(unittest.TestCase):
    def test_sysfs_discovery_does_not_open_hidraw(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            interface = root / "usb" / "device:1.1"
            hid = interface / "0003:256F:C658"
            hid.mkdir(parents=True)
            (interface / "bInterfaceNumber").write_text("01\n")
            (hid / "uevent").write_text("HID_ID=0003:0000256F:0000C658\n")
            descriptor = bytes.fromhex("05 01 09 02 a1 01 85 10 75 08 95 1f b1 02 c0")
            (hid / "report_descriptor").write_bytes(descriptor)
            entry = root / "class" / "hidraw" / "hidraw16"
            entry.mkdir(parents=True)
            (entry / "device").symlink_to(hid, target_is_directory=True)
            with patch("threedx_report10.hold_open_audit.os.open",
                       side_effect=AssertionError("hidraw opened during discovery")):
                nodes = discover_wired(entry.parent, root / "dev")
            self.assertEqual(len(nodes), 1)
            self.assertEqual(nodes[0].usb_interface, "01")
            self.assertEqual(nodes[0].report10_length, 32)
            self.assertEqual(nodes[0].path, str(root / "dev" / "hidraw16"))

    def test_hold_opens_only_requested_access_mode(self):
        node = WiredNode("/dev/hidraw16", "01", "usb-parent", "hash", 32, 2, ())
        records = []
        self.assertEqual(_hold([node], "A", records), [])
        self.assertEqual(records, [])
        opened = []

        def opener(path, flags):
            opened.append((path, flags))
            return 11

        with patch("threedx_report10.hold_open_audit.os.open", side_effect=opener), \
             patch("threedx_report10.hold_open_audit.os.fstat",
                   return_value=SimpleNamespace(st_mode=stat.S_IFCHR)), \
             patch("threedx_report10.hold_open_audit.fcntl.fcntl", return_value=1):
            self.assertEqual(_hold([node], "B", []), [11])
            self.assertEqual(_hold([node], "C", []), [11])
        self.assertEqual(opened[0][1] & os.O_ACCMODE, os.O_RDONLY)
        self.assertEqual(opened[1][1] & os.O_ACCMODE, os.O_RDWR)
        self.assertTrue(all(flags & os.O_NONBLOCK for _, flags in opened))

    def test_single_interface_hold_opens_only_selected_node(self):
        nodes = [WiredNode(f"/dev/hidraw{number}", interface, "usb-parent", "hash",
                           None, None, ())
                 for number, interface in ((16, "00"), (17, "01"))]
        opened = []

        def opener(path, flags):
            opened.append((path, flags))
            return 11

        with patch("threedx_report10.hold_open_audit.os.open", side_effect=opener), \
             patch("threedx_report10.hold_open_audit.os.fstat",
                   return_value=SimpleNamespace(st_mode=stat.S_IFCHR)), \
             patch("threedx_report10.hold_open_audit.fcntl.fcntl", return_value=1):
            self.assertEqual(_hold(nodes, "MI00", []), [11])
            self.assertEqual(_hold(nodes, "MI01", []), [11])
        self.assertEqual([path for path, _ in opened],
                         ["/dev/hidraw16", "/dev/hidraw17"])
        self.assertTrue(all(flags & os.O_ACCMODE == os.O_RDONLY for _, flags in opened))

    def test_phase_closes_held_fd_after_operator_error(self):
        node = WiredNode("/dev/hidraw16", "01", "usb-parent", "hash", 32, 2, ())
        phase = {}
        with patch("threedx_report10.hold_open_audit._prompt_reconnect", return_value=[node]), \
             patch("threedx_report10.hold_open_audit._visible_other_holders", return_value=0), \
             patch("threedx_report10.hold_open_audit._hold", return_value=[11]), \
             patch("threedx_report10.hold_open_audit.discover_wired", return_value=[node]), \
             patch("threedx_report10.hold_open_audit.time.sleep"), \
             patch("threedx_report10.hold_open_audit._answer",
                   side_effect=RuntimeError("operator stopped")), \
             patch("threedx_report10.hold_open_audit.os.close") as closer:
            with self.assertRaisesRegex(RuntimeError, "operator stopped"):
                _run_phase("C", [node], phase, lambda: None)
        closer.assert_called_once_with(11)
        self.assertIn("fds_closed_at", phase)

    def test_phase_waits_from_reconnect_and_skips_immediate_rating(self):
        node = WiredNode("/dev/hidraw16", "01", "usb-parent", "hash", 32, 2,
                         ("/dev/input/event16",))
        phase = {}
        with patch("threedx_report10.hold_open_audit._prompt_reconnect", return_value=[node]), \
             patch("threedx_report10.hold_open_audit.discover_wired", return_value=[node]), \
             patch("threedx_report10.hold_open_audit._visible_other_holders", return_value=0), \
             patch("threedx_report10.hold_open_audit._hold", return_value=[11]), \
             patch("threedx_report10.hold_open_audit.time.monotonic",
                   side_effect=[100, 100, 130]), \
             patch("threedx_report10.hold_open_audit.time.sleep") as sleeper, \
             patch("threedx_report10.hold_open_audit._answer", return_value="y") as answer, \
             patch("threedx_report10.hold_open_audit._capture_evdev",
                   return_value={"presses": 3, "releases": 3}), \
             patch("threedx_report10.hold_open_audit.os.close"):
            _run_phase("B", [node], phase, lambda: None)
        sleeper.assert_called_once_with(30)
        self.assertEqual(answer.call_count, 2)
        self.assertNotIn("manual_immediate", phase)
        self.assertEqual(phase["settle_elapsed_seconds"], 30)
        self.assertEqual(phase["manual_after_idle"], "y")

    def test_run_restores_active_user_service_after_failed_phase(self):
        node = WiredNode("/dev/hidraw16", "01", "usb-parent", "hash", 32, 2,
                         ("/dev/input/event16",))
        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory) / "private.json"
            preflight = {"service_state": "active", "hidraw_read_write": True,
                         "event_readable": ["/dev/input/event16"]}
            actions = []
            with patch("threedx_report10.hold_open_audit.os.geteuid", return_value=1000), \
                 patch("threedx_report10.hold_open_audit.sys.stdin") as stdin, \
                 patch("threedx_report10.hold_open_audit.preflight", return_value=preflight), \
                 patch("threedx_report10.hold_open_audit.discover_wired", return_value=[node]), \
                 patch("threedx_report10.hold_open_audit._service_state",
                       side_effect=["inactive", "active"]), \
                 patch("threedx_report10.hold_open_audit._service_action",
                       side_effect=lambda action: actions.append(action)), \
                 patch("threedx_report10.hold_open_audit._answer", return_value="y"), \
                 patch("threedx_report10.hold_open_audit._run_phase",
                       side_effect=RuntimeError("trial failed")):
                stdin.isatty.return_value = True
                result = run(audit)
            document = json.loads(audit.read_text())
            self.assertEqual(result, 1)
            self.assertEqual(actions, ["stop", "start"])
            self.assertEqual(document["service_final"], "active")
            self.assertEqual(document["conditions"][0]["failure"], "trial failed")

    def test_run_stops_after_normal_unheld_baseline(self):
        node = WiredNode("/dev/hidraw16", "01", "usb-parent", "hash", 32, 2,
                         ("/dev/input/event16",))
        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory) / "private.json"
            preflight = {"service_state": "inactive", "hidraw_read_write": True,
                         "event_readable": ["/dev/input/event16"]}
            called = []

            def phase_runner(mode, _nodes, phase, _save):
                called.append(mode)
                phase.update({"manual_immediate": "y", "manual_after_idle": "y",
                              "operator_three_clicks": "y"})

            with patch("threedx_report10.hold_open_audit.os.geteuid", return_value=1000), \
                 patch("threedx_report10.hold_open_audit.sys.stdin") as stdin, \
                 patch("threedx_report10.hold_open_audit.preflight", return_value=preflight), \
                 patch("threedx_report10.hold_open_audit.discover_wired", return_value=[node]), \
                 patch("threedx_report10.hold_open_audit._service_state",
                       side_effect=["inactive", "inactive"]), \
                 patch("threedx_report10.hold_open_audit._service_action") as service_action, \
                 patch("threedx_report10.hold_open_audit._answer", return_value="y"), \
                 patch("threedx_report10.hold_open_audit._run_phase", side_effect=phase_runner):
                stdin.isatty.return_value = True
                result = run(audit)
            document = json.loads(audit.read_text())
            self.assertEqual(result, 0)
            self.assertEqual(called, ["A"])
            self.assertIn("stopped_after_A", document)
            self.assertEqual(document["operation_after_restore"], "y")
            service_action.assert_not_called()

    def test_prior_failed_baseline_runs_only_B_and_C(self):
        node = WiredNode("/dev/hidraw16", "01", "usb-parent", "hash", 32, 2,
                         ("/dev/input/event16",))
        with tempfile.TemporaryDirectory() as directory:
            old = Path(directory) / "old.json"
            new = Path(directory) / "new.json"
            old.write_text(json.dumps({
                "schema": "3dx-hold-open-audit/v1", "service_initial": "active",
                "service_final": "active", "conditions": [{
                    "condition": "A", "manual_immediate": "y", "manual_after_idle": "n",
                    "nodes": [node.public_record()], "evdev": {"presses": 0, "releases": 0},
                }],
            }))
            preflight = {"service_state": "inactive", "hidraw_read_write": True,
                         "event_readable": ["/dev/input/event16"]}
            called = []

            def phase_runner(mode, _nodes, phase, _save):
                called.append(mode)
                phase.update({"manual_immediate": "y", "manual_after_idle": "y",
                              "operator_three_clicks": "y"})

            with patch("threedx_report10.hold_open_audit.os.geteuid", return_value=1000), \
                 patch("threedx_report10.hold_open_audit.sys.stdin") as stdin, \
                 patch("threedx_report10.hold_open_audit.preflight", return_value=preflight), \
                 patch("threedx_report10.hold_open_audit.discover_wired", return_value=[node]), \
                 patch("threedx_report10.hold_open_audit._service_state",
                       side_effect=["inactive", "inactive"]), \
                 patch("threedx_report10.hold_open_audit._answer", return_value="y"), \
                 patch("threedx_report10.hold_open_audit._run_phase", side_effect=phase_runner):
                stdin.isatty.return_value = True
                result = run(new, prior_audit=old)
            document = json.loads(new.read_text())
            self.assertEqual(result, 0)
            self.assertEqual(called, ["B", "C"])
            self.assertEqual(document["prior_condition_A"]["manual_after_idle"], "n")
            self.assertEqual(len(document["prior_condition_A"]["sha256"]), 64)

    def test_completed_B_resumes_only_C(self):
        node = WiredNode("/dev/hidraw16", "01", "usb-parent", "hash", 32, 2,
                         ("/dev/input/event16",))
        with tempfile.TemporaryDirectory() as directory:
            old = Path(directory) / "old.json"
            new = Path(directory) / "new.json"
            old.write_text(json.dumps({
                "schema": "3dx-hold-open-audit/v1", "service_initial": "active",
                "service_final": "active", "prior_condition_A": {
                    "manual_immediate": "y", "manual_after_idle": "n",
                }, "conditions": [{
                    "condition": "B", "manual_immediate": "y", "manual_after_idle": "y",
                    "operator_three_clicks": "y", "visible_other_holders": 0,
                    "nodes": [node.public_record()],
                    "open_records": [{"interface": "01", "result": "held",
                                      "requested_flags": os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK}],
                    "evdev": {"presses": 3, "releases": 3},
                }], "failure": "operator response timed out",
            }))
            preflight = {"service_state": "inactive", "hidraw_read_write": True,
                         "event_readable": ["/dev/input/event16"]}
            called = []

            def phase_runner(mode, _nodes, phase, _save):
                called.append(mode)
                phase.update({"manual_immediate": "y", "manual_after_idle": "y",
                              "operator_three_clicks": "y"})

            with patch("threedx_report10.hold_open_audit.os.geteuid", return_value=1000), \
                 patch("threedx_report10.hold_open_audit.sys.stdin") as stdin, \
                 patch("threedx_report10.hold_open_audit.preflight", return_value=preflight), \
                 patch("threedx_report10.hold_open_audit.discover_wired", return_value=[node]), \
                 patch("threedx_report10.hold_open_audit._service_state",
                       side_effect=["inactive", "inactive"]), \
                 patch("threedx_report10.hold_open_audit._answer", return_value="y"), \
                 patch("threedx_report10.hold_open_audit._run_phase", side_effect=phase_runner):
                stdin.isatty.return_value = True
                result = run(new, prior_audit=old)
            document = json.loads(new.read_text())
            self.assertEqual(result, 0)
            self.assertEqual(called, ["C"])
            self.assertEqual(document["prior_condition_A"]["remaining_conditions"], ["C"])
            self.assertEqual(document["prior_condition_A"]["condition_B"]["evdev_presses"], 3)

    def test_repeat_trial_stops_after_B(self):
        node = WiredNode("/dev/hidraw16", "01", "usb-parent", "hash", 32, 2,
                         ("/dev/input/event16",))
        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory) / "repeat.json"
            preflight = {"service_state": "inactive", "hidraw_read_write": True,
                         "event_readable": ["/dev/input/event16"]}
            called = []

            def phase_runner(mode, _nodes, phase, _save):
                called.append(mode)
                phase.update({"manual_immediate": "y",
                              "manual_after_idle": "n" if mode == "A" else "y",
                              "operator_three_clicks": "y"})

            with patch("threedx_report10.hold_open_audit.os.geteuid", return_value=1000), \
                 patch("threedx_report10.hold_open_audit.sys.stdin") as stdin, \
                 patch("threedx_report10.hold_open_audit.preflight", return_value=preflight), \
                 patch("threedx_report10.hold_open_audit.discover_wired", return_value=[node]), \
                 patch("threedx_report10.hold_open_audit._service_state",
                       side_effect=["inactive", "inactive"]), \
                 patch("threedx_report10.hold_open_audit._answer", return_value="y"), \
                 patch("threedx_report10.hold_open_audit._run_phase", side_effect=phase_runner):
                stdin.isatty.return_value = True
                result = run(audit, stop_after_b=True)
            document = json.loads(audit.read_text())
            self.assertEqual(result, 0)
            self.assertEqual(called, ["A", "B"])
            self.assertTrue(document["planned_stop_after_B"])

    def test_unconfirmed_physical_clicks_stop_with_incomplete_result(self):
        node = WiredNode("/dev/hidraw16", "01", "usb-parent", "hash", 32, 2,
                         ("/dev/input/event16",))
        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory) / "incomplete.json"
            preflight = {"service_state": "inactive", "hidraw_read_write": True,
                         "event_readable": ["/dev/input/event16"]}
            called = []

            def phase_runner(mode, _nodes, phase, _save):
                called.append(mode)
                phase.update({"manual_immediate": "y", "manual_after_idle": "n",
                              "operator_three_clicks": "n"})

            with patch("threedx_report10.hold_open_audit.os.geteuid", return_value=1000), \
                 patch("threedx_report10.hold_open_audit.sys.stdin") as stdin, \
                 patch("threedx_report10.hold_open_audit.preflight", return_value=preflight), \
                 patch("threedx_report10.hold_open_audit.discover_wired", return_value=[node]), \
                 patch("threedx_report10.hold_open_audit._service_state",
                       side_effect=["inactive", "inactive"]), \
                 patch("threedx_report10.hold_open_audit._answer", return_value="y"), \
                 patch("threedx_report10.hold_open_audit._run_phase", side_effect=phase_runner):
                stdin.isatty.return_value = True
                result = run(audit, stop_after_b=True)
            document = json.loads(audit.read_text())
            self.assertEqual(result, 1)
            self.assertEqual(called, ["A"])
            self.assertIn("stopped_after_operator_check", document)

    def test_interface_comparison_brackets_single_interface_trials(self):
        nodes = [WiredNode(f"/dev/hidraw{number}", interface, "usb-parent", "hash",
                           None, None, ("/dev/input/event16",))
                 for number, interface in ((16, "00"), (17, "01"))]
        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory) / "interfaces.json"
            preflight = {"service_state": "inactive", "hidraw_read_write": True,
                         "event_readable": ["/dev/input/event16"]}
            called = []

            def phase_runner(mode, _nodes, phase, _save):
                called.append(mode)
                phase.update({"manual_immediate": "y", "manual_after_idle": "y",
                              "operator_three_clicks": "y",
                              "evdev": {"presses": 3, "releases": 3}})

            with patch("threedx_report10.hold_open_audit.os.geteuid", return_value=1000), \
                 patch("threedx_report10.hold_open_audit.sys.stdin") as stdin, \
                 patch("threedx_report10.hold_open_audit.preflight", return_value=preflight), \
                 patch("threedx_report10.hold_open_audit.discover_wired", return_value=nodes), \
                 patch("threedx_report10.hold_open_audit._service_state",
                       side_effect=["inactive", "inactive"]), \
                 patch("threedx_report10.hold_open_audit._answer", return_value="y"), \
                 patch("threedx_report10.hold_open_audit._run_phase", side_effect=phase_runner):
                stdin.isatty.return_value = True
                result = run(audit, compare_interfaces=True)
            document = json.loads(audit.read_text())
            self.assertEqual(result, 0)
            self.assertEqual(called, ["B", "MI00", "MI01", "B"])
            self.assertTrue(document["interface_comparison"])

    def test_interface_comparison_stops_if_first_control_fails(self):
        nodes = [WiredNode(f"/dev/hidraw{number}", interface, "usb-parent", "hash",
                           None, None, ("/dev/input/event16",))
                 for number, interface in ((16, "00"), (17, "01"))]
        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory) / "failed-control.json"
            preflight = {"service_state": "inactive", "hidraw_read_write": True,
                         "event_readable": ["/dev/input/event16"]}
            called = []

            def phase_runner(mode, _nodes, phase, _save):
                called.append(mode)
                phase.update({"manual_immediate": "y", "manual_after_idle": "n",
                              "operator_three_clicks": "y",
                              "evdev": {"presses": 0, "releases": 0}})

            with patch("threedx_report10.hold_open_audit.os.geteuid", return_value=1000), \
                 patch("threedx_report10.hold_open_audit.sys.stdin") as stdin, \
                 patch("threedx_report10.hold_open_audit.preflight", return_value=preflight), \
                 patch("threedx_report10.hold_open_audit.discover_wired", return_value=nodes), \
                 patch("threedx_report10.hold_open_audit._service_state",
                       side_effect=["inactive", "inactive"]), \
                 patch("threedx_report10.hold_open_audit._answer", return_value="y"), \
                 patch("threedx_report10.hold_open_audit._run_phase", side_effect=phase_runner):
                stdin.isatty.return_value = True
                result = run(audit, compare_interfaces=True)
            document = json.loads(audit.read_text())
            self.assertEqual(result, 1)
            self.assertEqual(called, ["B"])
            self.assertIn("stopped_after_control", document)


if __name__ == "__main__":
    unittest.main()
