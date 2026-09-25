import errno
import unittest
from unittest.mock import patch

from threedx_report10.linux_hidraw import HIDIOCGFEATURE, HidrawDevice
from threedx_report10.read_audit import (
    audit_read_paths, planned_gets, planned_report10_readback_gets,
)


class FakeDevice:
    fd = 3

    def __init__(self, path):
        self.path = path
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get_feature(self, report_id, length):
        self.calls.append((report_id, length))
        if report_id == 0x43:
            raise OSError(errno.EPIPE, "Pipe error")
        if report_id == 0x08:
            return b"\x08\x59" + bytes(length - 2)
        return bytes([report_id]) + bytes(length - 1)

    def get_feature_with_result(self, report_id, length):
        raw = self.get_feature(report_id, length)
        return raw, len(raw)


class ReadAuditTests(unittest.TestCase):
    def test_plan_restricts_requests_to_declared_reports_except_get08(self):
        lengths = {0x10: 32, 0x43: 8, 0x44: 7, 0x50: 8}
        self.assertEqual([r[0] for r in planned_gets(0xC652, lengths)],
                         [0x08, 0x43, 0x50])
        self.assertEqual(planned_gets(0xC658, lengths), [])

    def test_audit_records_each_get_failure_and_skips_undeclared(self):
        device = FakeDevice("/dev/hidraw9")
        descriptor = bytes.fromhex(
            "05 01 09 02 a1 01 85 10 75 08 95 1f b1 02 "
            "85 43 95 07 b1 02 85 50 95 07 b1 02 c0"
        )
        with patch("threedx_report10.read_audit.HidrawDevice", return_value=device), \
             patch("threedx_report10.read_audit._read_raw_info", return_value=(3, 0x256F, 0xC652)), \
             patch("threedx_report10.read_audit._read_descriptor", return_value=descriptor), \
             patch("threedx_report10.read_audit.input_event_nodes_for_hidraw", return_value=[]), \
             patch("threedx_report10.read_audit._interface_metadata", return_value={}):
            audit = audit_read_paths("/dev/hidraw9")
        self.assertEqual(device.calls, [(0x08, 8), (0x43, 8), (0x50, 8)])
        self.assertEqual(audit["gets"][1]["errno"], errno.EPIPE)
        self.assertEqual(audit["gets"][2]["response_length"], 8)
        self.assertIn("0x44", [entry["report_id"] for entry in audit["skipped_gets"]])
        self.assertFalse(audit["write_performed"])

    def test_report10_plan_requires_exact_interface_and_descriptor(self):
        lengths = {0x08: 8, 0x10: 32, 0x43: 8}
        self.assertEqual([r[0] for r in planned_report10_readback_gets(
            0xC658, lengths, "01")], [0x10])
        self.assertEqual([r[0] for r in planned_report10_readback_gets(
            0xC652, lengths, "03")], [0x08, 0x10])
        for pid, interface, features in (
            (0xC652, None, lengths), (0xC658, None, lengths),
            (0xC658, "01", {0x10: 31}), (0xC652, "03", {0x10: 32}),
        ):
            with self.subTest(pid=pid, interface=interface, features=features):
                with self.assertRaises(RuntimeError):
                    planned_report10_readback_gets(pid, features, interface)

    def test_report10_audit_records_only_control_and_target_gets(self):
        device = FakeDevice("/dev/hidraw9")
        descriptor = bytes.fromhex(
            "05 01 09 02 a1 01 85 08 75 08 95 07 b1 02 "
            "85 10 95 1f b1 02 85 43 95 07 b1 02 c0"
        )
        with patch("threedx_report10.read_audit.HidrawDevice", return_value=device), \
             patch("threedx_report10.read_audit._read_raw_info", return_value=(3, 0x256F, 0xC652)), \
             patch("threedx_report10.read_audit._read_descriptor", return_value=descriptor), \
             patch("threedx_report10.read_audit.input_event_nodes_for_hidraw", return_value=[]), \
             patch("threedx_report10.read_audit._interface_metadata", return_value={"usb_interface": "03"}):
            audit = audit_read_paths("/dev/hidraw9", report10_readback=True)
        self.assertEqual(device.calls, [(0x08, 8), (0x10, 32)])
        self.assertEqual(audit["gets"][1]["ioctl_result"], 32)
        self.assertTrue(audit["gets"][1]["report_id_matches"])
        self.assertEqual(len(audit["gets"][1]["response_sha256"]), 64)

    def test_report10_audit_stops_before_target_on_other_receiver_identity(self):
        device = FakeDevice("/dev/hidraw9")
        descriptor = bytes.fromhex(
            "05 01 09 02 a1 01 85 08 75 08 95 07 b1 02 "
            "85 10 95 1f b1 02 c0"
        )
        with patch("threedx_report10.read_audit.HidrawDevice", return_value=device), \
             patch("threedx_report10.read_audit._read_raw_info", return_value=(3, 0x256F, 0xC652)), \
             patch("threedx_report10.read_audit._read_descriptor", return_value=descriptor), \
             patch("threedx_report10.read_audit.input_event_nodes_for_hidraw", return_value=[]), \
             patch("threedx_report10.read_audit._interface_metadata", return_value={"usb_interface": "03"}), \
             patch.object(device, "get_feature_with_result", return_value=(b"\x08\x00" + bytes(6), 8)):
            audit = audit_read_paths("/dev/hidraw9", report10_readback=True)
        self.assertEqual(len(audit["gets"]), 1)
        self.assertIn("did not match", audit["failure"])

    def test_get_feature_with_result_uses_get_ioctl_return_length(self):
        device = HidrawDevice("/dev/hidraw9")
        device._fd = 3

        def ioctl(fd, request, buffer, mutate):
            self.assertEqual((fd, request, buffer[0], len(buffer), mutate),
                             (3, HIDIOCGFEATURE(32), 0x10, 32, True))
            buffer[:3] = b"\x10\x01\x02"
            return 3

        with patch("threedx_report10.linux_hidraw.fcntl.ioctl", side_effect=ioctl):
            self.assertEqual(device.get_feature_with_result(0x10, 32),
                             (b"\x10\x01\x02", 3))


if __name__ == "__main__":
    unittest.main()
