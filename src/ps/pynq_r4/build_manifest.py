"""Generate the deterministic R4 board software manifest."""

import argparse
import hashlib
import json
from pathlib import Path

from fft_campaign_export import notebook_source

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "software_manifest.json"
NOTEBOOK = HERE / "spectrum_analyzer.ipynb"
BUILD_REVISION = "spectrum_software_1_r4_bplus"
EXCLUDED_PARTS = {
    "__pycache__", ".pytest_cache", "spectrum_results", "m4_results",
    "user_records",
}
EXCLUDED_NAMES = {"software_manifest.json"}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def included_files(base=HERE):
    base = Path(base).resolve()
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.name in EXCLUDED_NAMES:
            continue
        relative = path.relative_to(base)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.suffix == ".pyc":
            continue
        yield relative.as_posix(), path


def build(base=HERE):
    base = Path(base).resolve()
    notebook = json.loads((base / NOTEBOOK.name).read_text(encoding="utf-8"))
    cell_count = len(notebook["cells"])
    files = {
        relative: sha256(path)
        for relative, path in included_files(base)
    }
    payload = {
        "software_revision": "spectrum_software_1",
        "build_revision": BUILD_REVISION,
        "status": "HOST_VALIDATED_BOARD_PENDING",
        "FPGA_contract": "v1.0",
        "part": "xc7z020clg400-1",
        "components": {
            "fft": "r3-derived, unchanged bit/hwh and numerical contract",
            "bplus": "B-X01 through B-X12 integrated under /bx",
            "m4": "exclusive M4 stereo capture mode",
        },
        "files_sha256": files,
        "file_count": len(files),
        "notebook": NOTEBOOK.name,
        "notebook_cell_count": cell_count,
        "notebook_source_sha256": notebook_source(notebook, cell_count),
    }
    (base / MANIFEST.name).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=HERE)
    args = parser.parse_args(argv)
    payload = build(args.base)
    print(json.dumps({
        "build_revision": payload["build_revision"],
        "status": payload["status"],
        "files": payload["file_count"],
        "notebook_cells": payload["notebook_cell_count"],
        "manifest_sha256": sha256(args.base / MANIFEST.name),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
