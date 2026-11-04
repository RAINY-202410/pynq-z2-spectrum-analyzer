"""Consolidate a complete B-X11 straight-through calibration dataset."""

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np

from .channel_calibration import calibrate_point
from .phasor_fit import fit_stereo

FREQUENCIES_HZ = [
    200, 300, 500, 700, 1000, 1200, 1400, 1500,
    1592, 1700, 1900, 2200, 3000, 4000, 6000, 8000,
]
NAME_RE = re.compile(r"^b11_f(\d{4})_(cal|val)(?:_retry)?_(\d{2})\.npy$")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def discover(dataset_dir, ignore_retry=False):
    dataset_dir = Path(dataset_dir)
    groups = {}
    for path in sorted(dataset_dir.glob("b11_f*_*.npy")):
        if ignore_retry and "_retry_" in path.name:
            continue
        match = NAME_RE.match(path.name)
        if not match:
            continue
        frequency = int(match.group(1))
        role = match.group(2)
        groups.setdefault(frequency, {"cal": [], "val": []})[role].append(path)
    missing = [frequency for frequency in FREQUENCIES_HZ if frequency not in groups]
    if missing:
        raise ValueError("missing B-X11 frequency groups: " + str(missing))
    for frequency in FREQUENCIES_HZ:
        if len(groups[frequency]["cal"]) < 3 or len(groups[frequency]["val"]) < 3:
            raise ValueError("frequency {} has fewer than 3 cal/val blocks".format(frequency))
    return groups


def _write_source_manifest(dataset_dir, out_dir, ignore_retry):
    entries = []
    for path in sorted(item for item in dataset_dir.iterdir() if item.is_file()):
        match = NAME_RE.match(path.name)
        if match:
            role = "excluded_retry" if ignore_retry and "_retry_" in path.name else "analysis_block"
        else:
            role = "metadata"
        entries.append({
            "file": path.name,
            "role": role,
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        })
    payload = {
        "step": "B-X11",
        "dataset": dataset_dir.name,
        "ignore_retry": bool(ignore_retry),
        "excluded_files": [
            item["file"] for item in entries if item["role"] == "excluded_retry"
        ],
        "files": entries,
    }
    (out_dir / "source_dataset_manifest.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8")


