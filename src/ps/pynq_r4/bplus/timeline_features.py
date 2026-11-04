"""B-X06 signal trend and threshold-event analysis.

The input is the B-X02 metric timeline (one row per frames.jsonl row). A peak
is selected only from the locally saved peak list (at most three peaks); when
a requested target band has no saved peak, the point is missing rather than
being reconstructed from scalar metrics.
"""

import argparse
import copy
import json
import math
from pathlib import Path

STEP = "B-X06"
EXTENSION_ROOT = Path(__file__).resolve().parent
DEFAULT_TIMELINE = EXTENSION_ROOT / "reports" / "B-X02" / "metric_timeline.jsonl"
DEFAULT_OUT = EXTENSION_ROOT / "reports" / "B-X06"
DEFAULT_MAX_GAP_S = 2.0


class TimelineFeatureError(ValueError):
    """Raised for invalid trend input or rule configuration."""


def _finite(value, name):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TimelineFeatureError(name + " must be numeric") from exc
    if not math.isfinite(number):
        raise TimelineFeatureError(name + " must be finite")
    return number


def _dbfs(linear):
    linear = _finite(linear, "linear amplitude")
    if linear < 0:
        raise TimelineFeatureError("linear amplitude must be nonnegative")
    return 20.0 * math.log10(max(linear, 1e-12))


def load_metric_records(path=DEFAULT_TIMELINE):
    path = Path(path)
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
            except ValueError as exc:
                raise TimelineFeatureError("invalid metric JSON at line {}".format(line_number)) from exc
            if not isinstance(record, dict) or record.get("record_type") != "metric":
                raise TimelineFeatureError("line {} is not a metric record".format(line_number))
            records.append(record)
    if not records:
        raise TimelineFeatureError("metric timeline is empty")
    return records


def _valid_peaks(record):
    metrics = record.get("metrics")
    if not isinstance(metrics, dict):
        return []
    peaks = metrics.get("peaks")
    if not isinstance(peaks, list):
        return []
    valid = []
    for peak in peaks:
        if not isinstance(peak, dict):
            continue
        try:
            frequency = _finite(peak["frequency_hz"], "peak frequency_hz")
            amplitude = _finite(peak["amplitude"], "peak amplitude")
            bin_index = int(peak["bin"])
        except (KeyError, TypeError, ValueError):
            continue
        if frequency < 0 or amplitude < 0:
            continue
        item = dict(peak)
        item["bin"] = bin_index
        item["frequency_hz"] = frequency
        item["amplitude"] = amplitude
        if "dbfs" in item:
            try:
                item["dbfs"] = _finite(item["dbfs"], "peak dbfs")
            except TimelineFeatureError:
                item["dbfs"] = _dbfs(amplitude)
        else:
            item["dbfs"] = _dbfs(amplitude)
        item["estimated_frequency_hz"] = _finite(
            item.get("estimated_frequency_hz", frequency), "estimated_frequency_hz")
        item["interpolated"] = bool(item.get("interpolated", False))
        valid.append(item)
    return valid


