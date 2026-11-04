"""B-X10 synchronous dual-channel sine fit and transfer ratio.

The first-order model uses one shared frequency for both channels:

    x[n] ~= ax*cos(w*n/fs) + bx*sin(w*n/fs) + cx
    y[n] ~= ay*cos(w*n/fs) + by*sin(w*n/fs) + cy
    Cx = ax - j*bx, Cy = ay - j*by, H_raw = Cy / Cx

No complex FFT phase subtraction or separate single-channel capture is used.
"""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np

STEP = "B-X10"
SOURCE = "M4_RAW_STEREO"
LEFT_ROLE = "input_reference"
RIGHT_ROLE = "rc_output"
FULL_SCALE = 2 ** 23


class PhasorFitError(ValueError):
    """Raised for malformed stereo blocks or fit configuration."""


def _normalise_stereo(samples, clipping_threshold=0.999):
    data = np.asarray(samples)
    if data.shape != (2, 1024):
        raise PhasorFitError("M4 stereo block must have shape (2, 1024)")
    raw_kind = data.dtype.kind
    if raw_kind in ("i", "u"):
        if np.any(data < -(2 ** 23)) or np.any(data > (2 ** 23 - 1)):
            raise PhasorFitError("int samples outside signed 24-bit range")
        normalized = data.astype(np.float64) / FULL_SCALE
        raw_min, raw_max = int(np.min(data)), int(np.max(data))
    elif raw_kind == "f":
        normalized = data.astype(np.float64)
        if np.any(~np.isfinite(normalized)):
            raise PhasorFitError("stereo samples must be finite")
        raw_min, raw_max = float(np.min(data)), float(np.max(data))
    else:
        raise PhasorFitError("stereo samples must be integer or float")
    clipping = bool(np.any(np.abs(normalized) >= clipping_threshold))
    ranges = []
    for channel in normalized:
        ranges.append({
            "min": float(np.min(channel)),
            "max": float(np.max(channel)),
            "peak": float(np.max(np.abs(channel))),
        })
    return normalized, {
        "dtype": str(data.dtype),
        "raw_min": raw_min,
        "raw_max": raw_max,
        "channels": ranges,
        "clipping_candidate": clipping,
        "normalization_scale": FULL_SCALE if raw_kind in ("i", "u") else 1.0,
    }


def _fit_channel(samples, fs_hz, frequency_hz):
    n = np.arange(samples.size, dtype=float)
    phase = 2.0 * np.pi * frequency_hz * n / fs_hz
    design = np.column_stack((np.cos(phase), np.sin(phase), np.ones(samples.size)))
    coefficients, _, rank, singular = np.linalg.lstsq(
        design, samples, rcond=None)
    fitted = design @ coefficients
    residual = samples - fitted
    residual_rms = float(np.sqrt(np.mean(residual * residual)))
    amplitude = float(np.hypot(coefficients[0], coefficients[1]))
    return {
        "a": float(coefficients[0]),
        "b": float(coefficients[1]),
        "c": float(coefficients[2]),
        "complex_real": float(coefficients[0]),
        "complex_imag": float(-coefficients[1]),
        "amplitude": amplitude,
        "residual_rms": residual_rms,
        "rank": int(rank),
        "condition": float(np.linalg.cond(design)),
        "singular_values": [float(value) for value in singular],
    }


def _frequency_score(samples, fs_hz, frequency_hz):
    xfit = _fit_channel(samples[0], fs_hz, frequency_hz)
    yfit = _fit_channel(samples[1], fs_hz, frequency_hz)
    score = xfit["residual_rms"] ** 2 + yfit["residual_rms"] ** 2
    return score, xfit, yfit


