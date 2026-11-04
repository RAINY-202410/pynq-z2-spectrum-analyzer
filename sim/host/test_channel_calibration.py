"""B-X11 pilot channel-calibration checks."""

import json
import sys
import unittest
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rc import channel_calibration as cc  # noqa: E402


class ChannelCalibrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = ROOT / "reports" / "B-X11"
        cls.payload = json.loads((cls.out / "channel_calibration.json").read_text(encoding="utf-8"))

    def test_real_m4_pilot_is_split_and_corrected(self):
        point = self.payload["calibration_point"]
        self.assertEqual(self.payload["status"], "HOST_VALIDATED_BOARD_PENDING")
        self.assertEqual(self.payload["scope"], "EXISTING_M4_1KHZ_VALIDATION_PILOT")
        self.assertEqual(point["status"], "PILOT_PASS")
        self.assertEqual(len(point["calibration_blocks"]), 5)
        self.assertEqual(len(point["validation_blocks"]), 5)
        self.assertTrue(point["independent_validation"]["passed"])
        self.assertAlmostEqual(point["C0"]["gain_db"], 0.0642542044108732, places=6)
        self.assertAlmostEqual(point["C0"]["phase_deg"], -0.00776305631303152, places=6)
        self.assertLess(abs(point["independent_validation"]["mean_gain_db"]), 0.01)
        self.assertLess(abs(point["independent_validation"]["mean_phase_deg"]), 0.01)

    def test_all_design_points_except_pilot_are_blank(self):
        points = self.payload["design_points"]
        self.assertEqual(len(points), 16)
        pilot = [item for item in points if item["status"] == "PILOT_M4_1KHZ"]
        self.assertEqual(len(pilot), 1)
        self.assertEqual(pilot[0]["target_hz"], 1000.0)
        self.assertEqual(sum(1 for item in points if item["status"] == "NOT_MEASURED"), 15)
        self.assertTrue(all(item["pilot_point"] is None for item in points
                            if item["target_hz"] != 1000.0))

    def test_raw_pilot_blocks_and_manifest(self):
        raw_files = self.payload["raw_files"]
        self.assertEqual(len(raw_files), 10)
        for item in raw_files:
            path = self.out / item["file"]
            array = np.load(path, allow_pickle=False)
            self.assertEqual(array.shape, (2, 1024))
            self.assertEqual(array.dtype, np.int32)
        manifest = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("raw_pilot/cap_01.npy", manifest["files"])
        self.assertEqual(manifest["status"], "BOARD_VALIDATED")

    def test_generated_bx11_audio_sources(self):
        audio_dir = self.out / "audio_sources"
        files = sorted(audio_dir.glob("b11_*Hz.wav"))
        self.assertEqual(len(files), 16)
        for path in files:
            with wave.open(str(path), "rb") as wav:
                self.assertEqual(wav.getframerate(), 48000)
                self.assertEqual(wav.getnchannels(), 2)
                self.assertEqual(wav.getsampwidth(), 2)
                self.assertEqual(wav.getnframes(), 576000)
                frames = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
            stereo = frames.reshape(-1, 2)
            self.assertTrue(np.array_equal(stereo[:, 0], stereo[:, 1]))
            self.assertLessEqual(int(np.max(np.abs(stereo))), 3277)

    def test_full_16_point_board_dataset(self):
        full = self.out / "full_20261101"
        payload = json.loads((full / "channel_calibration.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "BOARD_VALIDATED")
        self.assertEqual(payload["point_count"], 16)
        self.assertEqual(payload["pass_count"], 16)
        self.assertTrue(payload["conditions_complete"])
        self.assertEqual(payload["conditions"]["volume"], "100%")
        self.assertEqual(payload["conditions"]["temperature"], "25 C")
        self.assertIn("Direct stereo cable", payload["conditions"]["line_topology_note"])
        self.assertEqual(len(payload["rejected_blocks"]), 1)
        six_k = next(item for item in payload["points"] if item["target_hz"] == 6000.0)
        self.assertIn("b11_f6000_val_retry_01.npy",
                      six_k["selected_validation_files"])
        self.assertEqual(six_k["rejected_validation_files"], ["b11_f6000_val_03.npy"])
        self.assertTrue(six_k["independent_validation"]["passed"])
        manifest = json.loads((full / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["pass_count"], 16)
        self.assertIn("README.md", manifest["files"])

    def test_signal_generator_dataset_excludes_retry(self):
        report = self.out / "signal_generator_20261101"
        payload = json.loads(
            (report / "channel_calibration.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "BOARD_VALIDATED")
        self.assertEqual(payload["source_profile"], "SIGNAL_GENERATOR")
        self.assertEqual(payload["point_count"], 16)
        self.assertEqual(payload["pass_count"], 16)
        self.assertTrue(payload["conditions_complete"])
        self.assertTrue(payload["all_points_passed"])
        self.assertEqual(payload["rejected_blocks"], [])
        six_k = next(
            item for item in payload["points"] if item["target_hz"] == 6000.0)
        self.assertEqual(
            six_k["selected_validation_files"],
            [
                "b11_f6000_val_01.npy",
                "b11_f6000_val_02.npy",
                "b11_f6000_val_03.npy",
            ],
        )
        self.assertEqual(six_k["rejected_validation_files"], [])
        self.assertEqual(payload["unknown_conditions"], [])
        self.assertEqual(payload["conditions"]["generator_model"], "OWON_XDG3122")
        self.assertEqual(
            payload["conditions"]["generator_amplitude_vpp"], "0.2_VPP_ACTUAL")
        self.assertEqual(payload["conditions"]["temperature"], "26_C")
        source = json.loads(
            (report / "source_dataset_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(source["excluded_files"], ["b11_f6000_val_retry_01.npy"])
        self.assertEqual(
            sum(item["role"] == "analysis_block" for item in source["files"]), 96)
        manifest = json.loads((report / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["ignore_retry"])
        self.assertEqual(manifest["point_count"], 16)
        self.assertEqual(manifest["pass_count"], 16)
        self.assertIn("source_dataset_manifest.json", manifest["files"])
        self.assertIn("README.md", manifest["files"])

    def test_overlapping_calibration_validation_is_rejected(self):
        raw = self.out / "raw_pilot" / "cap_01.npy"
        with self.assertRaises(cc.CalibrationError):
            cc.calibrate_point([raw, raw, raw], [raw, raw, raw], 47998.2293823345)

    def test_no_pynq_import(self):
        if "pynq" in sys.modules:
            self.skipTest("pynq was imported by the environment before this test")
        self.assertNotIn("pynq", sys.modules)


if __name__ == "__main__":
    unittest.main()