def select_peak(record, mode="max_peak", target_hz=None, bandwidth_hz=None):
    """Select one saved peak, never synthesize a peak from scalar metrics."""
    peaks = _valid_peaks(record)
    if mode == "max_peak":
        selected = max(peaks, key=lambda item: item["amplitude"]) if peaks else None
        missing_reason = "本帧没有已保存的局部峰" if selected is None else None
        band = None
    elif mode == "target_band":
        if target_hz is None or bandwidth_hz is None:
            raise TimelineFeatureError("target_band requires target_hz and bandwidth_hz")
        target = _finite(target_hz, "target_hz")
        width = _finite(bandwidth_hz, "bandwidth_hz")
        if width <= 0:
            raise TimelineFeatureError("bandwidth_hz must be positive")
        low, high = target - width / 2.0, target + width / 2.0
        in_band = [item for item in peaks if low <= item["frequency_hz"] <= high]
        selected = max(in_band, key=lambda item: item["amplitude"]) if in_band else None
        missing_reason = ("目标频段内没有已保存的局部峰；不从标量日志重建频谱"
                          if selected is None else None)
        band = {"low_hz": low, "high_hz": high}
    else:
        raise TimelineFeatureError("mode must be max_peak or target_band")

    metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
    tone_checks_passed = metrics.get("tone_checks_passed")
    if selected is None:
        return {
            "valid": False,
            "mode": mode,
            "band": band,
            "missing_reason": missing_reason,
            "peak_count": len(peaks),
            "quality_hints": [],
        }

    neighbor_count = sum(
        1 for item in peaks
        if item is not selected and abs(item["bin"] - selected["bin"]) <= 3
    )
    hints = []
    if selected["interpolated"]:
        hints.append("辅助峰值插值，estimated_frequency_hz 仅为估计值")
    if neighbor_count:
        hints.append("附近存在其他局部峰，辅助估计需复核")
    if selected["dbfs"] < -50:
        hints.append("弱信号，频率估计仅作辅助")
    if tone_checks_passed is False:
        hints.append("原始帧质量状态未通过")
    return {
        "valid": True,
        "mode": mode,
        "band": band,
        "bin": selected["bin"],
        "discrete_frequency_hz": selected["frequency_hz"],
        "estimated_frequency_hz": selected["estimated_frequency_hz"],
        "interpolated": selected["interpolated"],
        "linear_amplitude": selected["amplitude"],
        "dbfs": selected["dbfs"],
        "peak_count": len(peaks),
        "neighbor_peak_count": neighbor_count,
        "tone_checks_passed": tone_checks_passed,
        "quality_hints": hints,
        "missing_reason": None,
    }


def build_trend(records, run_id, mode="max_peak", target_hz=None,
                bandwidth_hz=None, max_gap_s=DEFAULT_MAX_GAP_S):
    """Build a per-run trend from saved metric rows."""
    selected_records = [item for item in records if item.get("run_id") == run_id]
    if not selected_records:
        raise TimelineFeatureError("no metric rows for run " + str(run_id))
    if max_gap_s <= 0:
        raise TimelineFeatureError("max_gap_s must be positive")
    points = []
    previous_elapsed = None
    for record in selected_records:
        elapsed = _finite(record.get("elapsed_s"), "elapsed_s")
        if previous_elapsed is not None and elapsed < previous_elapsed:
            raise TimelineFeatureError("metric rows are not in elapsed_s order")
        gap = None if previous_elapsed is None else elapsed - previous_elapsed
        continuity_gap = bool(gap is not None and gap > max_gap_s)
        selected = select_peak(record, mode, target_hz, bandwidth_hz)
        metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
        point = {
            "run_id": run_id,
            "frame_id": record.get("frame_id"),
            "sequence": record.get("sequence"),
            "elapsed_s": elapsed,
            "window": record.get("window"),
            "fs_hz": record.get("fs_hz"),
            "N": record.get("N"),
            "mode": mode,
            "target_hz": target_hz,
            "bandwidth_hz": bandwidth_hz,
            "valid": selected["valid"],
            "bin": selected.get("bin"),
            "discrete_frequency_hz": selected.get("discrete_frequency_hz"),
            "estimated_frequency_hz": selected.get("estimated_frequency_hz"),
            "measurement_frequency_hz": selected.get("estimated_frequency_hz")
            if selected.get("valid") else None,
            "linear_amplitude": selected.get("linear_amplitude"),
            "dbfs": selected.get("dbfs"),
            "interpolated": selected.get("interpolated", False),
            "tone_checks_passed": selected.get("tone_checks_passed", metrics.get("tone_checks_passed")),
            "peak_count": selected.get("peak_count", 0),
            "neighbor_peak_count": selected.get("neighbor_peak_count", 0),
            "quality_hints": selected.get("quality_hints", []),
            "missing_reason": selected.get("missing_reason"),
            "band": selected.get("band"),
            "gap_before_s": gap,
            "continuity_gap": continuity_gap,
        }
        points.append(point)
        previous_elapsed = elapsed
    gaps = [item for item in points if item["continuity_gap"]]
    return {
        "run_id": run_id,
        "label": selected_records[0].get("run_label"),
        "mode": mode,
        "target_hz": target_hz,
        "bandwidth_hz": bandwidth_hz,
        "max_gap_s": max_gap_s,
        "point_count": len(points),
        "valid_count": sum(1 for item in points if item["valid"]),
        "missing_count": sum(1 for item in points if not item["valid"]),
        "continuity_gap_count": len(gaps),
        "points": points,
    }


