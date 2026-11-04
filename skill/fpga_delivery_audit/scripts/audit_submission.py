#!/usr/bin/env python3
"""Portable naming and manifest audit for an FPGA submission."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


NAME = re.compile(r"[a-z0-9_.-]+")
EXCLUDED_PARTS = {"__pycache__", ".git", ".pytest_cache", ".ipynb_checkpoints", ".venv"}
EXCLUDED_NAMES = {"submission_manifest.json", "host_validation_latest.txt", "host_validation_latest.json", ".DS_Store", "Thumbs.db", "desktop.ini"}


def included(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return (not any(part in EXCLUDED_PARTS for part in relative.parts)
            and path.name not in EXCLUDED_NAMES and path.suffix != ".pyc")



def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    errors = []
    required_paths = [
        "readme.md",
        "src",
        "sim",
        "build",
        "board",
        "data",
        "skill",
        "report",
    ]
    for relative in required_paths:
        if not (root / relative).exists():
            errors.append("missing: " + relative)
    for path in root.rglob("*"):
        if not included(path, root):
            continue
        if not NAME.fullmatch(path.name):
            errors.append(
                "non-conforming name: "
                + path.relative_to(root).as_posix())
    manifest_path = root / "submission_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and included(p, root)}
        listed = set(manifest.get("files_sha256", {}))
        for relative in sorted(actual - listed):
            errors.append("unlisted file: " + relative)
        for relative, expected in manifest.get("files_sha256", {}).items():
            path = root / relative
            if not path.is_file():
                errors.append("manifest missing file: " + relative)
            elif sha256(path) != expected.upper():
                errors.append("manifest hash mismatch: " + relative)
    else:
        errors.append("missing: submission_manifest.json")
    result = {"status": "PASS" if not errors else "FAIL",
              "errors": errors}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
