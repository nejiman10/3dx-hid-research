import unittest
from pathlib import Path

from threedx_report10.hold_open import WiredC658HoldOpen
from threedx_report10.linux_hidraw import C652_PID, C658_PID, C658_VID, HidrawInfo


def info(path, product=C658_PID):
    return HidrawInfo(Path(path), 3, C658_VID, product, {}, {})


class HoldOpenTests(unittest.TestCase):
    def test_holds_all_wired_interfaces_and_ignores_receiver(self):
        opened = []
        closed = []

        def opener(path, flags):
            opened.append((path, flags))
            return len(opened) + 10

        keeper = WiredC658HoldOpen(opener=opener, closer=closed.append)
        events = keeper.reconcile(
            [info("/dev/hidraw15"), info("/dev/hidraw14"), info("/dev/hidraw5", C652_PID)]
        )
        self.assertEqual(keeper.held_paths, (Path("/dev/hidraw14"), Path("/dev/hidraw15")))
        self.assertEqual([event["event"] for event in events], ["held", "held"])
        self.assertEqual(closed, [])

    def test_reconcile_releases_removed_and_opens_reconnected_path(self):
        next_fd = iter((20, 21))
        closed = []
        keeper = WiredC658HoldOpen(
            opener=lambda _path, _flags: next(next_fd), closer=closed.append
        )
        keeper.reconcile([info("/dev/hidraw14")])
        events = keeper.reconcile([info("/dev/hidraw18")])
        self.assertEqual(closed, [20])
        self.assertEqual(keeper.held_paths, (Path("/dev/hidraw18"),))
        self.assertEqual([event["event"] for event in events], ["released", "held"])

    def test_open_failure_is_retried_on_next_reconcile(self):
        attempts = []

        def opener(path, _flags):
            attempts.append(path)
            if len(attempts) == 1:
                raise PermissionError("denied")
            return 30

        keeper = WiredC658HoldOpen(opener=opener)
        first = keeper.reconcile([info("/dev/hidraw14")])
        second = keeper.reconcile([info("/dev/hidraw14")])
        self.assertEqual(first[0]["event"], "open-error")
        self.assertEqual(second[0]["event"], "held")


if __name__ == "__main__":
    unittest.main()
