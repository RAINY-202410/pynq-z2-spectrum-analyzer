"""B-X11 pilot channel calibration from synchronous M4 stereo blocks.

The full B-X11 requirement needs straight-through captures at every design
frequency and independently repeated conditions. The existing M4 validation
files provide only a 1 kHz pilot, so the output is explicitly marked
HOST_VALIDATED_BOARD_PENDING.
"""

import argparse
import hashlib
import json
import math
import shutil
from pathlib import Path

import numpy as np

try:
    from .phasor_fit import fit_stereo
except ImportError:
    from phasor_fit import fit_stereo

STEP = "B-X11"
SOURCE = "M4_RAW_STEREO"
NOMINAL_HZ = 1000.0


class CalibrationError(ValueError):
    """Raised for missing or overlapping calibration blocks."""


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def _load_fits(paths, fs_hz, nominal_hz):
    results = []
    for path in paths:
        samples = np.load(path, allow_pickle=False)
        fit = fit_stereo(
            samples, fs_hz, nominal_hz, search_span_hz=5.0,
            search_resolution_hz=0.01, source=SOURCE)
        results.append({
            "path": Path(path).name,
            "sha256": sha256(path),
            "fit": fit,
        })
    return results


def calibrate_point(calibration_paths, validation_paths, fs_hz,
                    nominal_hz=NOMINAL_HZ, max_gain_dev_db=0.5,
                    max_phase_dev_deg=2.0):
    calibration_paths = [Path(path).resolve() for path in calibration_paths]
    validation_paths = [Path(path).resolve() for path in validation_paths]
    if len(calibration_paths) < 3 or len(validation_paths) < 3:
        raise CalibrationError("calibration and validation each require at least 3 blocks")
    if set(calibration_paths) & set(validation_paths):
        raise CalibrationError("calibration and validation data must be independent")
    calibration = _load_fits(calibration_paths, fs_hz, nominal_hz)
    validation = _load_fits(validation_paths, fs_hz, nominal_hz)
    valid_cal = [item for item in calibration if item["fit"]["quality"]["valid"]]
    if len(valid_cal) != len(calibration):
        raise CalibrationError("calibration contains invalid stereo block")
    ratios = [
        complex(item["fit"]["transfer_ratio_raw"]["real"],
                item["fit"]["transfer_ratio_raw"]["imag"])
        for item in calibration
    ]
    c0 = complex(float(np.mean([item.real for item in ratios])),
                 float(np.mean([item.imag for item in ratios])))
    c0_gain = 20.0 * math.log10(abs(c0)) if abs(c0) > 0 else None
    c0_phase = math.degrees(math.atan2(c0.imag, c0.real))
    cal_gains = [item["fit"]["transfer_ratio_raw"]["gain_db"] for item in calibration]
    cal_phases = [item["fit"]["transfer_ratio_raw"]["phase_deg"] for item in calibration]

    corrected = []
    for item in validation:
        if not item["fit"]["quality"]["valid"]:
            corrected.append({
                "path": item["path"],
                "valid": False,
                "reason": "INVALID_STEREO_BLOCK",
            })
            continue
        raw = complex(item["fit"]["transfer_ratio_raw"]["real"],
                      item["fit"]["transfer_ratio_raw"]["imag"])
        h_cal = raw / c0
        gain = 20.0 * math.log10(abs(h_cal)) if abs(h_cal) > 0 else None
        phase = math.degrees(math.atan2(h_cal.imag, h_cal.real))
        valid = (gain is not None and abs(gain) <= max_gain_dev_db
                 and abs(phase) <= max_phase_dev_deg)
        corrected.append({
            "path": item["path"],
            "valid": bool(valid),
            "raw_gain_db": item["fit"]["transfer_ratio_raw"]["gain_db"],
            "raw_phase_deg": item["fit"]["transfer_ratio_raw"]["phase_deg"],
            "corrected_gain_db": gain,
            "corrected_phase_deg": phase,
            "frequency_hz": item["fit"]["estimated_frequency_hz"],
            "reasons": [] if valid else ["CORRECTED_RESPONSE_DEVIATES"],
        })
    corrected_valid = [item for item in corrected if item["valid"]]
    corrected_gain = [item["corrected_gain_db"] for item in corrected_valid]
    corrected_phase = [item["corrected_phase_deg"] for item in corrected_valid]
    mean_gain = float(np.mean(corrected_gain)) if corrected_gain else None
    mean_phase = float(np.mean(corrected_phase)) if corrected_phase else None
    std_gain = float(np.std(corrected_gain, ddof=1)) if len(corrected_gain) > 1 else None
    std_phase = float(np.std(corrected_phase, ddof=1)) if len(corrected_phase) > 1 else None
    passed = len(corrected_valid) == len(corrected)
    return {
        "step": STEP,
        "source": SOURCE,
        "nominal_hz": float(nominal_hz),
        "fs_hz": float(fs_hz),
        "channel_assignment": {"left": "input_reference", "right": "rc_output"},
        "calibration_blocks": calibration,
        "validation_blocks": corrected,
        "C0": {
            "real": float(c0.real),
            "imag": float(c0.imag),
            "gain_db": c0_gain,
            "phase_deg": c0_phase,
            "gain_std_db": float(np.std(cal_gains, ddof=1)),
            "phase_std_deg": float(np.std(cal_phases, ddof=1)),
            "gain_range_db": [min(cal_gains), max(cal_gains)],
            "phase_range_deg": [min(cal_phases), max(cal_phases)],
        },
        "independent_validation": {
            "count": len(corrected),
            "valid_count": len(corrected_valid),
            "max_gain_dev_db": max_gain_dev_db,
            "max_phase_dev_deg": max_phase_dev_deg,
            "mean_gain_db": mean_gain,
            "mean_phase_deg": mean_phase,
            "std_gain_db": std_gain,
            "std_phase_deg": std_phase,
            "passed": passed,
        },
        "status": "PILOT_PASS" if passed else "PILOT_INVALID",
        "scope": "M4_PILOT_1KHZ_ONLY",
    }