DEFAULT_RULES = {
    "amplitude_below": {
        "enabled": True,
        "threshold_dbfs": -60.0,
        "hysteresis_db": 2.0,
        "min_consecutive": 3,
        "recover_consecutive": 3,
    },
    "frequency_outside": {
        "enabled": False,
        "min_hz": None,
        "max_hz": None,
        "hysteresis_hz": 0.0,
        "min_consecutive": 3,
        "recover_consecutive": 3,
    },
    "missing_peak": {
        "enabled": True,
        "min_consecutive": 3,
        "recover_consecutive": 2,
    },
}


def merge_rules(rules=None):
    effective = copy.deepcopy(DEFAULT_RULES)
    if rules:
        for key, value in rules.items():
            effective.setdefault(key, {}).update(value)
    return effective


def _event_record(rule_id, rule, source, points, start, end, closure, open_at_end):
    event = {
        "event_id": "{}:{}:{}:{}:{}".format(
            source, points[0]["run_id"], rule_id, start.get("frame_id"), end.get("frame_id")),
        "rule": rule_id,
        "source": source,
        "synthetic": source == "SYNTHETIC_TEST",
        "board_fault": False,
        "start_frame_id": start.get("frame_id"),
        "end_frame_id": end.get("frame_id"),
        "start_elapsed_s": start.get("elapsed_s"),
        "end_elapsed_s": end.get("elapsed_s"),
        "frame_ids": [item.get("frame_id") for item in points],
        "point_count": len(points),
        "continuity_verified": True,
        "closure": closure,
        "open_at_end": bool(open_at_end),
        "rule_thresholds": copy.deepcopy(rule),
    }
    if rule_id == "amplitude_below":
        event["min_dbfs"] = min(item["dbfs"] for item in points if item.get("dbfs") is not None)
        event["max_dbfs"] = max(item["dbfs"] for item in points if item.get("dbfs") is not None)
        event["reason"] = "连续帧峰值 dBFS 低于阈值；事件只表示观测幅值条件，不确认断线"
    elif rule_id == "frequency_outside":
        values = [item["measurement_frequency_hz"] for item in points
                  if item.get("measurement_frequency_hz") is not None]
        event["min_frequency_hz"] = min(values) if values else None
        event["max_frequency_hz"] = max(values) if values else None
        event["reason"] = "连续帧峰值估计频率超出设定范围；不确认硬件故障"
    else:
        event["reason"] = "连续帧目标频段没有已保存局部峰；不从标量日志重建频谱"
    hints = sorted({hint for item in points for hint in item.get("quality_hints", [])})
    event["quality_hints"] = hints
    return event


def _detect_rule(points, rule_id, rule, source, applicable, enter, exit_condition):
    events = []
    active = None
    entering = []
    recovery = 0
    min_enter = int(rule["min_consecutive"])
    min_recover = int(rule["recover_consecutive"])
    if min_enter < 1 or min_recover < 1:
        raise TimelineFeatureError("consecutive counts must be positive")

    def close(active_state, closure, open_at_end=False):
        if active_state and active_state["points"]:
            event = _event_record(
                rule_id, rule, source, active_state["points"],
                active_state["points"][0], active_state["points"][-1],
                closure, open_at_end)
            events.append(event)

    for point in points:
        if point.get("continuity_gap"):
            if active is not None:
                close(active, "gap")
            active = None
            entering = []
            recovery = 0
        if applicable is not None and not applicable(point):
            if active is not None:
                close(active, "not_applicable")
            active = None
            entering = []
            recovery = 0
            continue
        if active is None:
            if enter(point):
                entering.append(point)
                if len(entering) >= min_enter:
                    active = {"points": list(entering)}
                    entering = []
            else:
                entering = []
        else:
            if exit_condition(point):
                recovery += 1
                if recovery >= min_recover:
                    close(active, "recovered")
                    active = None
                    recovery = 0
                    entering = []
            else:
                recovery = 0
                active["points"].append(point)
    if active is not None:
        close(active, "open_at_end", open_at_end=True)
    return events


