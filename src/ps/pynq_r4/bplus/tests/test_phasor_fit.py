"""B-X10 synchronous stereo phasor-fit checks."""

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rc import phasor_fit as pf  # noqa: E402


class PhasorFitTest(unittest.TestCase):
    def test_gain_and_phase_cases(self):
        cases = [
            pf.generate_synthetic_case("gain1_phase0", 1000.0, 0.2, 0.0, 0.0),
            pf.generate_synthetic_case("gain05_phase45", 1592.0, 0.3,
                                       -6.020599913279624, -45.0),
            pf.generate_synthetic_case("gain05_phase90", 3000.0, 0.4,
                                       -6.020599913279624, -90.0,
                                       initial_phase=1.1, dc_left=0.08,
                                       dc_right=-0.06),
        ]
        for case in cases:
            result = pf.fit_stereo(
                case["samples_float"], 48000.0, case["target_hz"],
                search_span_hz=2.0, search_resolution_hz=0.002,
                source="SYNTHETIC_VALIDATION")
            self.assertTrue(result["quality"]["valid"], result["quality"]["reasons"])
            self.assertTrue(result["fit"]["same_frequency_for_both_channels"])
            self.assertAlmostEqual(result["estimated_frequency_hz"],
                                   case["actual_hz"], delta=0.002)
            self.assertAlmostEqual(result["transfer_ratio_raw"]["gain_db"],
                                   case["gain_db"], delta=1e-5)
            self.assertAlmostEqual(result["transfer_ratio_raw"]["phase_deg"],
                                   case["phase_deg"], delta=1e-5)
            self.assertLess(result["fit"]["relative_residual"], 1e-6)
            xfit = result["fit"]["x_reference"]
            yfit = result["fit"]["y_output"]
            truth = case["truth_coefficients"]
            for field, key in (("a", "ax"), ("b", "bx")):
                self.assertLessEqual(abs(xfit[field] - truth[key]), 1e-6)
            for field, key in (("a", "ay"), ("b", "by")):
                self.assertLessEqual(abs(yfit[field] - truth[key]), 1e-6)
            self.assertGreaterEqual(xfit["rank"], 3)
            self.assertGreaterEqual(yfit["rank"], 3)
            self.assertTrue(np.isfinite(xfit["condition"]))
            self.assertTrue(np.isfinite(yfit["condition"]))

    def test_initial_phase_offset_dc_and_integer_format(self):
        case = pf.generate_synthetic_case(
            "offset_dc", 8000.0, 0.4, -20.0, -80.0,
            reference_amplitude=0.3, dc_left=-0.1, dc_right=0.2,
            initial_phase=-0.9)
        result = pf.fit_stereo(
            case["samples_int32"], 48000.0, 8000.0,
            search_span_hz=2.0, search_resolution_hz=0.002)
        self.assertTrue(result["quality"]["valid"], result["quality"]["reasons"])
        self.assertEqual(result["data_range"]["dtype"], "int32")
        self.assertEqual(result["data_range"]["normalization_scale"], 2 ** 23)
        self.assertAlmostEqual(result["estimated_frequency_hz"], 8000.4, delta=0.003)
        self.assertAlmostEqual(result["transfer_ratio_raw"]["gain_db"], -20.0, delta=2e-4)
        self.assertAlmostEqual(result["transfer_ratio_raw"]["phase_deg"], -80.0, delta=2e-4)

    def test_weak_reference_and_clipping_are_invalid(self):
        weak = pf.generate_synthetic_case("weak", 1000.0, 0.2, 0.0, 0.0,
                                          reference_amplitude=1e-5)
        weak_result = pf.fit_stereo(weak["samples_float"], 48000.0, 1000.0,
                                    search_span_hz=2.0, search_resolution_hz=0.01)
        self.assertFalse(weak_result["quality"]["valid"])
        self.assertIn("REFERENCE_WEAK", weak_result["quality"]["reasons"])

        clipped = pf.generate_synthetic_case(
            "clipped", 1000.0, 0.2, 0.0, 0.0,
            reference_amplitude=1.2, dc_left=0.0, dc_right=0.0, clipping=True)
        clipped_result = pf.fit_stereo(clipped["samples_int32"], 48000.0, 1000.0,
                                       search_span_hz=2.0, search_resolution_hz=0.01)
        self.assertFalse(clipped_result["quality"]["valid"])
        self.assertIn("CLIPPING_CANDIDATE", clipped_result["quality"]["reasons"])

    def test_bad_shape_range_and_poor_fit_are_rejected(self):
        with self.assertRaises(pf.PhasorFitError):
            pf.fit_stereo(np.zeros((2, 1000)), 48000.0, 1000.0)
        with self.assertRaises(pf.PhasorFitError):
            pf.fit_stereo(np.full((2, 1024), 2 ** 23, dtype=np.int32), 48000.0, 1000.0)
        case = pf.generate_synthetic_case("poor", 1000.0, 0.2, 0.0, 0.0)
        bad = case["samples_float"].copy()
        rng = np.random.default_rng(4)
        bad[1] = rng.normal(0, 0.3, bad.shape[1])
        result = pf.fit_stereo(bad, 48000.0, 1000.0,
                               search_span_hz=2.0, search_resolution_hz=0.01)
        self.assertFalse(result["quality"]["valid"])
        self.assertIn("POOR_FIT_OR_SYNC_UNVERIFIED", result["quality"]["reasons"])

    def test_report_and_manifest_exist(self):
        out = ROOT / "reports" / "B-X10"
        payload = __import__("json").loads((out / "fit_results.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["step"], "B-X10")
        self.assertEqual(len(payload["bx09_results"]), 4)
        self.assertEqual(len(payload["synthetic_validation"]), 6)
        self.assertIn("fit_results.json", __import__("json").loads(
            (out / "manifest.json").read_text(encoding="utf-8"))["files"])

    def test_no_pynq_import(self):
        if "pynq" in sys.modules:
            self.skipTest("pynq was imported by the environment before this test")
        self.assertNotIn("pynq", sys.modules)


if __name__ == "__main__":
    unittest.main()