def search_frequency(samples, fs_hz, nominal_hz, search_span_hz=5.0,
                     search_resolution_hz=0.01):
    """1-D residual search; both channels always use the same frequency."""
    normalized, _ = _normalise_stereo(samples)
    low = max(0.1, float(nominal_hz) - float(search_span_hz))
    high = min(float(fs_hz) / 2.0 - 0.1, float(nominal_hz) + float(search_span_hz))
    if high <= low:
        raise PhasorFitError("frequency search range is empty")
    count = max(9, int(math.ceil((high - low) / float(search_resolution_hz))) + 1)
    grid = np.linspace(low, high, count)
    scores = np.empty(count, dtype=float)
    fits = []
    for index, frequency in enumerate(grid):
        score, xfit, yfit = _frequency_score(normalized, fs_hz, frequency)
        scores[index] = score
        fits.append((xfit, yfit))
    best_index = int(np.argmin(scores))
    best_frequency = float(grid[best_index])
    best_score = float(scores[best_index])
    # Parabolic refinement around the best grid point.
    if 0 < best_index < count - 1:
        y0, y1, y2 = scores[best_index - 1:best_index + 2]
        denominator = y0 - 2.0 * y1 + y2
        if denominator > 0:
            delta = 0.5 * (y0 - y2) / denominator
            candidate = grid[best_index] + delta * (grid[1] - grid[0])
            candidate = min(high, max(low, float(candidate)))
            candidate_score, xfit, yfit = _frequency_score(
                normalized, fs_hz, candidate)
            if candidate_score < best_score:
                best_frequency, best_score = float(candidate), float(candidate_score)
                fits[best_index] = (xfit, yfit)
    return {
        "frequency_hz": best_frequency,
        "score": best_score,
        "grid_low_hz": float(low),
        "grid_high_hz": float(high),
        "search_span_hz": float(search_span_hz),
        "search_resolution_hz": float(search_resolution_hz),
        "grid_evaluations": count,
        "xfit": fits[best_index][0],
        "yfit": fits[best_index][1],
    }


def fit_stereo(samples, fs_hz, nominal_hz, search_span_hz=5.0,
               search_resolution_hz=0.01, min_reference_amplitude=1e-4,
               max_relative_residual=0.05, clipping_threshold=0.999,
               max_condition=1e8, source=SOURCE):
    """Fit one synchronous (2, 1024) block and report validity explicitly."""
    fs_hz = float(fs_hz)
    nominal_hz = float(nominal_hz)
    if not math.isfinite(fs_hz) or fs_hz <= 0:
        raise PhasorFitError("fs_hz must be positive")
    if not math.isfinite(nominal_hz) or nominal_hz <= 0 or nominal_hz >= fs_hz / 2:
        raise PhasorFitError("nominal_hz must be inside the positive Nyquist band")
    normalized, data_range = _normalise_stereo(samples, clipping_threshold)
    search = search_frequency(
        normalized, fs_hz, nominal_hz, search_span_hz, search_resolution_hz)
    xfit, yfit = search["xfit"], search["yfit"]
    ref_amplitude = float(xfit["amplitude"])
    out_amplitude = float(yfit["amplitude"])
    ratio = None
    gain = None
    phase = None
    reasons = []
    ref_complex = complex(xfit["complex_real"], xfit["complex_imag"])
    out_complex = complex(yfit["complex_real"], yfit["complex_imag"])
    if ref_amplitude > 0:
        ratio = out_complex / ref_complex
        gain = float(20.0 * math.log10(abs(ratio)) if abs(ratio) > 0 else -240.0)
        phase = float(math.degrees(math.atan2(ratio.imag, ratio.real)))
    else:
        reasons.append("REFERENCE_ZERO")
    if ref_amplitude < min_reference_amplitude:
        reasons.append("REFERENCE_WEAK")
    if data_range["clipping_candidate"]:
        reasons.append("CLIPPING_CANDIDATE")
    relative_residual = max(
        xfit["residual_rms"] / max(ref_amplitude, 1e-12),
        yfit["residual_rms"] / max(out_amplitude, 1e-12),
    )
    if rank_bad(xfit) or rank_bad(yfit):
        reasons.append("RANK_DEFICIENT")
    if xfit["condition"] > max_condition or yfit["condition"] > max_condition:
        reasons.append("MATRIX_CONDITION_HIGH")
    if relative_residual > max_relative_residual:
        reasons.append("POOR_FIT_OR_SYNC_UNVERIFIED")
    valid = not reasons and ratio is not None
    return {
        "step": STEP,
        "source": source,
        "channel_assignment": {"left": LEFT_ROLE, "right": RIGHT_ROLE},
        "fs_hz": fs_hz,
        "N": 1024,
        "nominal_hz": nominal_hz,
        "estimated_frequency_hz": search["frequency_hz"],
        "frequency_offset_hz": search["frequency_hz"] - nominal_hz,
        "fit": {
            "x_reference": xfit,
            "y_output": yfit,
            "same_frequency_for_both_channels": True,
            "relative_residual": float(relative_residual),
        },
        "transfer_ratio_raw": {
            "real": float(ratio.real) if ratio is not None else None,
            "imag": float(ratio.imag) if ratio is not None else None,
            "gain_db": gain,
            "phase_deg": phase,
        },
        "reference_amplitude": ref_amplitude,
        "output_amplitude": out_amplitude,
        "data_range": data_range,
        "quality": {
            "valid": bool(valid),
            "reasons": reasons,
            "weak_reference": "REFERENCE_WEAK" in reasons,
            "clipping_candidate": "CLIPPING_CANDIDATE" in reasons,
            "poor_fit_or_sync_unverified": "POOR_FIT_OR_SYNC_UNVERIFIED" in reasons,
            "quality_status": "VALID" if valid else "INVALID",
        },
        "search": {
            "grid_low_hz": search["grid_low_hz"],
            "grid_high_hz": search["grid_high_hz"],
            "search_span_hz": search["search_span_hz"],
            "search_resolution_hz": search["search_resolution_hz"],
            "grid_evaluations": search["grid_evaluations"],
        },
    }


