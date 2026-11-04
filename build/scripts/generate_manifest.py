#!/usr/bin/env python3
"""Generate SHA256 coverage for the submission repository."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "submission_manifest.json"
EXCLUDED_PARTS = {"__pycache__", ".git", ".pytest_cache", ".ipynb_checkpoints", ".venv"}
EXCLUDED_NAMES = {"submission_manifest.json", "host_validation_latest.txt", "host_validation_latest.json", ".DS_Store", "Thumbs.db", "desktop.ini"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def included_files() -> list[tuple[str, Path]]:
    result = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.name in EXCLUDED_NAMES or path.suffix == ".pyc":
            continue
        result.append((relative.as_posix(), path))
    return result


def main() -> int:
    files = {relative: sha256(path) for relative, path in included_files()}
    payload = {
        "schema_version": 1,
        "file_count": len(files),
        "hash_algorithm": "SHA256",
        "files_sha256": files,
    }
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "manifest": str(OUTPUT),
        "files": len(files),
        "sha256": sha256(OUTPUT),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
