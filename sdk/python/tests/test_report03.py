import unittest

from threedx_report10 import REPORT03_MASKS, Report03Error, parse_report03


class Report03Tests(unittest.TestCase):
    def test_little_endian_bitmap_press_and_release(self):
        pressed = parse_report03(bytes.fromhex("03 40 00"), 0)
        self.assertEqual(pressed.bitmap, 0x40)
        self.assertEqual(pressed.pressed_mask, REPORT03_MASKS[6])
        self.assertTrue(pressed.host_index_pressed(7))
        self.assertEqual(pressed.released_mask, 0)
        released = parse_report03(bytes.fromhex("03 00 00"), pressed.bitmap)
        self.assertEqual(released.released_mask, REPORT03_MASKS[6])
        self.assertTrue(released.host_index_released(7))

    def test_multiple_buttons_and_high_bits_are_masked(self):
        frame = parse_report03(bytes.fromhex("03 85 ff"), 0)
        self.assertEqual(frame.bitmap, 0x05)
        self.assertEqual(frame.pressed_mask, 0x05)

    def test_wrong_report_rejected(self):
        with self.assertRaises(Report03Error):
            parse_report03(bytes.fromhex("04 01"))


if __name__ == "__main__":
    unittest.main()