def build(dataset_dir, out_dir, fs_hz, ignore_retry=False, conditions=None):
    dataset_dir = Path(dataset_dir).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    groups = discover(dataset_dir, ignore_retry=ignore_retry)
    points = []
    rejected = []
    block_fits = []
    for frequency in FREQUENCIES_HZ:
        cal_paths = groups[frequency]["cal"]
        val_paths = groups[frequency]["val"]
        all_paths = cal_paths + val_paths
        fits = {}
        for path in all_paths:
            samples = np.load(path, allow_pickle=False)
            fit = fit_stereo(
                samples, fs_hz, float(frequency), search_span_hz=5.0,
                search_resolution_hz=0.01, source="M4_RAW_STEREO")
            fits[path] = fit
            block_fits.append({
                "frequency_hz": frequency,
                "file": path.name,
                "role": "cal" if path in cal_paths else "val",
                "fit": fit,
            })
        if any(not fits[path]["quality"]["valid"] for path in cal_paths):
            raise ValueError("invalid calibration block at {} Hz".format(frequency))
        valid_val = [path for path in val_paths if fits[path]["quality"]["valid"]]
        invalid_val = [path for path in val_paths if not fits[path]["quality"]["valid"]]
        for path in invalid_val:
            rejected.append({
                "frequency_hz": frequency,
                "file": path.name,
                "reasons": fits[path]["quality"]["reasons"],
                "sha256": sha256(path),
            })
        if len(valid_val) < 3:
            raise ValueError("frequency {} has fewer than 3 valid validation blocks".format(frequency))
        selected = valid_val[:3]
        point = calibrate_point(cal_paths, selected, fs_hz, nominal_hz=float(frequency))
        point["target_hz"] = float(frequency)
        point["role"] = "calibration"
        point["selected_validation_files"] = [path.name for path in selected]
        point["rejected_validation_files"] = [path.name for path in invalid_val]
        points.append(point)

    passed = sum(1 for point in points if point["status"] == "PILOT_PASS")
    recorded_conditions = {
        "source_profile": "UNKNOWN_NOT_RECORDED",
        "volume": "UNKNOWN_NOT_RECORDED",
        "input_route": "UNKNOWN_NOT_RECORDED",
        "temperature": "UNKNOWN_NOT_RECORDED",
        "generator_waveform": "UNKNOWN_NOT_RECORDED",
        "generator_amplitude_vpp": "UNKNOWN_NOT_RECORDED",
        "generator_output_impedance": "UNKNOWN_NOT_RECORDED",
    }
    recorded_conditions.update(conditions or {})
    recorded_conditions.update({
        "codec": "configure_codec() from M4 candidate",
        "fs_hz": float(fs_hz),
        "m4_bit_sha256": "07a075244eb332556556c6d46d1a7b8523cbdff8fe6a23527fa33addbe832ef8",
        "m4_hwh_sha256": "c9721187b8e6aeec91aebb1fda57148ba4c18e395758aef0ec392062ac177f2d",
    })
    unknown_conditions = [
        key for key, value in recorded_conditions.items()
        if value is None
        or str(value).startswith("UNKNOWN")
        or "UNSPECIFIED" in str(value)
    ]
    conditions_complete = not unknown_conditions
    if passed == len(points):
        status = "BOARD_VALIDATED" if conditions_complete else (
            "BOARD_DATA_VALIDATED_CONDITIONS_PENDING")
    else:
        status = "BOARD_DATA_PARTIAL"
    notes = [
        "All 16 frequency points have 3 valid calibration blocks and 3 valid validation blocks.",
        "No RC circuit is connected in B-X11.",
    ]
    six_k = next(point for point in points if point["target_hz"] == 6000.0)
    if ignore_retry:
        notes.append(
            "b11_f6000_val_retry_01.npy was excluded by user request; "
            "6 kHz validation uses val_01 through val_03.")
    elif "b11_f6000_val_retry_01.npy" in six_k["selected_validation_files"]:
        notes.append(
            "b11_f6000_val_retry_01.npy was selected after the original "
            "validation set did not provide three valid blocks.")
    elif six_k["rejected_validation_files"]:
        notes.append("Only the selected 6 kHz validation blocks were used.")
    if conditions_complete:
        notes.append("The recorded source, amplitude, route and temperature conditions are complete.")
    else:
        notes.append(
            "Physical generator amplitude, output impedance or other source conditions "
            "remain incomplete for this dataset.")
    _write_source_manifest(dataset_dir, out_dir, ignore_retry)
    payload = {
        "step": "B-X11",
        "status": status,
        "source": "M4_RAW_STEREO",
        "source_profile": recorded_conditions["source_profile"],
        "dataset": dataset_dir.name,
        "fs_hz": float(fs_hz),
        "point_count": len(points),
        "pass_count": passed,
        "all_points_passed": passed == len(points),
        "conditions_complete": conditions_complete,
        "unknown_conditions": unknown_conditions,
        "points": points,
        "rejected_blocks": rejected,
        "conditions": recorded_conditions,
        "notes": notes,
    }
    (out_dir / "channel_calibration.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8")
    (out_dir / "fit_results.json").write_text(
        json.dumps({"step": "B-X11", "source": "M4_RAW_STEREO", "fs_hz": fs_hz,
                    "blocks": block_fits}, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8")
    with (out_dir / "calibration_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "target_hz", "C0_gain_db", "C0_phase_deg",
            "validation_mean_gain_db", "validation_mean_phase_deg",
            "validation_std_gain_db", "validation_std_phase_deg",
            "selected_validation_files", "pass",
        ])
        writer.writeheader()
        for point in points:
            c0, val = point["C0"], point["independent_validation"]
            writer.writerow({
                "target_hz": point["target_hz"],
                "C0_gain_db": c0["gain_db"],
                "C0_phase_deg": c0["phase_deg"],
                "validation_mean_gain_db": val["mean_gain_db"],
                "validation_mean_phase_deg": val["mean_phase_deg"],
                "validation_std_gain_db": val["std_gain_db"],
                "validation_std_phase_deg": val["std_phase_deg"],
                "selected_validation_files": ";".join(point["selected_validation_files"]),
                "pass": point["status"] == "PILOT_PASS",
            })
    plot_repeatability(out_dir, points, status)
    files = sorted(path for path in out_dir.iterdir() if path.is_file() and path.name != "manifest.json")
    manifest = {
        "schema_version": 1,
        "step": "B-X11",
        "status": status,
        "fs_hz": float(fs_hz),
        "point_count": len(points),
        "pass_count": passed,
        "rejected_block_count": len(rejected),
        "conditions_complete": conditions_complete,
        "ignore_retry": bool(ignore_retry),
        "files": {
            path.name: {
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            } for path in files
        },
        "raw_dataset": {
            "path": dataset_dir.name,
            "file_count": sum(len(item["cal"]) + len(item["val"]) for item in groups.values()),
            "excluded_retry_files": (
                ["b11_f6000_val_retry_01.npy"] if ignore_retry else []),
        },
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8")
    return payload


def plot_repeatability(out_dir, points, status):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    frequencies = [point["target_hz"] for point in points]
    c0_gain = [point["C0"]["gain_db"] for point in points]
    c0_phase = [point["C0"]["phase_deg"] for point in points]
    val_gain = [point["independent_validation"]["mean_gain_db"] for point in points]
    val_phase = [point["independent_validation"]["mean_phase_deg"] for point in points]
    val_gain_std = [point["independent_validation"]["std_gain_db"] or 0 for point in points]
    val_phase_std = [point["independent_validation"]["std_phase_deg"] or 0 for point in points]
    fig, (ax_g, ax_p) = plt.subplots(1, 2, figsize=(14, 5.2), dpi=140)
    ax_g.errorbar(frequencies, c0_gain, yerr=None, marker="o", color="#0f766e",
                  label="C0 gain")
    ax_g.errorbar(frequencies, val_gain, yerr=val_gain_std, marker="x", color="#2563eb",
                  label="validation H_cal gain")
    ax_g.axhline(0, color="#94a3b8", linestyle=":")
    ax_g.set_xscale("log")
    ax_g.set_xlabel("Frequency (Hz)")
    ax_g.set_ylabel("Gain (dB)")
    ax_g.grid(True, which="both", alpha=0.2)
    ax_g.legend(fontsize=8)
    ax_p.errorbar(frequencies, c0_phase, yerr=None, marker="o", color="#0f766e",
                  label="C0 phase")
    ax_p.errorbar(frequencies, val_phase, yerr=val_phase_std, marker="x", color="#2563eb",
                  label="validation H_cal phase")
    ax_p.axhline(0, color="#94a3b8", linestyle=":")
    ax_p.set_xscale("log")
    ax_p.set_xlabel("Frequency (Hz)")
    ax_p.set_ylabel("Phase (deg)")
    ax_p.grid(True, which="both", alpha=0.2)
    ax_p.legend(fontsize=8)
    fig.suptitle("B-X11 straight-through calibration · 16 frequency points · " + status,
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(out_dir / "calibration_repeatability.png", bbox_inches="tight")
    fig.savefig(out_dir / "calibration_repeatability.svg", bbox_inches="tight")
    plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", required=True)
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).resolve().parents[1] / "reports" / "B-X11" / "full_20261101")
    parser.add_argument("--fs-hz", type=float, default=47998.77998801426)
    parser.add_argument("--ignore-retry", action="store_true")
    parser.add_argument(
        "--condition", action="append", default=[], metavar="KEY=VALUE",
        help="record or override a physical-condition field")
    args = parser.parse_args(argv)
    conditions = {}
    for item in args.condition:
        if "=" not in item:
            raise ValueError("--condition must be KEY=VALUE: " + item)
        key, value = item.split("=", 1)
        conditions[key.strip()] = value.strip()
    payload = build(
        args.dataset_dir, args.out, args.fs_hz,
        ignore_retry=args.ignore_retry, conditions=conditions)
    print(json.dumps({
        "step": "B-X11",
        "status": payload["status"],
        "points": payload["point_count"],
        "passed": payload["pass_count"],
        "rejected_blocks": len(payload["rejected_blocks"]),
    }, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    raise SystemExit(main())
