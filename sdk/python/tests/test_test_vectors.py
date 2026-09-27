import json
import tempfile
import unittest
from pathlib import Path

from threedx_report10.test_vectors import export_vectors, main


VECTORS = Path(__file__).resolve().parents[1] / "vectors"


class TestVectorTests(unittest.TestCase):
    def test_fixed_input_matches_published_output(self):
        source = json.loads((VECTORS / "input.json").read_text(encoding="utf-8"))
        expected = (VECTORS / "output.json").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "vectors.json"
            self.assertEqual(main(["--input", str(VECTORS / "input.json"), "--output", str(output)]), 0)
            self.assertEqual(output.read_text(encoding="utf-8"), expected)

        result = export_vectors(source)
        self.assertEqual(result["wire"][0]["wire_hex"].split()[19], "29")
        self.assertEqual(result["wire"][0]["parsed"]["buttons"][0]["name"], "HOST_ROUTED_INDEX_1")
        self.assertEqual(result["descriptors"][0]["feature_wire_lengths"], {"0x10": 32})
        self.assertEqual(result["descriptors"][0]["input_wire_lengths"], {"0x03": 3})
        self.assertEqual(result["descriptors"][0]["top_level_usages"],
                         [{"page": "0x0001", "usage": "0x0002"}])
        self.assertEqual([(item["pressed_mask"], item["released_mask"])
                          for item in result["report03"]], [(1, 0), (0, 1)])
        self.assertEqual([item["packet_hex"] for item in result["receiver"]], [
            "41 02 02 00 00", "41 02 00 00 00", "41 04 02 00 00"])
        self.assertNotIn("serial", expected.lower())
        self.assertNotIn("/home/", expected)
        self.assertNotIn("/dev/", expected)


if __name__ == "__main__":
    unittest.main()