def build_pilot(m4_dir, out_dir):
    m4_dir = Path(m4_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sample_rate = json.loads((m4_dir / "sample_rate.json").read_text(encoding="utf-8"))
    fs_hz = float(sample_rate["fs_estimate_hz"])
    calibration = [m4_dir / "cap_{:02d}.npy".format(i) for i in range(1, 6)]
    validation = [m4_dir / "cap_{:02d}.npy".format(i) for i in range(6, 11)]
    for path in calibration + validation:
        if not path.is_file():
            raise CalibrationError("missing M4 pilot block: " + str(path))
    point = calibrate_point(calibration, validation, fs_hz)
    raw_dir = out_dir / "raw_pilot"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_files = []
    for role, paths in (("calibration", calibration), ("validation", validation)):
        for path in paths:
            target = raw_dir / path.name
            shutil.copy2(path, target)
            raw_files.append({
                "file": target.relative_to(out_dir).as_posix(),
                "role": role,
                "source": str(path),
                "sha256": sha256(target),
                "bytes": target.stat().st_size,
            })
    design_source = Path(__file__).resolve().parents[1] / "reports" / "B-X09" / "rc_points.json"
    design_payload = json.loads(design_source.read_text(encoding="utf-8"))
    design_points = []
    for item in design_payload["rc_points"]:
        target_hz = item["target_hz"]
        if target_hz == 1000.0:
            status = "PILOT_M4_1KHZ"
            reason = "Existing M4 1 kHz validation blocks; not a full 16-point straight-through session."
        else:
            status = "NOT_MEASURED"
            reason = "No straight-through M4 calibration data at this frequency in B-X11 pilot."
        design_points.append({
            "target_hz": target_hz,
            "status": status,
            "reason": reason,
            "pilot_point": point if target_hz == 1000.0 else None,
        })
    overlay_path = m4_dir / "overlay_hashes.json"
    overlay = json.loads(overlay_path.read_text(encoding="utf-8")) if overlay_path.is_file() else {}
    payload = {
        "step": STEP,
        "status": "HOST_VALIDATED_BOARD_PENDING",
        "scope": "EXISTING_M4_1KHZ_VALIDATION_PILOT",
        "source": SOURCE,
        "conditions": {
            "volume": "UNKNOWN_IN_EXISTING_FILES",
            "input_route": "UNKNOWN_IN_EXISTING_FILES",
            "temperature": "UNKNOWN_IN_EXISTING_FILES",
            "fs_hz": fs_hz,
            "fs_method": sample_rate.get("method"),
            "overlay_sha256": overlay,
            "source_directory": str(m4_dir),
        },
        "channel_assignment": {"left": "input_reference", "right": "rc_output"},
        "calibration_point": point,
        "design_points": design_points,
        "raw_files": raw_files,
        "board_pending": [
            "Full 16-frequency straight-through calibration.",
            "Independent validation at every design frequency.",
            "Recorded volume, input route, codec gain and temperature.",
            "Separate M4-only session after r2 data preservation.",
        ],
        "notes": [
            "The existing 10 M4 validation captures are real stereo files, but they were not a complete B-X11 session.",
            "No RC connection or RC measured response is included.",
            "No interpolation is used between calibration-frequency points.",
        ],
    }
    (out_dir / "channel_calibration.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8")
    _plot_repeatability(out_dir, point, design_points)
    files = sorted(path for path in out_dir.rglob("*")
                   if path.is_file() and path.name != "manifest.json")
    manifest = {
        "schema_version": 1,
        "step": STEP,
        "status": payload["status"],
        "source": SOURCE,
        "files": {
            path.relative_to(out_dir).as_posix(): {
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in files
        },
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8")
    return payload


def _plot_repeatability(out_dir, point, design_points):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cal = point["calibration_blocks"]
    val = point["validation_blocks"]
    fig, (ax_g, ax_p) = plt.subplots(1, 2, figsize=(12, 4.8), dpi=140)
    cal_x = np.arange(1, len(cal) + 1)
    val_x = np.arange(len(cal) + 1, len(cal) + len(val) + 1)
    ax_g.scatter(cal_x, [item["fit"]["transfer_ratio_raw"]["gain_db"] for item in cal],
                 color="#0f766e", label="calibration raw")
    ax_g.scatter(val_x, [item["raw_gain_db"] for item in val],
                 color="#f59e0b", marker="s", label="validation raw")
    ax_g.scatter(val_x, [item["corrected_gain_db"] for item in val],
                 color="#2563eb", marker="x", label="validation corrected")
    ax_g.axhline(0, color="#94a3b8", linestyle=":")
    ax_g.set_xlabel("Synchronous block")
    ax_g.set_ylabel("Gain (dB)")
    ax_g.grid(True, alpha=0.2)
    ax_g.legend(fontsize=8)
    ax_p.scatter(cal_x, [item["fit"]["transfer_ratio_raw"]["phase_deg"] for item in cal],
                 color="#0f766e", label="calibration raw")
    ax_p.scatter(val_x, [item["raw_phase_deg"] for item in val],
                 color="#f59e0b", marker="s", label="validation raw")
    ax_p.scatter(val_x, [item["corrected_phase_deg"] for item in val],
                 color="#2563eb", marker="x", label="validation corrected")
    ax_p.axhline(0, color="#94a3b8", linestyle=":")
    ax_p.set_xlabel("Synchronous block")
    ax_p.set_ylabel("Phase (deg)")
    ax_p.grid(True, alpha=0.2)
    ax_p.legend(fontsize=8)
    fig.suptitle("B-X11 1 kHz M4 pilot: calibration/validation repeatability", fontsize=12)
    fig.tight_layout()
    fig.savefig(out_dir / "calibration_repeatability.png", bbox_inches="tight")
    fig.savefig(out_dir / "calibration_repeatability.svg", bbox_inches="tight")
    plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--m4-dir", required=True)
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).resolve().parents[1] / "reports" / "B-X11")
    args = parser.parse_args(argv)
    payload = build_pilot(args.m4_dir, args.out)
    point = payload["calibration_point"]
    print(json.dumps({
        "step": STEP,
        "status": payload["status"],
        "scope": payload["scope"],
        "pilot_status": point["status"],
        "calibration_blocks": len(point["calibration_blocks"]),
        "validation_blocks": len(point["validation_blocks"]),
        "independent_validation_passed": point["independent_validation"]["passed"],
    }, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
