"""Build the B-X12 measured RC response from synchronous M4 stereo blocks."""

import argparse
import csv
import hashlib
import json
import math
import os
import re
from datetime import date
from pathlib import Path

import numpy as np

from .phasor_fit import fit_stereo
from .rc_model import DESIGN_FREQUENCIES_HZ, cutoff_hz, gain_db, phase_deg, transfer

STEP = "B-X12"
SOURCE = "M4_RAW_STEREO_RC"
B11_CALIBRATION = (
    Path(__file__).resolve().parents[1]
    / "reports" / "B-X11" / "signal_generator_20261101"
    / "channel_calibration.json"
)
NAME_RE = re.compile(r"^b12_f(\d{4})_(cal|val)_(\d{2})\.npy$")
MINUS_3_DB = -3.010299956639812


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def _complex(value):
    return complex(float(value["real"]), float(value["imag"]))


def _gain_db(value):
    return 20.0 * math.log10(abs(value)) if abs(value) > 0 else None


def _phase_deg(value):
    return math.degrees(math.atan2(value.imag, value.real))


def _summarize(values):
    complex_mean = complex(
        float(np.mean([value.real for value in values])),
        float(np.mean([value.imag for value in values])),
    )
    gains = [_gain_db(value) for value in values]
    phases = [_phase_deg(value) for value in values]
    return {
        "complex": {
            "real": float(complex_mean.real),
            "imag": float(complex_mean.imag),
        },
        "gain_db": _gain_db(complex_mean),
        "phase_deg": _phase_deg(complex_mean),
        "gain_std_db": float(np.std(gains, ddof=1)) if len(gains) > 1 else None,
        "phase_std_deg": float(np.std(phases, ddof=1)) if len(phases) > 1 else None,
    }


def discover(dataset_dir):
    groups = {}
    for path in sorted(Path(dataset_dir).glob("b12_f*.npy")):
        match = NAME_RE.match(path.name)
        if not match:
            continue
        frequency = float(int(match.group(1)))
        role = match.group(2)
        groups.setdefault(frequency, {"cal": [], "val": []})[role].append(path)
    missing = [
        frequency for frequency in DESIGN_FREQUENCIES_HZ
        if frequency not in groups
    ]
    malformed = [
        frequency for frequency in DESIGN_FREQUENCIES_HZ
        if frequency in groups
        and (len(groups[frequency]["cal"]) < 3
             or len(groups[frequency]["val"]) < 3)
    ]
    return groups, missing, malformed


def load_b11_calibration(path=B11_CALIBRATION):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("status") != "BOARD_VALIDATED":
        raise ValueError("B-X11 signal-generator calibration is not BOARD_VALIDATED")
    if payload.get("source_profile") != "SIGNAL_GENERATOR":
        raise ValueError("B-X11 calibration source is not a signal generator")
    c0 = {
        float(point["target_hz"]): point["C0"]
        for point in payload["points"]
    }
    missing = [frequency for frequency in DESIGN_FREQUENCIES_HZ
               if frequency not in c0]
    if missing:
        raise ValueError("B-X11 C0 is missing design frequencies: " + str(missing))
    return payload, c0


def _write_source_manifest(dataset_dir, out_dir):
    entries = []
    for path in sorted(item for item in dataset_dir.iterdir() if item.is_file()):
        entries.append({
            "file": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "role": "analysis_block" if NAME_RE.match(path.name) else "metadata",
        })
    payload = {
        "step": STEP,
        "dataset": dataset_dir.name,
        "files": entries,
    }
    (out_dir / "source_dataset_manifest.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8")


def _interpolate_cutoff(frequencies, gains):
    ordered = sorted(zip(frequencies, gains))
    for (f0, g0), (f1, g1) in zip(ordered, ordered[1:]):
        if g0 >= MINUS_3_DB >= g1 and g1 != g0:
            fraction = (MINUS_3_DB - g0) / (g1 - g0)
            return float(math.exp(
                math.log(f0) + fraction * (math.log(f1) - math.log(f0))))
    return None