def rank_bad(fit):
    return int(fit["rank"]) < 3


def generate_synthetic_case(case_id, target_hz, frequency_offset_hz,
                            gain_db, phase_deg, reference_amplitude=0.35,
                            dc_left=0.01, dc_right=-0.02,
                            initial_phase=0.37, fs_hz=48000.0,
                            clipping=False):
    """Create a known synchronous block and its coefficient truth."""
    actual_hz = float(target_hz) + float(frequency_offset_hz)
    n = np.arange(1024, dtype=float)
    phase = 2.0 * np.pi * actual_hz * n / fs_hz + float(initial_phase)
    gain = 10.0 ** (float(gain_db) / 20.0)
    phase_rad = math.radians(float(phase_deg))
    x = reference_amplitude * np.cos(phase) + dc_left
    y = reference_amplitude * gain * np.cos(phase + phase_rad) + dc_right
    if clipping:
        x = np.clip(x, -1.0, 1.0)
        y = np.clip(y, -1.0, 1.0)
    float_samples = np.vstack((x, y)).astype(np.float64)
    int_samples = np.clip(
        np.rint(float_samples * FULL_SCALE), -(2 ** 23), 2 ** 23 - 1).astype(np.int32)
    return {
        "case_id": case_id,
        "target_hz": float(target_hz),
        "actual_hz": actual_hz,
        "frequency_offset_hz": float(frequency_offset_hz),
        "gain_db": float(gain_db),
        "phase_deg": float(phase_deg),
        "dc_left": float(dc_left),
        "dc_right": float(dc_right),
        "initial_phase": float(initial_phase),
        "reference_amplitude": float(reference_amplitude),
        "samples_float": float_samples,
        "samples_int32": int_samples,
        "truth_coefficients": {
            "ax": float(reference_amplitude * math.cos(initial_phase)),
            "bx": float(-reference_amplitude * math.sin(initial_phase)),
            "ay": float(reference_amplitude * gain * math.cos(initial_phase + phase_rad)),
            "by": float(-reference_amplitude * gain * math.sin(initial_phase + phase_rad)),
        },
    }


def _fit_case(case, search_resolution_hz=0.002):
    return fit_stereo(
        case["samples_float"], 48000.0, case["target_hz"],
        search_span_hz=5.0, search_resolution_hz=search_resolution_hz,
        source="SYNTHETIC_VALIDATION",
    )


def _synthetic_validation_cases():
    return [
        generate_synthetic_case("gain1_phase0", 1000.0, 0.2, 0.0, 0.0),
        generate_synthetic_case("gain05_phase_minus45", 1592.0, 0.3,
                                -6.020599913279624, -45.0),
        generate_synthetic_case("gain05_phase_minus90", 3000.0, 0.4,
                                -6.020599913279624, -90.0,
                                initial_phase=1.1, dc_left=0.08, dc_right=-0.06),
        generate_synthetic_case("initial_phase_and_dc", 8000.0, 0.4,
                                -20.0, -80.0, reference_amplitude=0.3,
                                dc_left=-0.1, dc_right=0.2, initial_phase=-0.9),
        generate_synthetic_case("weak_reference", 1000.0, 0.2, 0.0, 0.0,
                                reference_amplitude=1e-5),
        generate_synthetic_case("clipping_candidate", 1000.0, 0.2, 0.0, 0.0,
                                reference_amplitude=1.2, dc_left=0.0, dc_right=0.0,
                                clipping=True),
    ]


