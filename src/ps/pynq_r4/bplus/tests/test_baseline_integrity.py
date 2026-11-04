"""B-X01 source and baseline integrity checks."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import verify_baseline  # noqa: E402


class BaselineIntegrityTest(unittest.TestCase):
    def test_original_package_and_copy_hashes(self):
        result = verify_baseline.verify(require_source=True)
        self.assertTrue(result["ok"], result["failures"])
        self.assertTrue(result["source"]["outer_package_checked"])
        self.assertTrue(result["source"]["r3_archive_checked"])
        self.assertFalse(result["hardware_access"])
        self.assertGreaterEqual(result["counts"]["baseline_files"], 40)
        self.assertEqual(result["counts"]["input_files"], 5)


if __name__ == "__main__":
    unittest.main()
