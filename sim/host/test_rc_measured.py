"""B-X12 measured RC report checks."""

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rc import rc_model  # noqa: E402


class RCMeasuredTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = ROOT / "reports" / "B-X12" / "measured_20261101"
        cls.payload = json.loads(
            (cls.out / "rc_measured.json").read_text(encoding="utf-8"))

    def test_all_design_points_are_measured(self):
        self.assertEqual(self.payload["step"], "B-X12")
        self.assertEqual(self.payload["status"], "RC_MEASURED")
        self.assertEqual(self.payload["design_point_count"], 16)
        self.assertEqual(self.payload["measured_point_count"], 16)
        self.assertEqual(self.payload["pass_count"], 16)
        self.assertEqual(self.payload["missing_frequencies_hz"], [])
        self.assertTrue(all(
            point["status"] == "RC_PASS" for point in self.payload["points"]))

    def test_conditions_and_real_rc_values(self):
        conditions = self.payload["conditions"]
        self.assertEqual(conditions["generator_model"], "OWON_XDG3122")
        self.assertEqual(conditions["temperature"], "25_C")
        self.assertEqual(conditions["actual_r_ohm"], 978.0)
        self.assertAlmostEqual(conditions["actual_c_f"], 105.6e-9, places=15)
        self.assertIn("L(input_reference)", conditions["wiring"])
        self.assertIn("R(rc_output)", conditions["wiring"])
        self.assertIn("common_GND", conditions["wiring"])
        self.assertEqual(
            conditions["channel_assignment"],
            {"left": "input_reference", "right": "rc_output"})

    def test_c0_and_theory_are_separate(self):
        for point in self.payload["points"]:
            self.assertIsNotNone(point["C0"])
            self.assertIsNotNone(point["H_raw_cal_mean"])
            self.assertIsNotNone(point["H_cal_calibration_mean"])
            self.assertIsNotNone(point["H_cal_validation_mean"])
            expected_theory = complex(
                rc_model.transfer(point["target_hz"], 978.0, 105.6e-9))
            self.assertAlmostEqual(
                point["theory"]["real"], expected_theory.real, places=12)
            self.assertAlmostEqual(
                point["theory"]["imag"], expected_theory.imag, places=12)

    def test_one_pole_fit_and_cutoff(self):
        theory = rc_model.cutoff_hz(978.0, 105.6e-9)
        self.assertAlmostEqual(
            self.payload["theory_cutoff_hz"], theory, places=9)
        self.assertAlmostEqual(
            self.payload["measured_cutoff_hz"], 1547.744629388391, places=6)
        self.assertLess(abs(self.payload["cutoff_delta_percent"]), 1.0)
        self.assertLess(self.payload["one_pole_fit"]["residual_rms"], 0.01)
        self.assertGreater(
            self.payload["one_pole_fit"]["passband"]["gain_db"], -1.0)

    def test_fit_blocks_and_manifests(self):
        fit_payload = json.loads(
            (self.out / "fit_results.json").read_text(encoding="utf-8"))
        self.assertEqual(len(fit_payload["blocks"]), 96)
        self.assertTrue(all(
            block["fit"]["quality"]["valid"]
            for block in fit_payload["blocks"]))
        source = json.loads(
            (self.out / "source_dataset_manifest.json").read_text(
                encoding="utf-8"))
        self.assertEqual(
            sum(item["role"] == "analysis_block" for item in source["files"]),
            96)
        manifest = json.loads(
            (self.out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "RC_MEASURED")
        self.assertEqual(manifest["point_count"], 16)
        for name, info in manifest["files"].items():
            path = self.out / name
            self.assertEqual(path.stat().st_size, info["bytes"], name)
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest().upper(),
                info["sha256"], name)


if __name__ == "__main__":
    unittest.main()