def build_report(out_dir=None):
    root = Path(__file__).resolve().parents[1]
    out_dir = Path(out_dir or (root / "reports" / "B-X10"))
    out_dir.mkdir(parents=True, exist_ok=True)
    source_root = root / "reports" / "B-X09"
    source = json.loads((source_root / "rc_points.json").read_text(encoding="utf-8"))
    source_results = []
    for point in source["synthetic_points"]:
        archive = np.load(source_root / point["raw_file"], allow_pickle=False)
        result = fit_stereo(
            archive["samples_int32"], float(archive["fs_hz"]), point["target_hz"],
            search_span_hz=5.0, search_resolution_hz=0.01,
            source="SYNTHETIC_BX09")
        source_results.append({
            "case_id": point["case_id"],
            "truth_gain_db": point["truth_complex_transfer_ratio"]["gain_db"],
            "truth_phase_deg": point["truth_complex_transfer_ratio"]["phase_deg"],
            "fit": result,
        })

    validation = []
    for case in _synthetic_validation_cases():
        result = _fit_case(case)
        truth = case["truth_coefficients"]
        xfit = result["fit"]["x_reference"]
        yfit = result["fit"]["y_output"]
        validation.append({
            "case": {key: value for key, value in case.items()
                     if key not in ("samples_float", "samples_int32")},
            "fit": result,
            "coefficient_error": {
                "ax": abs(xfit["a"] - truth["ax"]),
                "bx": abs(xfit["b"] - truth["bx"]),
                "ay": abs(yfit["a"] - truth["ay"]),
                "by": abs(yfit["b"] - truth["by"]),
            },
        })
    payload = {
        "step": STEP,
        "source": "SYNTHETIC_VALIDATION",
        "board_accepted": False,
        "method": "shared-frequency least-squares phasor fit",
        "channel_assignment": {"left": LEFT_ROLE, "right": RIGHT_ROLE},
        "bx09_results": source_results,
        "synthetic_validation": validation,
        "boundaries": [
            "Each fit uses one synchronous (2,1024) block.",
            "Both channels use the same fitted frequency.",
            "No complex FFT phase subtraction or separate capture subtraction is used.",
            "Weak reference, clipping candidate and poor fit are explicitly invalid.",
        ],
    }
    (out_dir / "fit_results.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8")
    with (out_dir / "fit_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "case_id", "truth_gain_db", "truth_phase_deg", "fit_gain_db",
            "fit_phase_deg", "frequency_error_hz", "residual", "valid", "reasons",
        ])
        writer.writeheader()
        for item in source_results:
            fit = item["fit"]
            writer.writerow({
                "case_id": item["case_id"],
                "truth_gain_db": item["truth_gain_db"],
                "truth_phase_deg": item["truth_phase_deg"],
                "fit_gain_db": fit["transfer_ratio_raw"]["gain_db"],
                "fit_phase_deg": fit["transfer_ratio_raw"]["phase_deg"],
                "frequency_error_hz": fit["frequency_offset_hz"],
                "residual": fit["fit"]["relative_residual"],
                "valid": fit["quality"]["valid"],
                "reasons": ";".join(fit["quality"]["reasons"]),
            })
    files = sorted(path for path in out_dir.iterdir() if path.is_file() and path.name != "manifest.json")
    manifest = {
        "schema_version": 1,
        "step": STEP,
        "source": "SYNTHETIC_VALIDATION",
        "files": {
            path.name: {
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
            }
            for path in files
        },
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8")
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).resolve().parents[1] / "reports" / "B-X10")
    args = parser.parse_args(argv)
    payload = build_report(args.out)
    print(json.dumps({
        "step": STEP,
        "out": str(args.out),
        "bx09_cases": len(payload["bx09_results"]),
        "synthetic_validation_cases": len(payload["synthetic_validation"]),
        "valid_bx09": sum(1 for item in payload["bx09_results"] if item["fit"]["quality"]["valid"]),
    }, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
