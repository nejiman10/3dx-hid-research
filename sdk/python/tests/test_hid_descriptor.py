import hashlib
import json
import unittest
from pathlib import Path

from threedx_report10 import (
    HidDescriptorError,
    feature_report_wire_lengths,
    input_report_wire_lengths,
)
from threedx_report10.hid_descriptor import top_level_usages


REAL_DESCRIPTORS = Path(__file__).parent / "data" / "real_hid_descriptors.json"


class HidDescriptorTests(unittest.TestCase):
    def test_captured_descriptors(self):
        fixtures = json.loads(REAL_DESCRIPTORS.read_text(encoding="utf-8"))["descriptors"]
        expected = {
            "c652_receiver_mi00": ({0x41: 5, 0x42: 8, 0x43: 8, 0x44: 8, 0x45: 8,
                                    0x46: 8, 0x47: 8, 0x50: 8, 0x51: 9, 0x60: 8, 0x1a: 8},
                                   {}, [(0xff0a, 1)]),
            "c652_receiver_mi02": ({0x10: 32, 0x08: 8, 0x41: 5, 0x42: 8, 0x43: 8,
                                    0x44: 8, 0x45: 8, 0x46: 8, 0x47: 8, 0x50: 8,
                                    0x51: 8, 0x60: 8, 0x1a: 8},
                                   {0x1b: 9, 0x03: 2, 0x17: 3},
                                   [(1, 2), (0xff08, 1), (0xff0a, 1)]),
            "c658_wired_mi00": ({}, {0x1b: 9}, [(1, 2)]),
            "c658_wired_mi01": ({0x10: 32, 0x08: 8, 0x0d: 4, 0x0b: 2, 0x1a: 8},
                                 {0x03: 2, 0x17: 3, 0x0f: 32, 0x20: 16},
                                 [(0xff08, 1)]),
        }
        self.assertEqual({item["name"] for item in fixtures}, set(expected))
        for item in fixtures:
            with self.subTest(name=item["name"]):
                raw = bytes.fromhex(item["descriptor_hex"])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), item["descriptor_sha256"])
                features, inputs, usages = expected[item["name"]]
                self.assertEqual(feature_report_wire_lengths(raw), features)
                self.assertEqual(input_report_wire_lengths(raw), inputs)
                self.assertEqual(top_level_usages(raw), usages)

    def test_feature_report_10_is_32_wire_bytes(self):
        # Report ID 0x10, size 8, count 31, Feature(Data,Var,Abs).
        descriptor = bytes.fromhex("85 10 75 08 95 1f b1 02")
        self.assertEqual(feature_report_wire_lengths(descriptor), {0x10: 32})

    def test_multiple_feature_items_accumulate(self):
        descriptor = bytes.fromhex("85 10 75 08 95 10 b1 02 95 0f b1 02")
        self.assertEqual(feature_report_wire_lengths(descriptor), {0x10: 32})

    def test_global_push_pop(self):
        descriptor = bytes.fromhex("85 10 75 08 95 01 a4 75 01 95 08 b1 02 b4 b1 02")
        # 8 bits inside pushed globals + 8 bits after pop + Report ID.
        self.assertEqual(feature_report_wire_lengths(descriptor), {0x10: 3})

    def test_truncated_item_rejected(self):
        with self.assertRaises(HidDescriptorError):
            feature_report_wire_lengths(bytes.fromhex("76 01"))

    def test_input_report_03_length(self):
        descriptor = bytes.fromhex("85 03 75 08 95 02 81 02")
        self.assertEqual(input_report_wire_lengths(descriptor), {0x03: 3})

    def test_top_level_usages(self):
        descriptor = bytes.fromhex(
            "05 01 09 02 a1 01 09 01 a1 00 c0 c0 "
            "06 00 ff 09 10 a1 01 c0"
        )
        self.assertEqual(top_level_usages(descriptor), [(1, 2), (0xff00, 0x10)])


if __name__ == "__main__":
    unittest.main()
