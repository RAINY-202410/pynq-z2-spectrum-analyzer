#!/usr/bin/env python3
"""Static smoke test for a PYNQ bit/hwh pair without programming hardware."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bit", type=Path)
    parser.add_argument("hwh", type=Path)
    args = parser.parse_args()
    bit = args.bit.resolve()
    hwh = args.hwh.resolve()
    if bit.suffix.lower() != ".bit":
        raise SystemExit("Expected a .bit file")
    if hwh.suffix.lower() != ".hwh":
        raise SystemExit("Expected a .hwh file")
    if not bit.is_file() or not hwh.is_file():
        raise SystemExit("bit/hwh pair is incomplete")
    hwh_text = hwh.read_text(encoding="utf-8", errors="replace")
    if "<EDKSYSTEM" not in hwh_text:
        raise SystemExit("HWH does not contain an EDK system description")
    result = {
        "status": "STATIC_PASS",
        "platform": platform.platform(),
        "python": sys.version,
        "bit": {"path": str(bit), "bytes": bit.stat().st_size,
                "sha256": sha256(bit)},
        "hwh": {"path": str(hwh), "bytes": hwh.stat().st_size,
                "sha256": sha256(hwh)},
        "hardware_programmed": False,
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
