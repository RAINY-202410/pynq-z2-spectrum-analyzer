#!/usr/bin/env python3
"""Recompute and verify a B-X07 extension export package.

This script never loads PYNQ. It reads the archived source referenced by the
package's source_index.json and recomputes features, cursors, and trend/events.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def same_value(actual, expected, tolerance=1e-9):
    if actual is None or expected is None:
        return actual is expected
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(actual) - float(expected)) <= tolerance
    return actual == expected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True)
    parser.add_argument("--extension-root", default=str(Path(__file__).resolve().parent))
    args = parser.parse_args(argv)
    package = Path(args.package).resolve()
    extension = Path(args.extension_root).resolve()
    sys.path.insert(0, str(extension))
    sys.path.insert(0, str(extension / "baseline_readonly" / "host_tools" / "sw" / "pynq"))
    failures = []

    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest.get("files", {}).items():
        actual = sha256(package / name)
        if actual != expected["sha256"]:
            failures.append("manifest hash mismatch: " + name)
    parameters = json.loads((package / "parameters.json").read_text(encoding="utf-8"))
    source_index = json.loads((package / "source_index.json").read_text(encoding="utf-8"))
    summary = json.loads((package / "analysis_summary.json").read_text(encoding="utf-8"))
    cursor_payload = json.loads((package / "cursor_readings.json").read_text(encoding="utf-8"))

    import cursor_features
    import session_reader
    import spectrum_features
    import timeline_features

    index = json.loads((extension / "reports" / "B-X02" / "sample_index.json")
                       .read_text(encoding="utf-8"))
    samples = {item["frame_id"]: item for item in index["spectral_samples"]
               if item["run_id"] == parameters["run_id"]}
    frames = {}
    for frame_id in parameters["observed_frame_ids"]:
        sample = samples.get(frame_id)
        if sample is None:
            failures.append("missing observed sample: {}".format(frame_id))
            continue
        frame = dict(session_reader.load_spectral_sample(sample))
        frame["run_id"] = sample["run_id"]
        frame["frame_id"] = sample["frame_id"]
        frame["elapsed_s"] = sample["elapsed_s"]
        frames[frame_id] = frame

    accumulator = spectrum_features.SpectrumAccumulator(
        average_length=parameters["average_length"])
    for frame_id in parameters["observed_frame_ids"]:
        if frame_id in frames:
            accumulator.add(frames[frame_id])
    snapshot = accumulator.snapshot()
    recomputed_average = np.asarray(snapshot["average"]["linear"], dtype=float)
    recomputed_hold = np.asarray(snapshot["hold"]["linear"], dtype=float)
    packaged_average = np.load(package / "mean_square_average.npy", allow_pickle=False)
    packaged_hold = np.load(package / "peak_hold.npy", allow_pickle=False)
    if not np.array_equal(recomputed_average, packaged_average):
        failures.append("average array mismatch")
    if not np.array_equal(recomputed_hold, packaged_hold):
        failures.append("hold array mismatch")
    current = frames.get(parameters["current_frame_id"])
    if current is None:
        failures.append("current frame missing")
        current = next(iter(frames.values()))
    current_linear = np.asarray(current["amplitude"], dtype=float)
    if not np.array_equal(current_linear, np.load(package / "current_amplitude.npy", allow_pickle=False)):
        failures.append("current amplitude array mismatch")

    curve_key = parameters["cursor_curve"]
    curve = current_linear if curve_key == "current" else (
        recomputed_average if curve_key == "average" else recomputed_hold)
    for key in ("A", "B"):
        expected = cursor_payload.get(key)
        bin_index = parameters["cursors"].get(key)
        if expected is None or bin_index is None:
            continue
        actual = cursor_features.cursor_reading(
            current["frequency_hz"], curve, bin_index, cursor_payload["curve_name"])
        for field in ("bin", "frequency_hz", "linear", "dbfs"):
            if not same_value(actual[field], expected[field]):
                failures.append("cursor {} {} mismatch".format(key, field))
    expected_delta = cursor_payload.get("delta")
    if expected_delta is not None:
        a = cursor_features.cursor_reading(current["frequency_hz"], curve,
                                           parameters["cursors"]["A"], cursor_payload["curve_name"])
        b = cursor_features.cursor_reading(current["frequency_hz"], curve,
                                           parameters["cursors"]["B"], cursor_payload["curve_name"])
        actual_delta = cursor_features.dual_cursor_delta(a, b)
        for field in ("delta_f_hz", "delta_dbfs", "ratio", "ratio_db", "ratio_applicable"):
            if not same_value(actual_delta[field], expected_delta[field]):
                failures.append("delta {} mismatch".format(field))

    trend_settings = parameters["trend"]
    records = timeline_features.load_metric_records(extension / "reports" / "B-X02" / "metric_timeline.jsonl")
    trend = timeline_features.analyze(
        records,
        trend_settings["run_id"],
        trend_settings["mode"],
        trend_settings.get("target_hz"),
        trend_settings.get("bandwidth_hz"),
        trend_settings.get("max_gap_s", 2.0),
        trend_settings.get("rules"),
    )
    if trend["point_count"] != summary["trend"]["point_count"]:
        failures.append("trend point count mismatch")
    if len(trend["events"]) != summary["trend"]["event_count"]:
        failures.append("trend event count mismatch")

    result = {
        "ok": not failures,
        "package": str(package),
        "run_id": parameters["run_id"],
        "observed_frames": parameters["observed_frame_ids"],
        "average_count": snapshot["average"]["count"],
        "hold_count": snapshot["hold"]["count"],
        "trend_points": trend["point_count"],
        "trend_events": len(trend["events"]),
        "failures": failures,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
