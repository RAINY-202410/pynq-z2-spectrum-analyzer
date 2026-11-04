#!/usr/bin/env python3
"""Extract the signed R4 package and run reproducible host checks."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "board" / "software" / "spectrum_software_v1_r4_bplus_board.zip"
RESULT_DIR = ROOT / "sim" / "results"


def run(command: list[str], cwd: Path) -> dict:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return {
        "command": command,
        "cwd": str(cwd),
        "returncode": completed.returncode,
        "output": completed.stdout,
    }


def verify_manifest(package: Path) -> dict:
    command = [
        sys.executable,
        "-c",
        (
            "import json; from pathlib import Path; "
            "from spectrum_integrity import verify_software; "
            "print(json.dumps(verify_software(Path('.')), indent=2))"
        ),
    ]
    return run(command, package)


def main() -> int:
    if not ARCHIVE.is_file():
        raise SystemExit("Missing board package: " + str(ARCHIVE))
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    checks = []
    with tempfile.TemporaryDirectory(prefix="pynq_r4_host_") as temporary:
        extract_root = Path(temporary)
        with zipfile.ZipFile(ARCHIVE) as archive:
            archive.extractall(extract_root)
        package = extract_root / "spectrum_software_v1_r4_bplus"
        checks.append(run(
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-p",
                "test_r4_integration.py",
                "-v",
            ],
            package,
        ))
        checks.append(run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            package / "bplus",
        ))
        checks.append(verify_manifest(package))
        node = shutil.which("node")
        if node:
            os.environ["VOLTA_HOME"] = str(extract_root / ".volta")
            checks.append(run(
                [node, "--check", "spectrum_web/workspace.js"],
                package,
            ))
        else:
            checks.append({
                "command": ["node", "--check", "spectrum_web/workspace.js"],
                "cwd": str(package),
                "returncode": None,
                "output": "SKIPPED: Node.js is not installed.",
            })

    sections = []
    for index, check in enumerate(checks, 1):
        command = " ".join(check["command"])
        sections.append(
            "===== check {} =====\n"
            "cwd: {}\n"
            "command: {}\n"
            "returncode: {}\n"
            "{}\n".format(
                index,
                check["cwd"],
                command,
                check["returncode"],
                check["output"].rstrip(),
            )
        )
    log = "\n".join(sections) + "\n"
    (RESULT_DIR / "host_validation_latest.txt").write_text(
        log, encoding="utf-8", newline="\n")
    status = all(
        check["returncode"] in (0, None) for check in checks)
    summary = {
        "status": "PASS" if status else "FAIL",
        "board_package": str(ARCHIVE.relative_to(ROOT)),
        "checks": [
            {
                "command": check["command"],
                "returncode": check["returncode"],
            }
            for check in checks
        ],
    }
    (RESULT_DIR / "host_validation_latest.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(log, end="")
    return 0 if status else 1


if __name__ == "__main__":
    raise SystemExit(main())