def _fit_one_pole(frequencies, values):
    frequencies = np.asarray(frequencies, dtype=float)
    values = np.asarray(values, dtype=complex)
    rows = []
    targets = []
    for frequency, value in zip(frequencies, values):
        rows.append([1.0, 0.0, frequency * value.imag])
        targets.append(value.real)
        rows.append([0.0, 1.0, -frequency * value.real])
        targets.append(value.imag)
    coefficients, _, rank, _ = np.linalg.lstsq(
        np.asarray(rows), np.asarray(targets), rcond=None)
    if rank < 3 or coefficients[2] <= 0:
        raise ValueError("one-pole fit did not produce a positive cutoff")
    passband = complex(coefficients[0], coefficients[1])
    cutoff = 1.0 / coefficients[2]
    modeled = passband / (1.0 + 1j * frequencies / cutoff)
    residual = values - modeled
    return {
        "passband": {
            "real": float(passband.real),
            "imag": float(passband.imag),
            "gain_db": _gain_db(passband),
            "phase_deg": _phase_deg(passband),
        },
        "cutoff_hz": float(cutoff),
        "residual_rms": float(np.sqrt(np.mean(np.abs(residual) ** 2))),
        "residual_max": float(np.max(np.abs(residual))),
        "rank": int(rank),
    }


def summarize_complex_ratios(values):
    """Public helper for user-record fitting."""
    return _summarize(values)


def fit_one_pole_model(frequencies, values):
    """Public one-pole fit helper shared by board data and user records."""
    return _fit_one_pole(frequencies, values)


def plot_measurement_summary(out_dir, points, status, fitted_cutoff,
                             r_ohm=978.0, c_f=105.6e-9):
    """Plot a replay point set with the same renderer used by B-X12."""
    return _plot(
        out_dir, points, status, fitted_cutoff,
        r_ohm=float(r_ohm), c_f=float(c_f))


