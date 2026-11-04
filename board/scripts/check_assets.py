#!/usr/bin/env python3
"""Cross-platform verification for board asset SHA256 values."""

from __future__ import annotations

import hashlib
from pathlib import Path


BOARD_ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> int:
    errors = []
    for line in (BOARD_ROOT / "assets.sha256").read_text(
            encoding="ascii").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(maxsplit=1)
        path = BOARD_ROOT / relative.strip()
        if not path.is_file():
            errors.append("missing: " + relative)
        elif sha256(path) != expected:
            errors.append("hash mismatch: " + relative)
    if errors:
        print("FAIL")
        for error in errors:
            print("  " + error)
        return 1
    print("PASS: board assets match board/assets.sha256")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
