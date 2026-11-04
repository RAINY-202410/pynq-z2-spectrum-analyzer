"""B-X09 first-order RC low-pass theory and SYNTHETIC fixtures.

Measured columns are intentionally empty. SYNTHETIC points are kept in a
separate collection and never occupy the measured result columns.
"""

import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np

STEP = "B-X09"
R_OHM = 1000.0
C_F = 100e-9
FS_HZ = 48000.0
N_SAMPLES = 1024
DESIGN_FREQUENCIES_HZ = [
    200.0, 300.0, 500.0, 700.0, 1000.0, 1200.0, 1400.0, 1500.0,
    1592.0, 1700.0, 1900.0, 2200.0, 3000.0, 4000.0, 6000.0, 8000.0,
]


def cutoff_hz(r_ohm=R_OHM, c_f=C_F):
    if r_ohm <= 0 or c_f <= 0:
        raise ValueError("R and C must be positive")
    return 1.0 / (2.0 * math.pi * r_ohm * c_f)


def transfer(frequency_hz, r_ohm=R_OHM, c_f=C_F):
    frequency = np.asarray(frequency_hz, dtype=float)
    if np.any(~np.isfinite(frequency)) or np.any(frequency < 0):
        raise ValueError("frequency must be finite and nonnegative")
    return 1.0 / (1.0 + 1j * 2.0 * np.pi * frequency * r_ohm * c_f)


def gain_db(frequency_hz, r_ohm=R_OHM, c_f=C_F):
    return 20.0 * np.log10(np.abs(transfer(frequency_hz, r_ohm, c_f)))


def phase_deg(frequency_hz, r_ohm=R_OHM, c_f=C_F):
    return np.angle(transfer(frequency_hz, r_ohm, c_f), deg=True)


def measured_point_template(target_hz, r_ohm=R_OHM, c_f=C_F):
    """One design point with measured fields deliberately blank."""
    return {
        "target_hz": float(target_hz),
        "estimated_actual_hz": None,
        "fs_hz": None,
        "frame_id": None,
        "raw_file": None,
        "channel_assignment": None,
        "straight_through_calibration": None,
        "complex_transfer_ratio": None,
        "gain_db": None,
        "phase_deg": None,
        "quality_status": "NOT_MEASURED",
        "actual_r_ohm": None,
        "actual_c_f": None,
        "source": "DESIGN_ONLY",
        "theory_gain_db": float(gain_db(target_hz, r_ohm, c_f)),
        "theory_phase_deg": float(phase_deg(target_hz, r_ohm, c_f)),
    }


def synthetic_specs():
    return [
        {
            "case_id": "synth_flat_offset_dc",
            "target_hz": 1000.0,
            "frequency_offset_hz": 0.2,
            "gain_db": 0.0,
            "phase_deg": 0.0,
            "dc_left": 0.01,
            "dc_right": -0.02,
            "reference_amplitude": 0.35,
            "quality_status": "VALID_SYNTHETIC",
        },
        {
            "case_id": "synth_cutoff",
            "target_hz": cutoff_hz(),
            "frequency_offset_hz": 0.3,
            "gain_db": -6.020599913279624,
            "phase_deg": -45.0,
            "dc_left": 0.05,
            "dc_right": -0.04,
            "reference_amplitude": 0.35,
            "quality_status": "VALID_SYNTHETIC",
        },
        {
            "case_id": "synth_8k",
            "target_hz": 8000.0,
            "frequency_offset_hz": 0.4,
            "gain_db": -20.0,
            "phase_deg": -80.0,
            "dc_left": -0.10,
            "dc_right": 0.20,
            "reference_amplitude": 0.30,
            "quality_status": "VALID_SYNTHETIC",
        },
        {
            "case_id": "synth_weak_reference",
            "target_hz": 1000.0,
            "frequency_offset_hz": 0.2,
            "gain_db": 0.0,
            "phase_deg": 0.0,
            "dc_left": 0.0,
            "dc_right": 0.0,
            "reference_amplitude": 1e-5,
            "quality_status": "REFERENCE_TOO_WEAK_SYNTHETIC",
        },
    ]


def _make_stereo(spec):
    actual_hz = spec["target_hz"] + spec["frequency_offset_hz"]
    n = np.arange(N_SAMPLES, dtype=float)
    phase0 = 0.37
    phase_rad = math.radians(spec["phase_deg"])
    gain = 10.0 ** (spec["gain_db"] / 20.0)
    x = spec["reference_amplitude"] * np.cos(2.0 * np.pi * actual_hz * n / FS_HZ + phase0) + spec["dc_left"]
    y = spec["reference_amplitude"] * gain * np.cos(
        2.0 * np.pi * actual_hz * n / FS_HZ + phase0 + phase_rad) + spec["dc_right"]
    float_samples = np.vstack((x, y)).astype(np.float64)
    int_samples = np.clip(np.rint(float_samples * (2 ** 23)), -(2 ** 23), 2 ** 23 - 1).astype(np.int32)
    ratio = gain * np.exp(1j * phase_rad)
    return actual_hz, float_samples, int_samples, ratio


