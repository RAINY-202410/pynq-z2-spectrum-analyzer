"""B-X05 actual-bin dual-cursor checks."""

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cursor_features as cf  # noqa: E402
import session_reader  # noqa: E402


class CursorFeaturesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        index_path = ROOT / "reports" / "B-X02" / "sample_index.json"
        import json
        index = json.loads(index_path.read_text(encoding="utf-8"))
        sample = next(item for item in index["spectral_samples"]
                      if item["run_id"] == "spectrum_38749b56cab6" and item["frame_id"] == 1)
        cls.frame = session_reader.load_spectral_sample(sample)

    def test_real_dual_tone_bins_and_readings_match_arrays(self):
        frequency = np.asarray(self.frame["frequency_hz"], dtype=float)
        linear = np.asarray(self.frame["amplitude"], dtype=float)
        a_bin = cf.nearest_bin(frequency, 1000)
        b_bin = cf.nearest_bin(frequency, 3000)
        self.assertEqual(a_bin, 21)
        self.assertEqual(b_bin, 64)
        a = cf.cursor_reading(frequency, linear, a_bin, "当前谱")
        b = cf.cursor_reading(frequency, linear, b_bin, "当前谱")
        self.assertEqual(a["bin"], 21)
        self.assertEqual(b["bin"], 64)
        self.assertAlmostEqual(a["frequency_hz"], float(frequency[21]), places=12)
        self.assertAlmostEqual(b["linear"], float(linear[64]), places=15)
        delta = cf.dual_cursor_delta(a, b)
        self.assertAlmostEqual(delta["delta_f_hz"], frequency[64] - frequency[21], places=12)
        self.assertTrue(delta["ratio_applicable"])
        self.assertAlmostEqual(delta["ratio"], linear[64] / linear[21], places=15)

    def test_zero_amplitude_ratio_is_not_applicable(self):
        frequency = np.array([0.0, 1000.0, 3000.0])
        linear = np.array([0.0, 0.0, 1.0])
        a = cf.cursor_reading(frequency, linear, 1, "当前谱")
        b = cf.cursor_reading(frequency, linear, 2, "当前谱")
        delta = cf.dual_cursor_delta(a, b)
        self.assertIsNone(delta["ratio"])
        self.assertFalse(delta["ratio_applicable"])

    def test_different_curves_do_not_produce_ratio(self):
        frequency = np.array([0.0, 1000.0])
        linear = np.array([0.0, 2.0])
        a = cf.cursor_reading(frequency, linear, 1, "当前谱")
        b = cf.cursor_reading(frequency, linear, 1, "峰值保持")
        delta = cf.dual_cursor_delta(a, b)
        self.assertFalse(delta["same_curve"])
        self.assertIsNone(delta["ratio"])
        self.assertEqual(delta["delta_f_hz"], 0.0)

    def test_invalid_bin_is_rejected(self):
        with self.assertRaises(cf.CursorError):
            cf.cursor_reading([0.0, 1000.0], [0.0, 1.0], 2, "当前谱")


if __name__ == "__main__":
    unittest.main()
