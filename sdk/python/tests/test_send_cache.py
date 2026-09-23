import unittest

from threedx_report10 import (
    ButtonMapping,
    DirectAction,
    Report10Config,
    Report10SendCache,
)


class SendCacheTests(unittest.TestCase):
    def test_success_suppression_and_failure_clear(self):
        baseline = Report10Config.latest_software_baseline()
        calls = []

        def success(report):
            calls.append(report)
            return 0

        cache = Report10SendCache()
        first = cache.send(baseline, success)
        second = cache.send(baseline, success)
        self.assertEqual(first.disposition, "sent-and-cached")
        self.assertEqual(second.disposition, "suppressed-identical")
        self.assertEqual(len(calls), 1)

        def fail(_report):
            raise OSError("injected")

        changed_buttons = list(baseline.buttons)
        changed_buttons[0] = ButtonMapping.direct(DirectAction.HID_MOUSE_RIGHT)
        changed = Report10Config.create(
            dpi=baseline.dpi,
            lift_detection=baseline.lift_detection,
            wheel_mode=baseline.wheel_mode,
            buttons=changed_buttons,
            polling_rate=baseline.polling_rate,
        )
        with self.assertRaises(OSError):
            cache.send(changed, fail)
        self.assertIsNone(cache.last_successful_blob)
        resent = cache.send(baseline, success)
        self.assertEqual(resent.disposition, "sent-and-cached")
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()