def detect_events(points, rules=None, source="REPLAY"):
    """Detect configured events with consecutive-frame and gap handling."""
    effective = merge_rules(rules)
    events = []

    amplitude = effective["amplitude_below"]
    if amplitude.get("enabled"):
        threshold = _finite(amplitude["threshold_dbfs"], "threshold_dbfs")
        hysteresis = _finite(amplitude.get("hysteresis_db", 0), "hysteresis_db")
        events.extend(_detect_rule(
            points, "amplitude_below", amplitude, source,
            applicable=lambda point: point.get("valid") and point.get("dbfs") is not None,
            enter=lambda point: point["dbfs"] < threshold,
            exit_condition=lambda point: point["dbfs"] >= threshold + hysteresis,
        ))

    frequency = effective["frequency_outside"]
    if frequency.get("enabled"):
        low = _finite(frequency["min_hz"], "min_hz")
        high = _finite(frequency["max_hz"], "max_hz")
        if low >= high:
            raise TimelineFeatureError("min_hz must be below max_hz")
        hysteresis = _finite(frequency.get("hysteresis_hz", 0), "hysteresis_hz")
        events.extend(_detect_rule(
            points, "frequency_outside", frequency, source,
            applicable=lambda point: point.get("valid") and point.get("measurement_frequency_hz") is not None,
            enter=lambda point: not (low <= point["measurement_frequency_hz"] <= high),
            exit_condition=lambda point: low + hysteresis <= point["measurement_frequency_hz"] <= high - hysteresis,
        ))

    missing = effective["missing_peak"]
    if missing.get("enabled"):
        events.extend(_detect_rule(
            points, "missing_peak", missing, source,
            applicable=None,
            enter=lambda point: not point.get("valid"),
            exit_condition=lambda point: point.get("valid"),
        ))

    events.sort(key=lambda item: (item["start_elapsed_s"], item["rule"]))
    return events


def analyze(records, run_id, mode="max_peak", target_hz=None, bandwidth_hz=None,
            max_gap_s=DEFAULT_MAX_GAP_S, rules=None):
    trend = build_trend(records, run_id, mode, target_hz, bandwidth_hz, max_gap_s)
    effective_rules = merge_rules(rules)
    events = detect_events(trend["points"], effective_rules, source="REPLAY")
    return {
        "run_id": run_id,
        "label": trend["label"],
        "mode": mode,
        "target_hz": target_hz,
        "bandwidth_hz": bandwidth_hz,
        "max_gap_s": max_gap_s,
        "point_count": trend["point_count"],
        "valid_count": trend["valid_count"],
        "missing_count": trend["missing_count"],
        "continuity_gap_count": trend["continuity_gap_count"],
        "rules": effective_rules,
        "points": trend["points"],
        "events": events,
    }


def _synthetic_point(frame_id, elapsed, dbfs, frequency, valid=True, gap=False):
    return {
        "run_id": "SYNTHETIC_BX06",
        "frame_id": frame_id,
        "sequence": 1000 + frame_id,
        "elapsed_s": elapsed,
        "window": "hann",
        "fs_hz": 48000.0,
        "N": 1024,
        "mode": "target_band",
        "target_hz": 1000.0,
        "bandwidth_hz": 200.0,
        "valid": valid,
        "bin": None if frequency is None else 21,
        "discrete_frequency_hz": frequency,
        "estimated_frequency_hz": frequency,
        "measurement_frequency_hz": frequency,
        "linear_amplitude": None if dbfs is None else 10 ** (dbfs / 20),
        "dbfs": dbfs,
        "interpolated": False,
        "tone_checks_passed": None,
        "peak_count": 0 if not valid else 1,
        "neighbor_peak_count": 0,
        "quality_hints": [],
        "missing_reason": "SYNTHETIC_TARGET_MISSING" if not valid else None,
        "band": {"low_hz": 900.0, "high_hz": 1100.0},
        "gap_before_s": 10.0 if gap else 0.2,
        "continuity_gap": gap,
    }


