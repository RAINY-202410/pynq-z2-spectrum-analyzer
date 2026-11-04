#!/usr/bin/env python3
"""Verify repository naming, required structure, and SHA256 manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "submission_manifest.json"
NAME = re.compile(r"[a-z0-9_.-]+")
EXCLUDED_PARTS = {"__pycache__", ".git", ".pytest_cache", ".ipynb_checkpoints", ".venv"}
EXCLUDED_NAMES = {"submission_manifest.json", "host_validation_latest.txt", "host_validation_latest.json", ".DS_Store", "Thumbs.db", "desktop.ini"}


def included(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return (not any(part in EXCLUDED_PARTS for part in relative.parts)
            and path.name not in EXCLUDED_NAMES and path.suffix != ".pyc")

REQUIRED = (
    "readme.md",
    "license.md",
    "packeditor.ipynb",
    "spectrum_software_v1_r4_bplus_board.zip",
    "report/ai_records/figure15_original_dialogue_excerpt_20261104.md",
    "build/board_files/pynq-z2/a.0/board.xml",
    "build/reports/fft/synthesis_utilization.rpt",
    "report/final_recheck.md",
    "src/hw/ip/fft_system_bd.tcl",
    "sim/m4/tb_m4_delivery.v",
    "build/reports/fft/utilization.rpt",
    "build/reports/fft/timing.rpt",
    "report/design_report.docx",
    "src/hw/rtl",
    "sim/rtl_fft",
    "build/scripts",
    "board/software/spectrum_software_v1_r4_bplus_board.zip",
    "board/overlays/fft/fft.bit",
    "board/overlays/fft/fft.hwh",
    "data/b11_signal_generator/calibration_summary.csv",
    "data/b12_rc_measured/rc_measured.csv",
    "skill/readme.md",
    "report/design_report.md",
)
EXPECTED_OVERLAYS = {
    "board/overlays/fft/fft.bit":
        "A00606402E7ADC8929DEDA61FFAD39236AD3500FF87976E001292A6078551E26",
    "board/overlays/fft/fft.hwh":
        "A4F43CC8594ECCCD6F30B43E5BFC935DDFA0F2825AD90C1D9F659B5DE1DCE091",
    "board/overlays/m4/m4.bit":
        "07A075244EB332556556C6D46D1A7B8523CBDFF8FE6A23527FA33ADDBE832EF8",
    "board/overlays/m4/m4.hwh":
        "C9721187B8E6AEEC91AEBB1FDA57148BA4C18E395758AEF0EC392062AC177F2D",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def verify_board_zip() -> dict:
    archive = (
        ROOT / "board" / "software"
        / "spectrum_software_v1_r4_bplus_board.zip"
    )
    prefix = "spectrum_software_v1_r4_bplus/"
    with zipfile.ZipFile(archive) as package:
        manifest = json.loads(
            package.read(prefix + "software_manifest.json"))
        expected = manifest["files_sha256"]
        actual = {
            name[len(prefix):]: hashlib.sha256(package.read(name)).hexdigest().upper()
            for name in package.namelist()
            if name.startswith(prefix)
            and not name.endswith("/")
            and name != prefix + "software_manifest.json"
        }
    if set(actual) != set(expected):
        raise ValueError("Board ZIP file coverage mismatch")
    changed = [
        name for name, value in expected.items()
        if actual[name] != value.upper()
    ]
    if changed:
        raise ValueError("Board ZIP changed files: " + ", ".join(changed))
    return {
        "build_revision": manifest["build_revision"],
        "status": manifest["status"],
        "verified_files": len(expected),
    }


def main() -> int:
    errors = []
    for relative in REQUIRED:
        if not (ROOT / relative).exists():
            errors.append("Missing required path: " + relative)
    for relative, expected in EXPECTED_OVERLAYS.items():
        path = ROOT / relative
        if not path.is_file():
            errors.append("Missing overlay: " + relative)
        elif sha256(path) != expected:
            errors.append("Overlay hash mismatch: " + relative)
    for path in ROOT.rglob("*"):
        if not included(path, ROOT):
            continue
        if not NAME.fullmatch(path.name):
            errors.append(
                "Non-conforming name: " + path.relative_to(ROOT).as_posix())
    if not MANIFEST.is_file():
        errors.append("Missing submission_manifest.json")
    else:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        actual = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file() and included(p, ROOT)}
        listed = set(manifest["files_sha256"])
        for relative in sorted(actual - listed):
            errors.append("Unlisted file: " + relative)
        for relative, expected in manifest["files_sha256"].items():
            path = ROOT / relative
            if not path.is_file():
                errors.append("Manifest file missing: " + relative)
            elif sha256(path) != expected.upper():
                errors.append("Manifest hash mismatch: " + relative)
    board = verify_board_zip()
    result = {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "board_package": board,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
