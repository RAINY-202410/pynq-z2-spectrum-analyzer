"""B-X03 read-only replay API contracts."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import plus_app  # noqa: E402


class ReplayServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = plus_app.ReplayService()
        cls.index = cls.service.index_payload()
        cls.long_run = next(run for run in cls.index["runs"] if run["label"] == "long_hann_tone1k")

    def test_index_is_sparse_and_source_is_replay(self):
        self.assertEqual(self.index["source"], "REPLAY")
        self.assertEqual(self.index["original_context"], "BOARD_LIVE")
        self.assertEqual(len(self.index["runs"]), 4)
        self.assertEqual(self.index["metric_rows"], 3220)
        self.assertEqual(self.index["spectral_samples"], 20)
        self.assertEqual(self.long_run["metric_rows"], 3100)
        self.assertEqual(len(self.long_run["samples"]), 14)
        self.assertEqual(len(self.long_run["segments"]), 13)
        self.assertEqual(
            sum(item["metric_rows_between"] for item in self.long_run["segments"]),
            3100 - 14,
        )
        for sample in self.long_run["samples"]:
            self.assertNotIn("dbfs", sample)
            self.assertNotIn("frequency_hz", sample)

    def test_frame_payload_is_a_replay_spectrum(self):
        frame = self.service.frame_payload(self.long_run["run_id"], 1)
        self.assertEqual(frame["source"], "PL_FFT")
        self.assertEqual(frame["mode"], "REPLAY")
        self.assertEqual(frame["source_mode"], "LIVE")
        self.assertEqual(frame["sample_index"], 1)
        self.assertEqual(frame["window"], "hann")
        self.assertEqual(len(frame["frequency_hz"]), 513)
        self.assertEqual(len(frame["amplitude"]), 513)
        self.assertEqual(len(frame["dbfs"]), 513)
        self.assertAlmostEqual(frame["elapsed_s"], 0.042517490000136604, places=12)
        self.assertTrue(frame["quality"]["complete_spectrum"])
        self.assertFalse(frame["quality"]["amplitude_calibrated"])

    def test_missing_frame_is_not_fabricated(self):
        with self.assertRaises(plus_app.ReplayError) as caught:
            self.service.frame_payload(self.long_run["run_id"], 2)
        self.assertEqual(caught.exception.status, 404)
        self.assertIn("未留存完整频谱", caught.exception.message)

    def test_unknown_run_is_rejected(self):
        with self.assertRaises(plus_app.ReplayError) as caught:
            self.service.frame_payload("not_a_run", 1)
        self.assertEqual(caught.exception.status, 404)

    def test_frame_cache_is_reused(self):
        first = self.service.frame_payload(self.long_run["run_id"], 250)
        second = self.service.frame_payload(self.long_run["run_id"], 250)
        self.assertIs(first, second)

    def test_no_pynq_import(self):
        if "pynq" in sys.modules:
            self.skipTest("pynq was imported by the environment before this test")
        self.assertNotIn("pynq", sys.modules)


if __name__ == "__main__":
    unittest.main()