def synthetic_validation():
    points = [
        _synthetic_point(1, 0.0, -50.0, 1000.0),
        _synthetic_point(2, 0.2, -62.0, 1000.0),
        _synthetic_point(3, 0.4, -64.0, 1000.0),
        _synthetic_point(4, 0.6, -55.0, 1000.0),
        _synthetic_point(5, 0.8, -57.0, 1000.0),
        _synthetic_point(6, 1.0, -50.0, 1000.0),
        _synthetic_point(7, 1.2, -50.0, 1300.0),
        _synthetic_point(8, 1.4, -50.0, 1300.0),
        _synthetic_point(9, 1.6, -50.0, 1000.0),
        _synthetic_point(10, 1.8, -50.0, 1000.0),
        _synthetic_point(11, 2.0, None, None, valid=False),
        _synthetic_point(12, 2.2, None, None, valid=False),
        _synthetic_point(13, 2.4, None, None, valid=False),
        _synthetic_point(14, 2.6, -50.0, 1000.0),
        _synthetic_point(15, 2.8, -50.0, 1000.0),
        _synthetic_point(16, 12.8, -50.0, 1000.0, gap=True),
        _synthetic_point(17, 13.0, -65.0, 1000.0),
        _synthetic_point(18, 13.2, -65.0, 1000.0),
    ]
    rules = copy.deepcopy(DEFAULT_RULES)
    rules["amplitude_below"].update(min_consecutive=2, recover_consecutive=2,
                                    threshold_dbfs=-60.0, hysteresis_db=2.0)
    rules["frequency_outside"].update(enabled=True, min_hz=900.0, max_hz=1100.0,
                                      hysteresis_hz=10.0, min_consecutive=2,
                                      recover_consecutive=2)
    rules["missing_peak"].update(min_consecutive=2, recover_consecutive=2)
    return {
        "source": "SYNTHETIC_TEST",
        "board_fault": False,
        "rules": rules,
        "points": points,
        "events": detect_events(points, rules, source="SYNTHETIC_TEST"),
    }


def _plot_trend(trend, events, output_path, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    points = trend["points"]
    time = [item["elapsed_s"] for item in points]
    discrete = [item["discrete_frequency_hz"] if item["valid"] else float("nan") for item in points]
    estimated = [item["estimated_frequency_hz"] if item["valid"] else float("nan") for item in points]
    dbfs = [item["dbfs"] if item["valid"] else float("nan") for item in points]
    fig, (ax_f, ax_a) = plt.subplots(2, 1, figsize=(13, 8), sharex=True, dpi=140)
    ax_f.plot(time, discrete, color="#94a3b8", linewidth=1.0, label="discrete peak bin")
    ax_f.plot(time, estimated, color="#2563eb", linewidth=1.4, label="estimated peak frequency")
    if trend.get("target_hz") is not None:
        band = trend.get("bandwidth_hz") or 0
        ax_f.axhline(trend["target_hz"], color="#0f766e", linestyle=":", linewidth=1, label="target")
        if band:
            ax_f.axhline(trend["target_hz"] - band / 2, color="#0f766e", linestyle="--", linewidth=0.8)
            ax_f.axhline(trend["target_hz"] + band / 2, color="#0f766e", linestyle="--", linewidth=0.8)
    missing_t = [item["elapsed_s"] for item in points if not item["valid"]]
    missing_y = [trend.get("target_hz") or 0 for _ in missing_t]
    if missing_t:
        ax_f.scatter(missing_t, missing_y, marker="x", color="#fb7185", s=24, label="missing saved peak")
    ax_f.set_ylabel("Frequency (Hz)")
    ax_f.grid(True, alpha=0.22)
    ax_f.legend(loc="upper right", fontsize=8)
    ax_a.plot(time, dbfs, color="#0f766e", linewidth=1.2, label="peak dBFS")
    if not any(math.isfinite(value) for value in dbfs):
        ax_a.text(
            0.5, 0.5,
            "No saved peak in the selected band\nNo amplitude values to plot",
            transform=ax_a.transAxes, ha="center", va="center",
            color="#94a3b8", fontsize=11)
        ax_a.set_ylim(-1, 1)
    for event in events:
        if event["rule"] == "amplitude_below":
            ax_a.axvspan(event["start_elapsed_s"], event["end_elapsed_s"], color="#fb7185", alpha=0.12)
        elif event["rule"] in ("frequency_outside", "missing_peak"):
            ax_f.axvspan(event["start_elapsed_s"], event["end_elapsed_s"], color="#fbbf24", alpha=0.10)
    ax_a.set_xlabel("Original elapsed_s")
    ax_a.set_ylabel("Peak dBFS")
    ax_a.grid(True, alpha=0.22)
    ax_a.legend(loc="upper right", fontsize=8)
    fig.suptitle(title, fontsize=12)
    fig.tight_layout()
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, bbox_inches="tight")
    fig.savefig(output.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)
    return output


