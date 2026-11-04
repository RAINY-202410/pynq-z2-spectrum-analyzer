"""B-X01 must parse archived data without importing or touching PYNQ."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PYNQ = ROOT / "baseline_readonly" / "host_tools" / "sw" / "pynq"
REPLAY = BASELINE_PYNQ / "replay_examples"


class OfflineIsolationTest(unittest.TestCase):
    def setUp(self):
        self.pynq_was_imported = "pynq" in sys.modules

    def tearDown(self):
        if not self.pynq_was_imported:
            self.assertNotIn("pynq", sys.modules)

    def test_extension_entry_points_do_not_import_pynq(self):
        sys.path.insert(0, str(ROOT))
        import export_results
        import plus_app
        import session_reader
        import spectrum_features
        import timeline_features

        self.assertFalse(hasattr(plus_app, "Overlay"))
        self.assertFalse(hasattr(plus_app, "FFTCapture"))
        self.assertEqual(export_results.reports_root(), (ROOT / "reports").resolve())
        self.assertEqual(session_reader.STEP, "B-X02")
        self.assertEqual(spectrum_features.STEP, "B-X04")
        self.assertEqual(timeline_features.STEP, "B-X06")

    def test_real_replay_frame_parses_without_pynq(self):
        sys.path.insert(0, str(BASELINE_PYNQ))
        import fft_session

        frame = fft_session.load_frame(
            REPLAY / "tone1k_hann_words.npy",
            REPLAY / "tone1k_hann_state.json",
        )
        self.assertEqual(frame["source"], "PL_FFT")
        self.assertEqual(frame["mode"], "REPLAY")
        self.assertEqual(frame["N"], 1024)
        self.assertEqual(len(frame["amplitude"]), 513)
        self.assertEqual(len(frame["frequency_hz"]), 513)

    def test_corrupt_replay_hash_is_rejected(self):
        sys.path.insert(0, str(BASELINE_PYNQ))
        import fft_session

        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            words = temp / "tone1k_hann_words.npy"
            state = temp / "tone1k_hann_state.json"
            shutil.copy2(REPLAY / "tone1k_hann_words.npy", words)
            shutil.copy2(REPLAY / "tone1k_hann_state.json", state)
            blob = bytearray(words.read_bytes())
            blob[-1] ^= 0x01
            words.write_bytes(bytes(blob))
            with self.assertRaises(ValueError):
                fft_session.load_frame(words, state)

    def test_check_mode_reports_offline(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "plus_app.py"), "--check"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        status = json.loads(completed.stdout)
        self.assertEqual(status["status"], "OFFLINE_READY")
        self.assertFalse(status["hardware_access"])
        self.assertFalse(status["pynq_imported"])
        self.assertEqual(status["replay_examples"], 7)
        self.assertTrue(status["b_x03"]["ready"])
        self.assertEqual(status["b_x03"]["runs"], 4)
        self.assertEqual(status["b_x03"]["metric_rows"], 3220)
        self.assertEqual(status["b_x03"]["spectral_samples"], 20)
        self.assertTrue(status["b_x04"]["ready"])
        self.assertEqual(status["b_x04"]["average_lengths"], [8, 32])
        self.assertTrue(status["b_x05"]["ready"])
        self.assertEqual(status["b_x05"]["cursors"], ["A", "B"])
        self.assertTrue(status["b_x06"]["ready"])
        self.assertTrue(status["b_x07"]["ready"])
        self.assertTrue(status["b_x08"]["ready"])
        self.assertTrue(status["b_x09"]["ready"])
        self.assertTrue(status["b_x10"]["ready"])
        self.assertTrue(status["b_x11"]["ready"])
        self.assertTrue(status["b_x12"]["ready"])
        self.assertEqual(status["b_x12"]["measured_points"], 16)
        self.assertEqual(status["b_x12"]["passed_points"], 16)
        self.assertEqual(status["b_x12"]["status"], "RC_MEASURED")


if __name__ == "__main__":
    unittest.main()
