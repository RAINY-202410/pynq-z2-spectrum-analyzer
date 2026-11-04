"""B-X07 exported package and independent recomputation checks."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "reports" / "B-X07" / "demo_export"


class ExportPackageTest(unittest.TestCase):
    def test_real_demo_package_recomputes(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "recompute_export.py"),
             "--package", str(PACKAGE), "--extension-root", str(ROOT)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertTrue(result["ok"])
        self.assertEqual(result["run_id"], "spectrum_38749b56cab6")
        self.assertEqual(result["average_count"], 2)
        self.assertEqual(result["hold_count"], 2)

    def test_package_contract_and_arrays(self):
        summary = json.loads((PACKAGE / "analysis_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["source"]["context"], "BOARD_LIVE")
        self.assertEqual(summary["source"]["display_mode"], "REPLAY")
        self.assertTrue(summary["sparse_retained_spectra"])
        self.assertEqual(summary["run"]["window"], "hann")
        self.assertEqual(summary["run"]["N"], 1024)
        for name in ("mean_square_average.npy", "peak_hold.npy",
                     "current_amplitude.npy", "frequency_hz.npy"):
            array = np.load(PACKAGE / name, allow_pickle=False)
            self.assertEqual(array.shape, (513,))
            self.assertTrue(np.all(np.isfinite(array)))
        readings = json.loads((PACKAGE / "cursor_readings.json").read_text(encoding="utf-8"))
        self.assertEqual(readings["A"]["bin"], 21)
        self.assertEqual(readings["B"]["bin"], 64)
        self.assertTrue(readings["delta"]["ratio_applicable"])

    def test_manifest_hashes(self):
        manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("analysis_summary.json", manifest["files"])
        self.assertIn("mean_square_average.npy", manifest["files"])
        self.assertEqual(manifest["source_session_sha256"],
                         "3E7FFF49310213C024F073566E5420B5F69727BD9E9C225698B90D7272EBD62E")


if __name__ == "__main__":
    unittest.main()
