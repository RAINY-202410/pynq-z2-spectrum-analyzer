"""B-X04 linear mean-square average and peak-hold checks."""

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import spectrum_features as sf  # noqa: E402


def frame(frame_id, amplitude, run_id="run_a", window="hann", fs_hz=48000.0,
          elapsed_s=None, mode="REPLAY"):
    return {
        "source": "PL_FFT",
        "mode": mode,
        "run_id": run_id,
        "frame_id": frame_id,
        "sequence": 1000 + frame_id,
        "elapsed_s": float(frame_id if elapsed_s is None else elapsed_s),
        "window_name": window,
        "fs_hz": fs_hz,
        "N": 1024,
        "amplitude": amplitude,
    }


def amp(bin1=0.0, bin2=0.0):
    values = np.zeros(513, dtype=float)
    values[1] = bin1
    values[2] = bin2
    return values


class SpectrumFeatureMathTest(unittest.TestCase):
    def test_small_array_manual_mean_square_and_hold(self):
        arrays = [np.array([0.0, 3.0, 4.0]), np.array([0.0, 4.0, 0.0])]
        average = sf.mean_square_spectrum(arrays)
        expected = np.array([0.0, np.sqrt((9.0 + 16.0) / 2.0), np.sqrt(16.0 / 2.0)])
        np.testing.assert_allclose(average, expected, rtol=0, atol=1e-15)
        np.testing.assert_array_equal(sf.peak_hold(arrays), np.array([0.0, 4.0, 4.0]))

    def test_zero_stays_zero_and_epsilon_is_display_only(self):
        zero = np.zeros(513)
        self.assertTrue(np.all(sf.mean_square_spectrum([zero, zero]) == 0))
        self.assertTrue(np.all(sf.to_dbfs(zero) == 20.0 * np.log10(sf.EPSILON)))

    def test_average_counts_actual_frames_and_hold_covers_all_observed(self):
        acc = sf.SpectrumAccumulator(average_length=2)
        acc.add(frame(1, amp(3.0, 4.0)))
        acc.add(frame(2, amp(4.0, 0.0)))
        snapshot = acc.add(frame(3, amp(0.0, 0.0)))
        self.assertEqual(snapshot["average"]["count"], 2)
        self.assertEqual(snapshot["hold"]["count"], 3)
        self.assertEqual(snapshot["total_observed"], 3)
        self.assertAlmostEqual(float(snapshot["average"]["linear"][1]), np.sqrt(8.0), places=15)
        self.assertAlmostEqual(float(snapshot["average"]["linear"][2]), 0.0, places=15)
        self.assertAlmostEqual(float(snapshot["hold"]["linear"][1]), 4.0, places=15)
        self.assertAlmostEqual(float(snapshot["hold"]["linear"][2]), 4.0, places=15)

    def test_duplicate_frame_is_ignored(self):
        acc = sf.SpectrumAccumulator(average_length=2)
        acc.add(frame(1, amp(1.0, 0.0)))
        acc.add(frame(2, amp(2.0, 0.0)))
        before = acc.snapshot()
        after = acc.add(frame(2, amp(2.0, 0.0)))
        self.assertTrue(after["duplicate_ignored"])
        self.assertEqual(after["total_observed"], before["total_observed"])
        self.assertEqual(after["hold"]["count"], before["hold"]["count"])
        self.assertEqual(after["average"]["count"], before["average"]["count"])

    def test_average_length_change_does_not_reset_hold(self):
        acc = sf.SpectrumAccumulator(average_length=1)
        for frame_id, value in ((1, 1.0), (2, 2.0), (3, 3.0)):
            acc.add(frame(frame_id, amp(value, 0.0)))
        changed = acc.set_average_length(3)
        self.assertEqual(changed["average_length"], 3)
        self.assertEqual(changed["average"]["count"], 3)
        self.assertEqual(changed["hold"]["count"], 3)
        self.assertAlmostEqual(float(changed["hold"]["linear"][1]), 3.0, places=15)

    def test_group_change_resets(self):
        acc = sf.SpectrumAccumulator(average_length=2)
        acc.add(frame(1, amp(1.0, 0.0), run_id="run_a"))
        changed = acc.add(frame(1, amp(2.0, 0.0), run_id="run_b"))
        self.assertEqual(changed["reset_reason"], "group_changed")
        self.assertEqual(changed["total_observed"], 1)
        self.assertEqual(changed["hold"]["count"], 1)
        self.assertEqual(changed["group"]["run_id"], "run_b")

    def test_window_change_resets(self):
        acc = sf.SpectrumAccumulator(average_length=2)
        acc.add(frame(1, amp(1.0, 0.0), window="hann"))
        changed = acc.add(frame(2, amp(2.0, 0.0), window="rect"))
        self.assertEqual(changed["reset_reason"], "group_changed")
        self.assertEqual(changed["group"]["window"], "rect")
        self.assertEqual(changed["total_observed"], 1)

    def test_clear_resets_both_curves(self):
        acc = sf.SpectrumAccumulator(average_length=2)
        acc.add(frame(1, amp(1.0, 0.0)))
        cleared = acc.clear()
        self.assertIsNone(cleared["current"])
        self.assertIsNone(cleared["average"])
        self.assertIsNone(cleared["hold"])
        self.assertEqual(cleared["total_observed"], 0)
        self.assertEqual(cleared["last_reset_reason"], "manual_clear")

    def test_history_is_bounded_but_hold_count_continues(self):
        acc = sf.SpectrumAccumulator(average_length=32, max_history=32)
        for frame_id in range(1, 41):
            acc.add(frame(frame_id, amp(float(frame_id), 0.0)))
        snapshot = acc.snapshot()
        self.assertEqual(snapshot["stored_frames"], 32)
        self.assertEqual(snapshot["average"]["count"], 32)
        self.assertEqual(snapshot["hold"]["count"], 40)
        self.assertAlmostEqual(float(snapshot["hold"]["linear"][1]), 40.0, places=15)

    def test_zero_bins_remain_explicit(self):
        snapshot = sf.accumulate([frame(1, amp(0.0, 0.0))], average_length=8)
        self.assertEqual(snapshot["zero_bins"]["current"], 513)
        self.assertEqual(snapshot["zero_bins"]["average"], 513)
        self.assertEqual(snapshot["zero_bins"]["hold"], 513)
        self.assertFalse(snapshot["method"]["complex_fft_averaging"])
        self.assertFalse(snapshot["method"]["dbfs_averaging"])


if __name__ == "__main__":
    unittest.main()
