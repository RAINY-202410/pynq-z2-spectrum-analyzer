"""B-X01 output boundary checks."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import export_results  # noqa: E402


class ExportGuardTest(unittest.TestCase):
    def test_relative_path_stays_inside_reports(self):
        target = export_results.resolve_report_path("analysis/run01/summary.json")
        self.assertEqual(target, (ROOT / "reports" / "analysis" / "run01" / "summary.json").resolve())
        target.relative_to(export_results.reports_root())

    def test_parent_traversal_is_rejected(self):
        for name in ("../outside.json", "run/../../outside.json", "..\\outside.json"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    export_results.resolve_report_path(name)

    def test_absolute_and_drive_paths_are_rejected(self):
        for name in ("C:\\temp\\outside.json", "D:/outside.json", "/tmp/outside.json"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    export_results.resolve_report_path(name)

    def test_empty_and_nul_names_are_rejected(self):
        for name in ("", "   ", "bad\x00name.json"):
            with self.subTest(name=repr(name)):
                with self.assertRaises(ValueError):
                    export_results.resolve_report_path(name)


if __name__ == "__main__":
    unittest.main()
