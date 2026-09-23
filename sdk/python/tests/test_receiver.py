import unittest

from threedx_report10 import (
    PAIR_START,
    PAIR_STOP,
    ReceiverSlot,
    build_unpair_packet,
    newly_occupied_slots,
)


def slot(number, device_type):
    report_id = 0x43 + number
    raw = bytes((report_id, device_type, 1, 2, 3, 4, 5, 6))
    return ReceiverSlot(number, report_id, device_type, raw[2:], raw)


class ReceiverTests(unittest.TestCase):
    def test_pairing_packets(self):
        self.assertEqual(PAIR_START, bytes.fromhex("41 02 02 00 00"))
        self.assertEqual(PAIR_STOP, bytes.fromhex("41 02 00 00 00"))

    def test_unpair_packet_requires_explicit_valid_slot(self):
        self.assertEqual(build_unpair_packet(3), bytes.fromhex("41 04 03 00 00"))
        with self.assertRaises(ValueError):
            build_unpair_packet(5)

    def test_newly_occupied_slot(self):
        before = [slot(index, 0) for index in range(5)]
        after = [slot(index, 0x59 if index == 2 else 0) for index in range(5)]
        found = newly_occupied_slots(before, after)
        self.assertEqual([item.slot for item in found], [2])
        self.assertEqual(found[0].device_type, 0x59)


if __name__ == "__main__":
    unittest.main()
