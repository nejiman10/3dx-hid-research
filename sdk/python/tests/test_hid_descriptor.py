import unittest

from threedx_report10 import (
    HidDescriptorError,
    feature_report_wire_lengths,
    input_report_wire_lengths,
)


class HidDescriptorTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
