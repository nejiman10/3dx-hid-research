import tempfile
import unittest
from pathlib import Path

from threedx_report10.input_events import _input_event_nodes_from_device_root


class InputEventDiscoveryTests(unittest.TestCase):
    def test_direct_hid_sysfs_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event = root / "input" / "input42" / "event17"
            event.mkdir(parents=True)
            self.assertEqual(
                _input_event_nodes_from_device_root(root),
                [Path("/dev/input/event17")],
            )

    def test_one_child_receiver_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event = root / "child" / "input" / "input9" / "event8"
            event.mkdir(parents=True)
            self.assertEqual(
                _input_event_nodes_from_device_root(root),
                [Path("/dev/input/event8")],
            )

    def test_symlink_graph_is_not_recursively_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "loop").symlink_to(root, target_is_directory=True)
            self.assertEqual(_input_event_nodes_from_device_root(root), [])


if __name__ == "__main__":
    unittest.main()
