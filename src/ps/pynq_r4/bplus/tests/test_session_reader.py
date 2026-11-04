"""B-X02 archive indexing and frozen-parser checks."""

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import session_reader  # noqa: E402


class SessionReaderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.temp.name) / "B-X02"
        cls.index = session_reader.write_index(session_reader.DEFAULT_SESSION, cls.out)
        cls.timeline = session_reader.load_metric_timeline(cls.out / "metric_timeline.jsonl")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_selected_runs_and_counts(self):
        self.assertEqual(len(self.index["runs"]), 4)
        self.assertEqual(len(self.index["spectral_samples"]), 20)
        self.assertEqual(len(self.timeline), 3220)
        self.assertEqual(self.index["verification"]["metric_rows"], 3220)
        self.assertEqual(self.index["verification"]["spectral_samples"], 20)
        self.assertEqual(self.index["verification"]["saved_fft_matches_parser"], 20)
        self.assertEqual(self.index["verification"]["warnings"], [])
        self.assertTrue(self.index["verification"]["no_cpu_fft_reexecution"])

    def test_run_groups_remain_separate(self):
        by_label = {run["label"]: run for run in self.index["runs"]}
        self.assertEqual(by_label["long_hann_tone1k"]["metric_rows"], 3100)
        self.assertEqual(by_label["long_hann_tone1k"]["saved_samples"], 14)
        self.assertEqual(by_label["long_hann_tone1k"]["window"], "hann")
        self.assertEqual(by_label["dual_rect"]["window"], "rect")
        self.assertEqual(by_label["dual_rect"]["saved_samples"], 2)
        self.assertEqual(by_label["dual_hann"]["window"], "hann")
        self.assertEqual(by_label["analog_silence"]["expected_tones_hz"], [])
        self.assertEqual(by_label["analog_silence"]["first_sequence"], 3503)

    def test_spectral_sample_loader_reuses_saved_pl_result(self):
        sample = self.index["spectral_samples"][0]
        frame = session_reader.load_spectral_sample(sample)
        self.assertEqual(frame["source"], "PL_FFT")
        self.assertEqual(frame["mode"], "REPLAY")
        self.assertEqual(frame["N"], 1024)
        self.assertEqual(frame["sequence"], sample["sequence"])
        self.assertEqual(sample["mode"], "LIVE")
        self.assertEqual(len(frame["amplitude"]), 513)
        self.assertEqual(len(frame["frequency_hz"]), 513)
        self.assertFalse(sample["reexecutes_fft"])

    def test_bad_words_hash_is_rejected(self):
        sample = copy.deepcopy(self.index["spectral_samples"][0])
        sample["words_sha256"] = "0" * 64
        with self.assertRaises(session_reader.SessionDataError):
            session_reader.load_spectral_sample(sample)

    def test_missing_member_is_rejected(self):
        sample = copy.deepcopy(self.index["spectral_samples"][0])
        sample["words_member"] = "spectrum_569e5f254203/does_not_exist_words.npy"
        with self.assertRaises(session_reader.SessionDataError) as caught:
            session_reader.load_spectral_sample(sample)
        self.assertIn("missing ZIP member", str(caught.exception))

    def test_metric_timeline_preserves_source_identity(self):
        first = self.timeline[0]
        self.assertEqual(first["record_type"], "metric")
        self.assertEqual(first["frame_id"], 1)
        self.assertEqual(first["source_mode"], "LIVE")
        self.assertEqual(first["mode"], "LIVE")
        self.assertEqual(first["index_mode"], "OFFLINE_INDEX")
        for key in ("run_id", "sequence", "elapsed_s", "window", "fs_hz", "N",
                    "source_member", "source_sha256", "line_number", "line_sha256",
                    "metrics"):
            self.assertIn(key, first)
        self.assertEqual(self.timeline[1]["sequence"], self.timeline[0]["sequence"] + 1)

    def test_output_manifest_hashes(self):
        manifest = json.loads((self.out / "index_manifest.json").read_text(encoding="utf-8"))
        for name, expected in manifest["outputs"].items():
            actual = hashlib.sha256((self.out / name).read_bytes()).hexdigest().upper()
            self.assertEqual(actual, expected["sha256"])
        sample_index = json.loads((self.out / "sample_index.json").read_text(encoding="utf-8"))
        self.assertEqual(
            sample_index["metric_timeline"]["sha256"],
            manifest["outputs"]["metric_timeline.jsonl"]["sha256"],
        )

    def test_no_pynq_import(self):
        if "pynq" in sys.modules:
            self.skipTest("pynq was imported by the environment before this test")
        self.assertNotIn("pynq", sys.modules)


if __name__ == "__main__":
    unittest.main()
