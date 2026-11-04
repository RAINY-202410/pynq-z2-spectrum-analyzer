"""B-X09 RC theory and SYNTHETIC fixture checks."""

import csv
import json
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rc import rc_model  # noqa: E402


class RCModelTest(unittest.TestCase):
    def test_cutoff_and_transfer(self):
        fc = rc_model.cutoff_hz()
        self.assertAlmostEqual(fc, 1591.5494309189535, places=9)
        self.assertAlmostEqual(float(rc_model.gain_db(fc)), -3.010299956639812, places=10)
        self.assertAlmostEqual(float(rc_model.phase_deg(fc)), -45.0, places=10)

    def test_measured_table_is_blank(self):
        points = [rc_model.measured_point_template(f) for f in rc_model.DESIGN_FREQUENCIES_HZ]
        self.assertEqual(len(points), 16)
        self.assertEqual(points[0]["target_hz"], 200.0)
        self.assertEqual(points[-1]["target_hz"], 8000.0)
        for point in points:
            self.assertEqual(point["quality_status"], "NOT_MEASURED")
            for field in ("estimated_actual_hz", "fs_hz", "frame_id", "raw_file",
                          "channel_assignment", "straight_through_calibration",
                          "complex_transfer_ratio", "gain_db", "phase_deg",
                          "actual_r_ohm", "actual_c_f"):
                self.assertIsNone(point[field])

    def test_generated_real_theory_file_and_synthetic_cases(self):
        out = ROOT / "reports" / "B-X09"
        payload = json.loads((out / "rc_points.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["experiment"]["fc_hz"], rc_model.cutoff_hz())
        self.assertEqual(payload["experiment"]["measured_source"], "NONE_IN_B_X09")
        self.assertEqual(len(payload["rc_points"]), 16)
        self.assertEqual(len(payload["synthetic_points"]), 4)
        self.assertTrue(all(item["source"] == "DESIGN_ONLY" for item in payload["rc_points"]))
        self.assertTrue(all(item["source"] == "SYNTHETIC" for item in payload["synthetic_points"]))
        self.assertTrue(all(item["gain_db"] is None for item in payload["rc_points"]))
        for point in payload["synthetic_points"]:
            raw = out / point["raw_file"]
            self.assertTrue(raw.is_file())
            archive = np.load(raw, allow_pickle=False)
            self.assertEqual(archive["samples_int32"].shape, (2, 1024))
            self.assertEqual(archive["samples_int32"].dtype, np.int32)
            self.assertEqual(archive["samples_float"].shape, (2, 1024))
            self.assertEqual(str(archive["source"]), "SYNTHETIC")
            self.assertAlmostEqual(float(archive["actual_frequency_hz"]),
                                   point["estimated_actual_hz"], places=9)
            self.assertAlmostEqual(float(archive["truth_phase_deg"]),
                                   point["truth_complex_transfer_ratio"]["phase_deg"], places=9)

    def test_measured_and_synthetic_csv_are_separate(self):
        out = ROOT / "reports" / "B-X09"
        with (out / "rc_points.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 16)
        self.assertTrue(all(row["gain_db"] == "" and row["phase_deg"] == "" for row in rows))
        with (out / "synthetic_points.csv").open(encoding="utf-8", newline="") as handle:
            synthetic = list(csv.DictReader(handle))
        self.assertEqual(len(synthetic), 4)
        self.assertTrue(all(row["source"] == "SYNTHETIC" for row in synthetic))

    def test_manifest_hashes(self):
        out = ROOT / "reports" / "B-X09"
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["step"], "B-X09")
        for name, info in manifest["files"].items():
            import hashlib
            actual = hashlib.sha256((out / name).read_bytes()).hexdigest().upper()
            self.assertEqual(actual, info["sha256"], name)


if __name__ == "__main__":
    unittest.main()