def plot_generic_response(out_dir, points, status):
    """Plot measured amplitude/phase without assuming an RC model."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    frequencies = [point["target_hz"] for point in points]
    gain = [point["H_cal_calibration_mean"]["gain_db"] for point in points]
    phase = [point["H_cal_calibration_mean"]["phase_deg"] for point in points]
    fig, (ax_g, ax_p) = plt.subplots(1, 2, figsize=(14, 5.2), dpi=140)
    ax_g.semilogx(frequencies, gain, "o-", color="#0f766e")
    ax_g.set_xlabel("Frequency (Hz)")
    ax_g.set_ylabel("Gain (dB)")
    ax_g.grid(True, which="both", alpha=0.2)
    ax_p.semilogx(frequencies, phase, "o-", color="#2563eb")
    ax_p.set_xlabel("Frequency (Hz)")
    ax_p.set_ylabel("Phase (deg)")
    ax_p.grid(True, which="both", alpha=0.2)
    fig.suptitle("Generic system frequency response · " + status, fontsize=12)
    fig.tight_layout()
    fig.savefig(out_dir / "gain_phase.png", bbox_inches="tight")
    fig.savefig(out_dir / "gain_phase.svg", bbox_inches="tight")
    plt.close(fig)


def _build_point(frequency, group, fs_hz, c0_by_frequency, block_fits):
    c0 = c0_by_frequency[frequency]
    c0_complex = _complex(c0)
    paths = group["cal"] + group["val"]
    raw_complex = {}
    for path in paths:
        samples = np.load(path, allow_pickle=False)
        fit = fit_stereo(
            samples, fs_hz, frequency, search_span_hz=5.0,
            search_resolution_hz=0.01, source=SOURCE)
        raw = complex(
            fit["transfer_ratio_raw"]["real"],
            fit["transfer_ratio_raw"]["imag"],
        )
        raw_complex[path] = raw
        block_fits.append({
            "target_hz": frequency,
            "file": path.name,
            "role": "cal" if path in group["cal"] else "val",
            "sha256": sha256(path),
            "fit": fit,
            "H_raw": {
                "real": float(raw.real),
                "imag": float(raw.imag),
                "gain_db": _gain_db(raw),
                "phase_deg": _phase_deg(raw),
            },
            "H_cal": {
                "real": float((raw / c0_complex).real),
                "imag": float((raw / c0_complex).imag),
                "gain_db": _gain_db(raw / c0_complex),
                "phase_deg": _phase_deg(raw / c0_complex),
            },
        })
    cal_values = [raw_complex[path] / c0_complex for path in group["cal"]]
    val_values = [raw_complex[path] / c0_complex for path in group["val"]]
    cal_summary = _summarize(cal_values)
    val_summary = _summarize(val_values)
    raw_summary = _summarize([raw_complex[path] for path in group["cal"]])
    theory = complex(transfer(frequency, 978.0, 105.6e-9))
    measured = complex(
        cal_summary["complex"]["real"], cal_summary["complex"]["imag"])
    gain_delta = cal_summary["gain_db"] - _gain_db(theory)
    phase_delta = cal_summary["phase_deg"] - _phase_deg(theory)
    validation_gain_delta = val_summary["gain_db"] - cal_summary["gain_db"]
    validation_phase_delta = val_summary["phase_deg"] - cal_summary["phase_deg"]
    all_valid = all(
        block["fit"]["quality"]["valid"] for block in block_fits
        if block["target_hz"] == frequency
    )
    passed = (
        all_valid
        and abs(validation_gain_delta) <= 0.5
        and abs(validation_phase_delta) <= 2.0
    )
    return {
        "target_hz": frequency,
        "status": "RC_PASS" if passed else "RC_INVALID",
        "all_blocks_valid": all_valid,
        "block_count": len(paths),
        "calibration_files": [path.name for path in group["cal"]],
        "validation_files": [path.name for path in group["val"]],
        "C0": c0,
        "H_raw_cal_mean": raw_summary,
        "H_cal_calibration_mean": cal_summary,
        "H_cal_validation_mean": val_summary,
        "validation_minus_calibration": {
            "gain_db": validation_gain_delta,
            "phase_deg": validation_phase_delta,
        },
        "theory": {
            "real": float(theory.real),
            "imag": float(theory.imag),
            "gain_db": _gain_db(theory),
            "phase_deg": _phase_deg(theory),
        },
        "measured_minus_theory": {
            "gain_db": gain_delta,
            "phase_deg": phase_delta,
            "complex_error": abs(measured - theory),
        },
        "actual_r_ohm": 978.0,
        "actual_c_f": 105.6e-9,
        "theory_cutoff_hz": cutoff_hz(978.0, 105.6e-9),
    }


def _plot(out_dir, points, status, measured_cutoff,
          r_ohm=978.0, c_f=105.6e-9):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    frequencies = [point["target_hz"] for point in points]
    measured_gain = [point["H_cal_calibration_mean"]["gain_db"] for point in points]
    measured_phase = [point["H_cal_calibration_mean"]["phase_deg"] for point in points]
    validation_gain = [point["H_cal_validation_mean"]["gain_db"] for point in points]
    validation_phase = [point["H_cal_validation_mean"]["phase_deg"] for point in points]
    theory_gain = [point["theory"]["gain_db"] for point in points]
    theory_phase = [point["theory"]["phase_deg"] for point in points]
    theory_cutoff = cutoff_hz(r_ohm, c_f)
    plot_low = max(1.0, min(min(frequencies), theory_cutoff) / 3.0)
    plot_high = max(max(frequencies), theory_cutoff) * 1.5
    dense = np.logspace(
        math.log10(plot_low), math.log10(plot_high), 600)
    dense_gain = gain_db(dense, r_ohm, c_f)
    dense_phase = phase_deg(dense, r_ohm, c_f)
    fig, (ax_g, ax_p) = plt.subplots(1, 2, figsize=(14, 5.4), dpi=140)
    ax_g.semilogx(dense, dense_gain, color="#64748b", linewidth=1.5,
                  label="theory R={:.6g} ohm, C={:.6g} nF".format(
                      r_ohm, c_f * 1e9))
    ax_g.semilogx(frequencies, measured_gain, "o-", color="#0f766e",
                  label="measured H_cal (cal blocks)")
    ax_g.semilogx(frequencies, validation_gain, "x", color="#2563eb",
                  label="measured H_cal (validation blocks)")
    ax_g.axhline(MINUS_3_DB, color="#94a3b8", linestyle=":")
    if measured_cutoff:
        ax_g.axvline(measured_cutoff, color="#b45309", linestyle="--",
                     label="fitted one-pole cutoff")
    ax_g.set_xlabel("Frequency (Hz)")
    ax_g.set_ylabel("Gain (dB)")
    ax_g.grid(True, which="both", alpha=0.2)
    ax_g.legend(fontsize=8)
    ax_p.semilogx(dense, dense_phase, color="#64748b", linewidth=1.5)
    ax_p.semilogx(frequencies, measured_phase, "o-", color="#0f766e")
    ax_p.semilogx(frequencies, validation_phase, "x", color="#2563eb")
    ax_p.set_xlabel("Frequency (Hz)")
    ax_p.set_ylabel("Phase (deg)")
    ax_p.grid(True, which="both", alpha=0.2)
    fig.suptitle("B-X12 measured first-order RC response · " + status,
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(out_dir / "magnitude_phase.png", bbox_inches="tight")
    fig.savefig(out_dir / "magnitude_phase.svg", bbox_inches="tight")
    plt.close(fig)


def _write_readme(out_dir, payload):
    point_count = payload["measured_point_count"]
    lines = [
        "# B-X12 实测一阶 RC 幅频/相频",
        "",
        "日期：{}（Asia/Shanghai）。状态：`{}`。".format(
            payload["created"], payload["status"]),
        "",
        "## 条件与接线",
        "",
        "- OWON XDG3122 正弦波信源，沿用 B-X11 信号发生器会话的 `0.2 Vpp` 条件；",
        "- 温度：`25 C`；",
        "- 实测电阻：`978 Ω`；实测电容：`105.6 nF`；",
        "- 左声道：`input_reference`，直接接信号发生器输出；",
        "- 右声道：信号发生器输出经 `978 Ω` 后接 `rc_output`；",
        "- `rc_output` 经 `105.6 nF` 接公共 GND；信号发生器地接公共 GND；",
        "- M4 原始格式 `(2,1024)` int32，`fs={:.9f} Hz`；".format(
            payload["fs_hz"]),
        "- 使用 B-X11 信号发生器 `C0(f)` 计算 `H_cal=H_raw/C0`。",
        "",
        "## 结果",
        "",
        "- 设计点：16；已测点：{}；通过：{}；".format(
            point_count, payload["pass_count"]),
        "- 实测 R/C 理论截止频率：`{:.3f} Hz`；".format(
            payload["theory_cutoff_hz"]),
        "- 一阶复数拟合截止频率：`{:.3f} Hz`；".format(
            payload["one_pole_fit"]["cutoff_hz"]),
        "- 相对实测 R/C 理论值的偏差：`{:+.3f} Hz ({:+.3f}%)`；".format(
            payload["cutoff_delta_hz"], payload["cutoff_delta_percent"]),
        "- 一阶拟合通带复增益：`{:.4f} dB / {:+.4f}°`；".format(
            payload["one_pole_fit"]["passband"]["gain_db"],
            payload["one_pole_fit"]["passband"]["phase_deg"]),
        "- 一阶拟合复残差：RMS `{:.6f}`，最大 `{:.6f}`；".format(
            payload["one_pole_fit"]["residual_rms"],
            payload["one_pole_fit"]["residual_max"]),
        "- 验证块相对校准块的最大偏差：`{:.6f} dB / {:.6f}°`；".format(
            payload["max_validation_gain_delta_db"],
            payload["max_validation_phase_delta_deg"]),
        "- 实测相对无源 RC 理论的最大偏差：`{:.4f} dB / {:.4f}°`；".format(
            payload["max_theory_gain_error_db"],
            payload["max_theory_phase_error_deg"]),
        "- 绝对 -3.0103 dB 幅值交点：`{}`；该值受约 `-0.42 dB` 通带偏置影响，"
        "不作为主截止频率。".format(
            "{:.3f} Hz".format(payload["absolute_minus_3db_hz"])
            if payload["absolute_minus_3db_hz"] is not None
            else "不可用"),
        "- 校准块和验证块校正后响应一致性阈值：`0.5 dB / 2°`。",
        "",
        "逐点结果见 `rc_measured.csv`，完整质量和同步双声道拟合见",
        "`rc_measured.json` 与 `fit_results.json`。",
        "",
        "## 边界",
        "",
        "- 这是实际 RC 板端数据，不是理论图或 SYNTHETIC 数据；",
        "- R/C 为当前接线使用的实测值，元件测量方法未另行记录；",
        "- 音源输出阻抗、板卡输入负载和寄生效应的单独贡献未拆分；",
        "- 展示时 M4 RC 双声道拟合与 PL FFT 频谱模式应明确区分。",
        "",
    ]
    (out_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def build(dataset_dir, out_dir, condition_payload=None):
    from datetime import datetime

    dataset_dir = Path(dataset_dir).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    groups, missing, malformed = discover(dataset_dir)
    b11_payload, c0_by_frequency = load_b11_calibration()
    sample_rate = json.loads(
        (dataset_dir / "sample_rate.json").read_text(encoding="utf-8"))
    overlay = json.loads(
        (dataset_dir / "overlay_hashes.json").read_text(encoding="utf-8"))
    fs_hz = float(sample_rate["fs_estimate_hz"])
    extension_root = out_dir.parents[2]
    dataset_path_from_extension = os.path.relpath(dataset_dir, extension_root)
    points = []
    block_fits = []
    for frequency in DESIGN_FREQUENCIES_HZ:
        if frequency not in groups or frequency in malformed:
            continue
        points.append(_build_point(
            frequency, groups[frequency], fs_hz, c0_by_frequency, block_fits))
    pass_count = sum(point["status"] == "RC_PASS" for point in points)
    absolute_minus_3db = _interpolate_cutoff(
        [point["target_hz"] for point in points],
        [point["H_cal_calibration_mean"]["gain_db"] for point in points],
    )
    measured_complex = [
        complex(
            point["H_cal_calibration_mean"]["complex"]["real"],
            point["H_cal_calibration_mean"]["complex"]["imag"],
        )
        for point in points
    ]
    one_pole_fit = _fit_one_pole(
        [point["target_hz"] for point in points], measured_complex)
    theory_cutoff = cutoff_hz(978.0, 105.6e-9)
    cutoff_delta = one_pole_fit["cutoff_hz"] - theory_cutoff
    max_validation_gain_delta = max(
        abs(point["validation_minus_calibration"]["gain_db"])
        for point in points)
    max_validation_phase_delta = max(
        abs(point["validation_minus_calibration"]["phase_deg"])
        for point in points)
    max_theory_gain_error = max(
        abs(point["measured_minus_theory"]["gain_db"]) for point in points)
    max_theory_phase_error = max(
        abs(point["measured_minus_theory"]["phase_deg"]) for point in points)
    if missing or malformed or pass_count != len(points):
        status = "RC_MEASURED_PARTIAL"
    elif one_pole_fit["residual_rms"] > 0.02:
        status = "RC_MEASURED_PARTIAL"
    else:
        status = "RC_MEASURED"
    conditions = {
        "generator_model": "OWON_XDG3122",
        "generator_waveform": "SINE",
        "generator_amplitude_vpp": "0.2_VPP_ACTUAL_INHERITED_FROM_BX11",
        "generator_output_impedance": "50_OHM_NOMINAL_MODEL_SPEC",
        "temperature": "25_C",
        "wiring": (
            "generator_output -> L(input_reference); "
            "generator_output -> 978_ohm -> R(rc_output); "
            "R(rc_output) -> 105.6_nF -> common_GND; "
            "generator_ground -> common_GND"
        ),
        "channel_assignment": {
            "left": "input_reference",
            "right": "rc_output",
        },
        "actual_r_ohm": 978.0,
        "actual_c_f": 105.6e-9,
        "fs_hz": fs_hz,
        "m4_bit_sha256": overlay["m4.bit"],
        "m4_hwh_sha256": overlay["m4.hwh"],
        "b11_c0_status": b11_payload["status"],
        "b11_c0_source_profile": b11_payload["source_profile"],
        "b11_c0_fs_hz": b11_payload["fs_hz"],
    }
    conditions.update(condition_payload or {})
    payload = {
        "step": STEP,
        "created": date.today().isoformat(),
        "status": status,
        "source": SOURCE,
        "dataset": dataset_dir.name,
        "dataset_path_from_extension": dataset_path_from_extension,
        "fs_hz": fs_hz,
        "design_point_count": len(DESIGN_FREQUENCIES_HZ),
        "measured_point_count": len(points),
        "pass_count": pass_count,
        "missing_frequencies_hz": missing,
        "malformed_frequencies_hz": malformed,
        "theory_cutoff_hz": theory_cutoff,
        "measured_cutoff_hz": one_pole_fit["cutoff_hz"],
        "one_pole_fit": one_pole_fit,
        "cutoff_delta_hz": cutoff_delta,
        "cutoff_delta_percent": 100.0 * cutoff_delta / theory_cutoff,
        "absolute_minus_3db_hz": absolute_minus_3db,
        "valid_block_count": sum(
            block["fit"]["quality"]["valid"] for block in block_fits),
        "block_count": len(block_fits),
        "max_validation_gain_delta_db": max_validation_gain_delta,
        "max_validation_phase_delta_deg": max_validation_phase_delta,
        "max_theory_gain_error_db": max_theory_gain_error,
        "max_theory_phase_error_deg": max_theory_phase_error,
        "conditions": conditions,
        "points": points,
        "notes": [
            "H_cal(f)=H_raw(f)/C0(f) using the B-X11 signal-generator calibration.",
            "Each measured point uses three cal and three independent val blocks.",
            "No measured points are interpolated or replaced with theory.",
        ],
    }
    (out_dir / "rc_measured.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8")
    (out_dir / "fit_results.json").write_text(
        json.dumps({
            "step": STEP,
            "source": SOURCE,
            "fs_hz": fs_hz,
            "blocks": block_fits,
        }, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8")
    with (out_dir / "rc_measured.csv").open(
            "w", newline="", encoding="utf-8") as handle:
        fields = [
            "target_hz", "status", "estimated_frequency_hz",
            "C0_gain_db", "C0_phase_deg",
            "H_cal_gain_db", "H_cal_phase_deg",
            "H_cal_validation_gain_db", "H_cal_validation_phase_deg",
            "validation_minus_cal_gain_db", "validation_minus_cal_phase_deg",
            "theory_gain_db", "theory_phase_deg",
            "measured_minus_theory_gain_db", "measured_minus_theory_phase_deg",
            "complex_error",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for point in points:
            writer.writerow({
                "target_hz": point["target_hz"],
                "status": point["status"],
                "estimated_frequency_hz":
                    block_fits[
                        next(i for i, block in enumerate(block_fits)
                             if block["target_hz"] == point["target_hz"])
                    ]["fit"]["estimated_frequency_hz"],
                "C0_gain_db": point["C0"]["gain_db"],
                "C0_phase_deg": point["C0"]["phase_deg"],
                "H_cal_gain_db": point["H_cal_calibration_mean"]["gain_db"],
                "H_cal_phase_deg": point["H_cal_calibration_mean"]["phase_deg"],
                "H_cal_validation_gain_db":
                    point["H_cal_validation_mean"]["gain_db"],
                "H_cal_validation_phase_deg":
                    point["H_cal_validation_mean"]["phase_deg"],
                "validation_minus_cal_gain_db":
                    point["validation_minus_calibration"]["gain_db"],
                "validation_minus_cal_phase_deg":
                    point["validation_minus_calibration"]["phase_deg"],
                "theory_gain_db": point["theory"]["gain_db"],
                "theory_phase_deg": point["theory"]["phase_deg"],
                "measured_minus_theory_gain_db":
                    point["measured_minus_theory"]["gain_db"],
                "measured_minus_theory_phase_deg":
                    point["measured_minus_theory"]["phase_deg"],
                "complex_error": point["measured_minus_theory"]["complex_error"],
            })
    _write_source_manifest(dataset_dir, out_dir)
    _plot(out_dir, points, status, one_pole_fit["cutoff_hz"])
    _write_readme(out_dir, payload)
    files = sorted(
        path for path in out_dir.iterdir()
        if path.is_file() and path.name != "manifest.json"
    )
    manifest = {
        "schema_version": 1,
        "step": STEP,
        "created": payload["created"],
        "status": status,
        "point_count": len(points),
        "pass_count": pass_count,
        "missing_frequencies_hz": missing,
        "files": {
            path.name: {
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            } for path in files
        },
        "source_dataset": {
            "path": dataset_path_from_extension,
            "block_count": sum(len(group["cal"]) + len(group["val"])
                               for group in groups.values()),
        },
        "generated_at_local": datetime.now().astimezone().isoformat(),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8")
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", required=True)
    parser.add_argument(
        "--out", type=Path,
        default=(
            Path(__file__).resolve().parents[1]
            / "reports" / "B-X12" / "measured_20261101"))
    args = parser.parse_args(argv)
    payload = build(args.dataset_dir, args.out)
    print(json.dumps({
        "step": payload["step"],
        "status": payload["status"],
        "measured_points": payload["measured_point_count"],
        "passed": payload["pass_count"],
        "missing": payload["missing_frequencies_hz"],
        "theory_cutoff_hz": payload["theory_cutoff_hz"],
        "measured_cutoff_hz": payload["measured_cutoff_hz"],
    }, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    raise SystemExit(main())