def synthetic_points(out_dir):
    out_dir = Path(out_dir)
    synthetic_dir = out_dir / "synthetic"
    synthetic_dir.mkdir(parents=True, exist_ok=True)
    points = []
    for index, spec in enumerate(synthetic_specs(), 1):
        actual_hz, float_samples, int_samples, ratio = _make_stereo(spec)
        file_name = "rc_{:02d}_{}.npz".format(index, spec["case_id"])
        relative = "synthetic/" + file_name
        path = out_dir / relative
        np.savez_compressed(
            path,
            samples_int32=int_samples,
            samples_float=float_samples,
            fs_hz=np.float64(FS_HZ),
            N=np.int64(N_SAMPLES),
            target_frequency_hz=np.float64(spec["target_hz"]),
            actual_frequency_hz=np.float64(actual_hz),
            frequency_offset_hz=np.float64(spec["frequency_offset_hz"]),
            truth_gain_db=np.float64(spec["gain_db"]),
            truth_phase_deg=np.float64(spec["phase_deg"]),
            truth_transfer_real=np.float64(ratio.real),
            truth_transfer_imag=np.float64(ratio.imag),
            reference_amplitude=np.float64(spec["reference_amplitude"]),
            dc_left=np.float64(spec["dc_left"]),
            dc_right=np.float64(spec["dc_right"]),
            source=np.array("SYNTHETIC"),
        )
        points.append({
            "case_id": spec["case_id"],
            "target_hz": float(spec["target_hz"]),
            "estimated_actual_hz": float(actual_hz),
            "fs_hz": FS_HZ,
            "frame_id": "SYNTHETIC_{:02d}".format(index),
            "raw_file": relative,
            "channel_assignment": {
                "left": "input_reference",
                "right": "rc_output",
            },
            "straight_through_calibration": None,
            "truth_complex_transfer_ratio": {
                "real": float(ratio.real),
                "imag": float(ratio.imag),
                "gain_db": float(spec["gain_db"]),
                "phase_deg": float(spec["phase_deg"]),
            },
            "gain_db": None,
            "phase_deg": None,
            "quality_status": spec["quality_status"],
            "actual_r_ohm": R_OHM,
            "actual_c_f": C_F,
            "source": "SYNTHETIC",
            "note": "Known synthetic truth; not a measured RC result.",
        })
    return points


def write_point_tables(out_dir, rc_points, synthetic):
    out_dir = Path(out_dir)
    with (out_dir / "rc_points.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "target_hz", "theory_gain_db", "theory_phase_deg",
            "estimated_actual_hz", "fs_hz", "frame_id", "raw_file",
            "gain_db", "phase_deg", "quality_status", "source",
        ])
        writer.writeheader()
        for point in rc_points:
            writer.writerow({key: ("" if point[key] is None else point[key]) for key in writer.fieldnames})
    with (out_dir / "synthetic_points.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "case_id", "target_hz", "estimated_actual_hz", "frequency_offset_hz",
            "truth_gain_db", "truth_phase_deg", "dc_left", "dc_right",
            "reference_amplitude", "raw_file", "quality_status", "source",
        ])
        writer.writeheader()
        for point in synthetic:
            writer.writerow({
                "case_id": point["case_id"],
                "target_hz": point["target_hz"],
                "estimated_actual_hz": point["estimated_actual_hz"],
                "frequency_offset_hz": point["estimated_actual_hz"] - point["target_hz"],
                "truth_gain_db": point["truth_complex_transfer_ratio"]["gain_db"],
                "truth_phase_deg": point["truth_complex_transfer_ratio"]["phase_deg"],
                "dc_left": point["dc_left"] if "dc_left" in point else "",
                "dc_right": point["dc_right"] if "dc_right" in point else "",
                "reference_amplitude": point["reference_amplitude"] if "reference_amplitude" in point else "",
                "raw_file": point["raw_file"],
                "quality_status": point["quality_status"],
                "source": "SYNTHETIC",
            })


