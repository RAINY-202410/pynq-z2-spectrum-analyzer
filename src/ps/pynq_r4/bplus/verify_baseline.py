#!/usr/bin/env python3
"""Verify the b_plus_v1 B-X01 baseline without touching hardware."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

EXTENSION = "b_plus_v1"
STEP = "B-X01"
HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent.parent
MANIFEST_PATH = HERE / "BASELINE_MANIFEST.json"
DEFAULT_SOURCE = WORKSPACE / "documents" / "B_拓展加分操作包_20261030.zip"


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest().upper()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _check(result: dict, name: str, condition: bool, detail: str | None = None) -> None:
    result["checks"].append({"name": name, "ok": bool(condition), "detail": detail})
    if not condition:
        result["failures"].append(name if detail is None else f"{name}: {detail}")


def _find_source(explicit: str | None) -> Path | None:
    if explicit:
        path = Path(explicit)
        return path if path.is_file() else None
    candidates = (
        DEFAULT_SOURCE,
        HERE / DEFAULT_SOURCE.name,
        WORKSPACE / DEFAULT_SOURCE.name,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _verify_zip_members(result: dict, zip_blob: bytes, prefix: str, items: list[dict], label: str) -> None:
    with zipfile.ZipFile(io.BytesIO(zip_blob)) as archive:
        names = set(archive.namelist())
        for item in items:
            entry = prefix + item["source_path"]
            if entry not in names:
                _check(result, f"{label}_zip_entry_present", False, entry)
                continue
            actual = sha256_bytes(archive.read(entry))
            _check(
                result,
                f"{label}_zip_entry_hash",
                actual == item["sha256"],
                f"{entry} expected {item['sha256']} got {actual}",
            )


def verify(source_package: str | None = None, require_source: bool = False) -> dict:
    result = {
        "extension": EXTENSION,
        "step": STEP,
        "ok": False,
        "hardware_access": False,
        "checks": [],
        "failures": [],
        "source": {
            "outer_package_checked": False,
            "r3_archive_checked": False,
            "status": "NOT_CHECKED",
        },
        "counts": {},
    }
    manifest = read_json(MANIFEST_PATH)
    outer_expected = manifest["source_package"]["sha256"].upper()
    r3_expected = manifest["r3_candidate"]["sha256"].upper()

    baseline_root = HERE / manifest["baseline_readonly"]["root"]
    input_root = HERE / manifest["inputs_readonly"]["root"]
    baseline_items = manifest["baseline_readonly"]["files"]
    input_items = manifest["inputs_readonly"]["files"]

    listed = set()
    for item in baseline_items:
        path = HERE / item["path"]
        listed.add(path.resolve())
        if not path.is_file():
            _check(result, "baseline_file_present", False, item["path"])
            continue
        actual = sha256_file(path)
        _check(
            result,
            "baseline_file_hash",
            actual == item["sha256"],
            f"{item['path']} expected {item['sha256']} got {actual}",
        )

    actual_baseline = {
        p.resolve()
        for p in baseline_root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }
    _check(result, "baseline_no_unlisted_files", actual_baseline == listed,
           f"unlisted={sorted(str(p.relative_to(HERE)) for p in actual_baseline - listed)}")

    listed_inputs = set()
    for item in input_items:
        path = HERE / item["path"]
        listed_inputs.add(path.resolve())
        if not path.is_file():
            _check(result, "input_file_present", False, item["path"])
            continue
        actual = sha256_file(path)
        _check(
            result,
            "input_file_hash",
            actual == item["sha256"],
            f"{item['path']} expected {item['sha256']} got {actual}",
        )
    actual_inputs = {
        p.resolve()
        for p in input_root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }
    _check(result, "inputs_no_unlisted_files", actual_inputs == listed_inputs,
           f"unlisted={sorted(str(p.relative_to(HERE)) for p in actual_inputs - listed_inputs)}")

    r3_manifest_path = HERE / "baseline_readonly" / "package_manifest.json"
    if r3_manifest_path.is_file():
        _check(
            result,
            "r3_package_manifest_hash",
            sha256_file(r3_manifest_path) == manifest["r3_candidate"]["package_manifest_sha256"].upper(),
            str(r3_manifest_path),
        )
        r3_manifest = read_json(r3_manifest_path)
        r3_hashes = {key: value.upper() for key, value in r3_manifest.get("files_sha256", {}).items()}
        for item in baseline_items:
            if item["source"] != "r3" or item.get("source_path") == "package_manifest.json":
                continue
            source_path = item["source_path"]
            _check(
                result,
                "r3_manifest_entry",
                r3_hashes.get(source_path) == item["sha256"],
                source_path,
            )

    source = _find_source(source_package)
    if source is None:
        result["source"]["status"] = "SOURCE_PACKAGE_NOT_FOUND"
        _check(result, "source_package_found", not require_source,
               f"not found; pass --source-package {DEFAULT_SOURCE}")
    else:
        source_hash = sha256_file(source)
        result["source"]["path"] = str(source)
        result["source"]["sha256"] = source_hash
        if source_hash == outer_expected:
            result["source"]["outer_package_checked"] = True
            result["source"]["status"] = "OUTER_PACKAGE_VERIFIED"
            with zipfile.ZipFile(source) as outer:
                outer_manifest = json.loads(outer.read("manifest.json").decode("utf-8"))
                _check(
                    result,
                    "outer_manifest_hash",
                    sha256_bytes(outer.read("manifest.json"))
                    == manifest["source_package"]["manifest_sha256"].upper(),
                    "manifest.json",
                )
                outer_hashes = {item["path"]: item["sha256"].upper() for item in outer_manifest["files"]}
                for item in input_items:
                    if item["source"] != "outer":
                        continue
                    source_path = item["source_path"]
                    _check(
                        result,
                        "outer_manifest_entry",
                        outer_hashes.get(source_path) == item["sha256"],
                        f"{source_path}",
                    )
                for item in baseline_items:
                    if item["source"] == "outer":
                        source_path = item["source_path"]
                        _check(
                            result,
                            "outer_manifest_entry",
                            outer_hashes.get(source_path) == item["sha256"],
                            f"{source_path}",
                        )
                r3_blob = outer.read("baseline/A_spectrum_software_v1_r3.zip")
                _check(
                    result,
                    "r3_archive_hash",
                    sha256_bytes(r3_blob) == r3_expected,
                    "baseline/A_spectrum_software_v1_r3.zip",
                )
                result["source"]["r3_archive_checked"] = True
                _verify_zip_members(
                    result,
                    r3_blob,
                    "A_spectrum_software_v1_r3/",
                    [item for item in baseline_items if item["source"] == "r3"],
                    "r3",
                )
                _verify_zip_members(
                    result,
                    source.read_bytes(),
                    "",
                    [item for item in baseline_items if item["source"] == "outer"]
                    + [item for item in input_items if item["source"] == "outer"],
                    "outer",
                )
        elif source_hash == r3_expected:
            result["source"]["r3_archive_checked"] = True
            result["source"]["status"] = "R3_ARCHIVE_VERIFIED"
            _verify_zip_members(
                result,
                source.read_bytes(),
                "A_spectrum_software_v1_r3/",
                [item for item in baseline_items if item["source"] == "r3"],
                "r3",
            )
        else:
            _check(result, "source_package_hash", False,
                   f"expected outer {outer_expected} or r3 {r3_expected}, got {source_hash}")

    result["counts"] = {
        "baseline_files": len(baseline_items),
        "input_files": len(input_items),
        "checks": len(result["checks"]),
    }
    result["ok"] = not result["failures"]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-package", help="outer operation ZIP or r3 ZIP")
    parser.add_argument("--require-source", action="store_true",
                        help="fail if the original package cannot be found")
    args = parser.parse_args(argv)
    result = verify(args.source_package, args.require_source)
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