def write_report(out_dir=DEFAULT_OUT, timeline_path=DEFAULT_TIMELINE):
    records = load_metric_records(timeline_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    specs = [
        {
            "run_id": "spectrum_569e5f254203",
            "label": "long_hann_tone1k",
            "mode": "max_peak",
            "target_hz": None,
            "bandwidth_hz": None,
            "rules": {
                "amplitude_below": {"threshold_dbfs": -20.0, "hysteresis_db": 2.0,
                                    "min_consecutive": 3, "recover_consecutive": 3},
                "frequency_outside": {"enabled": True, "min_hz": 900.0, "max_hz": 1100.0,
                                      "hysteresis_hz": 10.0, "min_consecutive": 3,
                                      "recover_consecutive": 3},
            },
            "plot": "trend_long_hann.png",
        },
        {
            "run_id": "spectrum_15131a729d8b",
            "label": "analog_silence_target1k",
            "mode": "target_band",
            "target_hz": 1000.0,
            "bandwidth_hz": 100.0,
            "rules": {
                "amplitude_below": {"threshold_dbfs": -60.0, "hysteresis_db": 2.0,
                                    "min_consecutive": 3, "recover_consecutive": 3},
                "frequency_outside": {"enabled": False},
                "missing_peak": {"enabled": True, "min_consecutive": 3, "recover_consecutive": 2},
            },
            "plot": "trend_silence_target1k.png",
        },
        {
            "run_id": "spectrum_38749b56cab6",
            "label": "dual_hann_target1k",
            "mode": "target_band",
            "target_hz": 1000.0,
            "bandwidth_hz": 200.0,
            "rules": {
                "amplitude_below": {"threshold_dbfs": -60.0, "hysteresis_db": 2.0,
                                    "min_consecutive": 3, "recover_consecutive": 3},
                "frequency_outside": {"enabled": True, "min_hz": 800.0, "max_hz": 1200.0,
                                      "hysteresis_hz": 10.0, "min_consecutive": 3,
                                      "recover_consecutive": 3},
            },
            "plot": "trend_dual_hann_target1k.png",
        },
    ]
    results = []
    for spec in specs:
        analysis = analyze(
            records, spec["run_id"], spec["mode"], spec["target_hz"], spec["bandwidth_hz"],
            DEFAULT_MAX_GAP_S, spec["rules"])
        _plot_trend(
            analysis, analysis["events"], out_dir / spec["plot"],
            "B-X06 {} · {} · {}".format(spec["label"], spec["mode"], "REPLAY"))
        results.append({
            "run_id": analysis["run_id"],
            "label": analysis["label"],
            "mode": analysis["mode"],
            "target_hz": analysis["target_hz"],
            "bandwidth_hz": analysis["bandwidth_hz"],
            "max_gap_s": analysis["max_gap_s"],
            "point_count": analysis["point_count"],
            "valid_count": analysis["valid_count"],
            "missing_count": analysis["missing_count"],
            "continuity_gap_count": analysis["continuity_gap_count"],
            "rules": analysis["rules"],
            "events": analysis["events"],
            "plot": spec["plot"],
        })
    synthetic = synthetic_validation()
    payload = {
        "step": STEP,
        "generated": "2026-10-31",
        "timezone": "Asia/Shanghai",
        "source": "REPLAY",
        "timeline": str(timeline_path),
        "max_gap_s": DEFAULT_MAX_GAP_S,
        "runs": results,
        "synthetic_validation": synthetic,
        "boundaries": [
            "Only saved local peaks are used; target-band absence is reported as missing.",
            "Events are observations, not confirmed hardware faults.",
            "Long gaps break continuity and cannot prove continuous triggering.",
            "Amplitude is not physically calibrated; board_accepted remains false.",
        ],
    }
    (out_dir / "events.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8")
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeline", default=str(DEFAULT_TIMELINE))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    payload = write_report(Path(args.out), Path(args.timeline))
    summary = {
        "step": STEP,
        "output": str(Path(args.out)),
        "runs": len(payload["runs"]),
        "events": sum(len(item["events"]) for item in payload["runs"]),
        "synthetic_events": len(payload["synthetic_validation"]["events"]),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