def plot_theory(out_dir, rc_points, synthetic):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir = Path(out_dir)
    freq = np.logspace(2, 4, 500)
    gain = gain_db(freq)
    phase = phase_deg(freq)
    fc = cutoff_hz()
    fig, ax_gain = plt.subplots(figsize=(12, 5.6), dpi=140)
    ax_phase = ax_gain.twinx()
    ax_gain.semilogx(freq, gain, color="#0f766e", linewidth=1.8, label="Theory gain")
    ax_phase.semilogx(freq, phase, color="#2563eb", linewidth=1.5, label="Theory phase")
    design_f = [item["target_hz"] for item in rc_points]
    design_g = [item["theory_gain_db"] for item in rc_points]
    design_p = [item["theory_phase_deg"] for item in rc_points]
    ax_gain.scatter(design_f, design_g, color="#0f766e", marker="o", s=14,
                    facecolors="none", label="Design frequencies")
    ax_phase.scatter(design_f, design_p, color="#2563eb", marker="x", s=16,
                     label="Design frequencies (phase)")
    if synthetic:
        ax_gain.scatter([item["estimated_actual_hz"] for item in synthetic],
                        [item["truth_complex_transfer_ratio"]["gain_db"] for item in synthetic],
                        color="#f59e0b", marker="D", s=34, label="SYNTHETIC truth")
        ax_phase.scatter([item["estimated_actual_hz"] for item in synthetic],
                         [item["truth_complex_transfer_ratio"]["phase_deg"] for item in synthetic],
                         color="#f59e0b", marker="s", s=26, label="SYNTHETIC truth (phase)")
    ax_gain.axvline(fc, color="#94a3b8", linestyle=":", linewidth=1)
    ax_gain.axhline(-3.010299956639812, color="#94a3b8", linestyle=":", linewidth=1)
    ax_phase.axhline(-45.0, color="#94a3b8", linestyle=":", linewidth=1)
    ax_gain.set_xlabel("Frequency (Hz)")
    ax_gain.set_ylabel("Gain (dB)", color="#0f766e")
    ax_phase.set_ylabel("Phase (deg)", color="#2563eb")
    ax_gain.grid(True, which="both", alpha=0.2)
    ax_gain.set_title("B-X09 first-order RC low-pass theory · measured columns intentionally empty")
    lines1, labels1 = ax_gain.get_legend_handles_labels()
    lines2, labels2 = ax_phase.get_legend_handles_labels()
    ax_gain.legend(lines1 + lines2, labels1 + labels2, loc="lower left", fontsize=8)
    fig.text(
        0.01, 0.01,
        "R=1 kOhm, C=100 nF, fc={:.6f} Hz; synthetic markers are not measurements".format(fc),
        fontsize=8, color="#475569")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    png = out_dir / "theory.png"
    fig.savefig(png, bbox_inches="tight")
    fig.savefig(out_dir / "theory.svg", bbox_inches="tight")
    plt.close(fig)
    return png


def build_baseline(out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fc = cutoff_hz()
    rc_points = [measured_point_template(freq) for freq in DESIGN_FREQUENCIES_HZ]
    synthetic = synthetic_points(out_dir)
    # Copy DC/amplitude truth into synthetic rows without putting it in measured cells.
    specs = {item["case_id"]: item for item in synthetic_specs()}
    for point in synthetic:
        spec = specs[point["case_id"]]
        point["frequency_offset_hz"] = spec["frequency_offset_hz"]
        point["dc_left"] = spec["dc_left"]
        point["dc_right"] = spec["dc_right"]
        point["reference_amplitude"] = spec["reference_amplitude"]
    payload = {
        "step": STEP,
        "experiment": {
            "circuit": "first_order_rc_lowpass",
            "R_ohm": R_OHM,
            "C_f": C_F,
            "fc_hz": fc,
            "fs_hz": FS_HZ,
            "N": N_SAMPLES,
            "formula": "H(f)=1/(1+j*2*pi*f*R*C)",
            "measured_source": "NONE_IN_B_X09",
            "synthetic_source": "SYNTHETIC",
            "board_accepted": False,
            "amplitude_calibrated": False,
            "scipy_note": "If cross-checking with scipy.signal.freqs, pass angular frequency w=2*pi*f.",
        },
        "rc_points": rc_points,
        "synthetic_points": synthetic,
        "notes": [
            "Measured fields stay blank until real RC capture/calibration exists.",
            "SYNTHETIC points use a separate collection and legend.",
            "Design frequencies are not a measured bandwidth claim.",
            "Theoretical fc magnitude is about -3.0103 dB and phase -45 degrees.",
        ],
    }
    (out_dir / "rc_points.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8")
    write_point_tables(out_dir, rc_points, synthetic)
    png = plot_theory(out_dir, rc_points, synthetic)
    files = sorted(path for path in out_dir.rglob("*") if path.is_file() and path.name != "manifest.json")
    manifest = {
        "schema_version": 1,
        "step": STEP,
        "source": "THEORY_AND_SYNTHETIC",
        "experiment": payload["experiment"],
        "files": {
            path.relative_to(out_dir).as_posix(): {
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
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "reports" / "B-X09")
    args = parser.parse_args(argv)
    payload = build_baseline(args.out)
    print(json.dumps({
        "step": STEP,
        "out": str(args.out),
        "fc_hz": payload["experiment"]["fc_hz"],
        "design_points": len(payload["rc_points"]),
        "synthetic_cases": len(payload["synthetic_points"]),
        "measured_points": sum(item["quality_status"] != "NOT_MEASURED" for item in payload["rc_points"]),
    }, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
