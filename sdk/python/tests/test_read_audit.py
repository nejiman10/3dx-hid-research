import errno
import unittest
from unittest.mock import patch

from threedx_report10.read_audit import audit_read_paths, planned_gets


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
        return bytes([report_id]) + bytes(length - 1)


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


if __name__ == "__main__":
    unittest.main()
