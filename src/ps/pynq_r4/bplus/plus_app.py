#!/usr/bin/env python3
"""Offline B-X01 through B-X07 integrated workspace and replay server.

The server reads only the B-X02 index and archived session ZIP. It never
imports PYNQ and never instantiates an Overlay, DMA, MMIO or CMA allocation.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import shutil
import sys
import uuid
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

from export_results import resolve_report_path

HERE = Path(__file__).resolve().parent
WEB_ROOT = HERE / "web"
REPLAY_INDEX = HERE / "reports" / "B-X02" / "sample_index.json"


class ReplayError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class ReplayService:
    """Read-only view over the B-X02 index and archived spectral samples."""

    def __init__(self):
        if not REPLAY_INDEX.is_file():
            raise ReplayError(
                "B-X02 index not found; run `python session_reader.py` first",
                503,
            )
        self.index = json.loads(REPLAY_INDEX.read_text(encoding="utf-8"))
        self.runs = {run["run_id"]: run for run in self.index.get("runs", [])}
        self.samples_by_run = {}
        for run in self.index.get("runs", []):
            samples = [
                sample for sample in self.index.get("spectral_samples", [])
                if sample.get("run_id") == run["run_id"]
            ]
            samples.sort(key=lambda item: item["frame_id"])
            self.samples_by_run[run["run_id"]] = samples
        self._cache = {}
        self._metric_records_cache = None
        self._run_payloads = {
            run["run_id"]: self._run_payload(run) for run in self.index.get("runs", [])
        }

    def _sample_payload(self, sample, sample_index):
        return {
            "sample_index": sample_index,
            "frame_id": sample["frame_id"],
            "stem": sample["stem"],
            "sequence": sample["sequence"],
            "elapsed_s": sample["elapsed_s"],
            "capture_elapsed_s": sample.get("capture_elapsed_s"),
            "peak_hz": sample.get("parsed_peak_hz"),
            "peak_dbfs": sample.get("parsed_peak_dbfs"),
            "peak_bin": sample.get("parsed_peak_bin"),
            "tone_checks_passed": sample.get("tone_checks_passed"),
            "nonzero_bins": sample.get("nonzero_bins"),
            "complete_spectrum": sample.get("complete_spectrum", True),
        }

    def _segments(self, samples):
        segments = []
        for previous, current in zip(samples, samples[1:]):
            gap = max(0.0, float(current["elapsed_s"]) - float(previous["elapsed_s"]))
            rows = max(0, int(current["frame_id"]) - int(previous["frame_id"]) - 1)
            segments.append({
                "from_frame_id": previous["frame_id"],
                "to_frame_id": current["frame_id"],
                "from_elapsed_s": previous["elapsed_s"],
                "to_elapsed_s": current["elapsed_s"],
                "elapsed_gap_s": gap,
                "metric_rows_between": rows,
                "note": "该区间未留存完整频谱",
            })
        return segments

    def _run_payload(self, run):
        raw_samples = self.samples_by_run[run["run_id"]]
        samples = [
            self._sample_payload(sample, index + 1)
            for index, sample in enumerate(raw_samples)
        ]
        return {
            "run_id": run["run_id"],
            "label": run["label"],
            "description": run.get("description"),
            "scenario": run.get("scenario"),
            "window": run["window"],
            "fs_hz": run.get("fs_hz"),
            "N": run.get("N"),
            "expected_tones_hz": run.get("expected_tones_hz", []),
            "metric_rows": run["metric_rows"],
            "saved_samples": run["saved_samples"],
            "summary_elapsed_s": run.get("summary_elapsed_s"),
            "first_sequence": run.get("first_sequence"),
            "last_sequence": run.get("last_sequence"),
            "first_elapsed_s": run.get("first_elapsed_s"),
            "last_elapsed_s": run.get("last_elapsed_s"),
            "source_mode": "LIVE",
            "replay_mode": "REPLAY",
            "samples": samples,
            "segments": self._segments(samples),
        }

    def index_payload(self):
        verification = self.index.get("verification", {})
        return {
            "status": "OK",
            "step": "B-X07",
            "index_step": self.index.get("step"),
            "source": "REPLAY",
            "display_source": "REPLAY",
            "original_context": "BOARD_LIVE",
            "source_session": self.index.get("source_session", {}),
            "metric_rows": verification.get("metric_rows", 0),
            "spectral_samples": verification.get("spectral_samples", 0),
            "warnings": verification.get("warnings", []),
            "runs": [self._run_payloads[run["run_id"]] for run in self.index.get("runs", [])],
            "playback_modes": [
                {"id": "original", "label": "按原时间播放"},
                {"id": "equal", "label": "等间隔浏览留样（非原始时间轴）"},
            ],
            "speed_options": [1, 2, 5, 10, 20, 50],
            "features": {
                "average_name": "均方幅度平均谱",
                "hold_name": "峰值保持",
                "average_lengths": [8, 32],
            },
            "cursor_measurement": {
                "cursors": ["A", "B"],
                "curves": ["current", "average", "hold"],
                "zoom_ranges_hz": [5000, 12000, 24000],
            },
            "note": "sparse saved spectra only; no interpolation and no silent looping",
        }

    def _metric_records(self):
        if self._metric_records_cache is None:
            import timeline_features
            self._metric_records_cache = timeline_features.load_metric_records()
        return self._metric_records_cache

    def _trend_settings(self, request):
        run_id = str(request.get("run_id", ""))
        if run_id not in self.runs:
            raise ReplayError("unknown run_id: " + run_id, 404)
        mode = str(request.get("mode", "max_peak"))
        if mode not in ("max_peak", "target_band"):
            raise ReplayError("mode must be max_peak or target_band", 400)

        def number(key, default):
            value = request.get(key, default)
            if value in (None, ""):
                return default
            try:
                return float(value)
            except (TypeError, ValueError):
                raise ReplayError(key + " must be numeric", 400)

        target_hz = number("target_hz", None) if mode == "target_band" else None
        bandwidth_hz = number("bandwidth_hz", None) if mode == "target_band" else None
        if mode == "target_band" and (target_hz is None or bandwidth_hz is None):
            raise ReplayError("target_band requires target_hz and bandwidth_hz", 400)
        threshold = number("threshold_dbfs", -60.0)
        hysteresis = number("hysteresis_db", 2.0)
        max_gap = number("max_gap_s", 2.0)
        try:
            min_consecutive = int(request.get("min_consecutive", 3))
            recover_consecutive = int(request.get("recover_consecutive", min_consecutive))
        except (TypeError, ValueError):
            raise ReplayError("consecutive counts must be integers", 400)
        if min_consecutive < 1 or recover_consecutive < 1 or max_gap <= 0:
            raise ReplayError("consecutive counts and max_gap_s must be positive", 400)

        min_hz = request.get("min_hz")
        max_hz = request.get("max_hz")
        min_hz = None if min_hz in (None, "") else float(min_hz)
        max_hz = None if max_hz in (None, "") else float(max_hz)
        if (min_hz is None) != (max_hz is None):
            raise ReplayError("min_hz and max_hz must be supplied together", 400)
        if min_hz is not None and min_hz >= max_hz:
            raise ReplayError("min_hz must be below max_hz", 400)
        rules = {
            "amplitude_below": {
                "enabled": True,
                "threshold_dbfs": threshold,
                "hysteresis_db": hysteresis,
                "min_consecutive": min_consecutive,
                "recover_consecutive": recover_consecutive,
            },
            "frequency_outside": {
                "enabled": min_hz is not None,
                "min_hz": min_hz,
                "max_hz": max_hz,
                "hysteresis_hz": number("frequency_hysteresis_hz", 0.0),
                "min_consecutive": min_consecutive,
                "recover_consecutive": recover_consecutive,
            },
            "missing_peak": {
                "enabled": True,
                "min_consecutive": min_consecutive,
                "recover_consecutive": recover_consecutive,
            },
        }
        return {
            "run_id": run_id,
            "mode": mode,
            "target_hz": target_hz,
            "bandwidth_hz": bandwidth_hz,
            "threshold_dbfs": threshold,
            "hysteresis_db": hysteresis,
            "min_consecutive": min_consecutive,
            "recover_consecutive": recover_consecutive,
            "max_gap_s": max_gap,
            "min_hz": min_hz,
            "max_hz": max_hz,
            "rules": rules,
        }

    def _trend_analysis(self, settings):
        import timeline_features
        records = self._metric_records()
        analysis = timeline_features.analyze(
            records,
            settings["run_id"],
            settings["mode"],
            settings["target_hz"],
            settings["bandwidth_hz"],
            settings["max_gap_s"],
            settings["rules"],
        )
        return analysis

    def trend_payload(self, request):
        settings = self._trend_settings(request)
        analysis = self._trend_analysis(settings)
        points = [{
            "frame_id": point["frame_id"],
            "elapsed_s": point["elapsed_s"],
            "valid": point["valid"],
            "bin": point["bin"],
            "discrete_frequency_hz": point["discrete_frequency_hz"],
            "estimated_frequency_hz": point["estimated_frequency_hz"],
            "dbfs": point["dbfs"],
            "missing_reason": point["missing_reason"],
            "continuity_gap": point["continuity_gap"],
            "quality_hints": point["quality_hints"],
        } for point in analysis["points"]]
        return {
            "status": "OK",
            "step": "B-X07",
            "source": "REPLAY",
            "run_id": analysis["run_id"],
            "run_label": analysis["label"],
            "mode": analysis["mode"],
            "parameters": {
                key: settings[key] for key in (
                    "target_hz", "bandwidth_hz", "threshold_dbfs", "hysteresis_db",
                    "min_consecutive", "recover_consecutive", "max_gap_s", "min_hz", "max_hz")
            },
            "rules": settings["rules"],
            "points": points,
            "events": analysis["events"],
            "point_count": analysis["point_count"],
            "valid_count": analysis["valid_count"],
            "missing_count": analysis["missing_count"],
            "continuity_gap_count": analysis["continuity_gap_count"],
            "event_count": len(analysis["events"]),
        }

    def _load_sample_frame(self, sample):
        import session_reader
        frame = dict(session_reader.load_spectral_sample(sample))
        frame["run_id"] = sample["run_id"]
        frame["frame_id"] = sample["frame_id"]
        frame["elapsed_s"] = sample["elapsed_s"]
        return frame

    def export_payload(self, request):
        if not isinstance(request, dict):
            raise ReplayError("export request must be a JSON object", 400)
        run_id = str(request.get("run_id", ""))
        if run_id not in self.runs:
            raise ReplayError("unknown run_id: " + run_id, 404)
        run = self.runs[run_id]
        samples = self.samples_by_run[run_id]
        sample_by_id = {item["frame_id"]: item for item in samples}
        raw_observed = request.get("observed_frame_ids", [])
        if not isinstance(raw_observed, list):
            raise ReplayError("observed_frame_ids must be a list", 400)
        observed = []
        for value in raw_observed:
            try:
                frame_id = int(value)
            except (TypeError, ValueError):
                raise ReplayError("observed frame IDs must be integers", 400)
            if frame_id not in sample_by_id:
                raise ReplayError("observed frame is not a complete spectrum: {}".format(frame_id), 400)
            if frame_id not in observed:
                observed.append(frame_id)
        if not observed:
            raise ReplayError("no observed spectral samples to export", 400)
        if len(observed) > 32:
            raise ReplayError("at most 32 observed spectra can be exported", 400)
        try:
            current_frame_id = int(request.get("current_frame_id"))
        except (TypeError, ValueError):
            raise ReplayError("current_frame_id must be an integer", 400)
        if current_frame_id not in sample_by_id:
            raise ReplayError("current frame has no complete spectrum", 400)
        if current_frame_id not in observed:
            observed.append(current_frame_id)

        import spectrum_features
        import cursor_features
        try:
            average_length = int(request.get("average_length", 8))
        except (TypeError, ValueError):
            raise ReplayError("average_length must be an integer", 400)
        if average_length not in (8, 32):
            raise ReplayError("average_length must be 8 or 32", 400)
        curve_key = str(request.get("cursor_curve", "current"))
        if curve_key not in ("current", "average", "hold"):
            raise ReplayError("cursor_curve must be current, average or hold", 400)

        frames_by_id = {frame_id: self._load_sample_frame(sample_by_id[frame_id])
                        for frame_id in observed}
        accumulator = spectrum_features.SpectrumAccumulator(average_length=average_length)
        for frame_id in observed:
            accumulator.add(frames_by_id[frame_id])
        feature_snapshot = accumulator.snapshot()
        current = frames_by_id[current_frame_id]
        curve_names = {
            "current": "当前谱",
            "average": "均方幅度平均谱",
            "hold": "峰值保持",
        }
        if curve_key == "current":
            curve_linear = np.asarray(current["amplitude"], dtype=float)
        elif curve_key == "average":
            curve_linear = np.asarray(feature_snapshot["average"]["linear"], dtype=float)
        else:
            curve_linear = np.asarray(feature_snapshot["hold"]["linear"], dtype=float)
        frequency = np.asarray(current["frequency_hz"], dtype=float)
        current_linear = np.asarray(current["amplitude"], dtype=float)
        cursors = request.get("cursors", {})
        if not isinstance(cursors, dict):
            raise ReplayError("cursors must be an object", 400)
        readings = {}
        for key in ("A", "B"):
            value = cursors.get(key)
            if value is None:
                readings[key] = None
                continue
            try:
                bin_index = int(value)
            except (TypeError, ValueError):
                raise ReplayError("cursor bin must be an integer", 400)
            readings[key] = cursor_features.cursor_reading(
                frequency, curve_linear, bin_index, curve_names[curve_key])
        delta = (cursor_features.dual_cursor_delta(readings["A"], readings["B"])
                 if readings["A"] and readings["B"] else None)

        trend_request = dict(request.get("trend") or {})
        trend_request["run_id"] = run_id
        settings = self._trend_settings(trend_request)
        trend = self._trend_analysis(settings)
        export_id = "{}_{}_{}".format(
            run_id, datetime.now().strftime("%Y%m%d_%H%M%S"), uuid.uuid4().hex[:6])
        out_dir = resolve_report_path("B-X07/exports/" + export_id)
        out_dir.mkdir(parents=True, exist_ok=False)

        np.save(out_dir / "frequency_hz.npy", frequency, allow_pickle=False)
        np.save(out_dir / "current_amplitude.npy", current_linear, allow_pickle=False)
        np.save(out_dir / "selected_curve_amplitude.npy", curve_linear, allow_pickle=False)
        np.save(out_dir / "mean_square_average.npy",
                np.asarray(feature_snapshot["average"]["linear"], dtype=float), allow_pickle=False)
        np.save(out_dir / "peak_hold.npy",
                np.asarray(feature_snapshot["hold"]["linear"], dtype=float), allow_pickle=False)
        source_session = self.index.get("source_session", {})
        source_index = {
            "run_id": run_id,
            "run_label": run["label"],
            "window": run["window"],
            "fs_hz": run["fs_hz"],
            "N": run["N"],
            "source_session": source_session,
            "metric_rows": run["metric_rows"],
            "saved_samples": run["saved_samples"],
            "sparse_retained_spectra": run["saved_samples"] < run["metric_rows"],
            "observed_frame_ids": observed,
            "current_frame_id": current_frame_id,
            "samples": [{
                "frame_id": item["frame_id"],
                "stem": item["stem"],
                "sequence": item["sequence"],
                "elapsed_s": item["elapsed_s"],
                "words_member": item["words_member"],
                "words_sha256": item["words_sha256"],
                "state_member": item["state_member"],
                "state_sha256": item["state_sha256"],
                "fft_member": item["fft_member"],
                "fft_sha256": item["fft_sha256"],
                "run_archive_member": item["run_archive_member"],
                "run_archive_sha256": item["run_archive_sha256"],
            } for item in (sample_by_id[frame_id] for frame_id in observed)],
        }
        parameters = {
            "extension_version": "b_plus_v1_B-X07_v1",
            "run_id": run_id,
            "observed_frame_ids": observed,
            "current_frame_id": current_frame_id,
            "average_length": average_length,
            "cursor_curve": curve_key,
            "cursors": {key: (None if value is None else value["bin"])
                        for key, value in readings.items()},
            "trend": settings,
        }
        cursor_payload = {
            "curve": curve_key,
            "curve_name": curve_names[curve_key],
            "A": readings["A"],
            "B": readings["B"],
            "delta": delta,
            "ratio_units": "linear amplitude ratio; dB representation included when applicable",
        }
        events_payload = {
            "step": "B-X07",
            "source": "REPLAY",
            "run_id": run_id,
            "rules": settings["rules"],
            "events": trend["events"],
            "synthetic": False,
            "board_fault": False,
        }
        trend_payload = {
            "step": "B-X07",
            "source": "REPLAY",
            "run_id": run_id,
            "parameters": settings,
            "points": trend["points"],
            "events": trend["events"],
        }
        summary = {
            "schema_version": 1,
            "extension": "b_plus_v1",
            "extension_version": "b_plus_v1_B-X07_v1",
            "step": "B-X07",
            "created": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source": {
                "context": "BOARD_LIVE",
                "mode": "LIVE",
                "display_mode": "REPLAY",
                "session": source_session,
            },
            "run": {
                "run_id": run_id,
                "label": run["label"],
                "window": run["window"],
                "fs_hz": run["fs_hz"],
                "N": run["N"],
            },
            "data_group": feature_snapshot["group"],
            "metric_rows": run["metric_rows"],
            "saved_samples": run["saved_samples"],
            "observed_frames": observed,
            "current_frame_id": current_frame_id,
            "sparse_retained_spectra": run["saved_samples"] < run["metric_rows"],
            "average": {
                "name": feature_snapshot["average"]["name"],
                "count": feature_snapshot["average"]["count"],
                "window": feature_snapshot["average"]["window"],
                "start_frame_id": feature_snapshot["average"]["start_frame_id"],
                "end_frame_id": feature_snapshot["average"]["end_frame_id"],
                "start_elapsed_s": feature_snapshot["average"]["start_elapsed_s"],
                "end_elapsed_s": feature_snapshot["average"]["end_elapsed_s"],
                "array_file": "mean_square_average.npy",
            },
            "hold": {
                "name": feature_snapshot["hold"]["name"],
                "count": feature_snapshot["hold"]["count"],
                "start_frame_id": feature_snapshot["hold"]["start_frame_id"],
                "end_frame_id": feature_snapshot["hold"]["end_frame_id"],
                "start_elapsed_s": feature_snapshot["hold"]["start_elapsed_s"],
                "end_elapsed_s": feature_snapshot["hold"]["end_elapsed_s"],
                "array_file": "peak_hold.npy",
            },
            "cursors": cursor_payload,
            "cursors_selected_curve_file": "selected_curve_amplitude.npy",
            "trend": {
                "mode": trend["mode"],
                "parameters": settings,
                "point_count": trend["point_count"],
                "valid_count": trend["valid_count"],
                "missing_count": trend["missing_count"],
                "continuity_gap_count": trend["continuity_gap_count"],
                "event_count": len(trend["events"]),
                "trend_file": "trend.json",
                "events_file": "events.json",
            },
            "verification": {
                "recomputed_from_source": True,
                "source_hashes_embedded": True,
                "amplitude_calibrated": False,
                "board_accepted": False,
                "old_auditor_scope": "Old session auditor is not claimed to validate this extension package.",
            },
        }
        (out_dir / "source_index.json").write_text(
            json.dumps(source_index, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8")
        (out_dir / "parameters.json").write_text(
            json.dumps(parameters, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8")
        (out_dir / "cursor_readings.json").write_text(
            json.dumps(cursor_payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8")
        (out_dir / "events.json").write_text(
            json.dumps(events_payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8")
        (out_dir / "trend.json").write_text(
            json.dumps(trend_payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8")
        (out_dir / "analysis_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8")
        (out_dir / "README.md").write_text(
            "# b_plus_v1 B-X07 分析导出包\n\n"
            "- 来源：BOARD_LIVE 原始归档，当前为 REPLAY。\n"
            "- `analysis_summary.json` 记录参数、样本范围、曲线、游标、趋势和事件。\n"
            "- `.npy` 为单边线性幅度数组，非复数 FFT。\n"
            "- 这是扩展自己的结果，旧会话审计器不宣称已完整验收本格式。\n"
            "- 重算命令：`python recompute_export.py --package <本目录> --extension-root <b_plus_v1>`。\n",
            encoding="utf-8")
        recompute_source = HERE / "recompute_export.py"
        if recompute_source.is_file():
            shutil.copy2(recompute_source, out_dir / "recompute_export.py")
        package_files = sorted(
            path for path in out_dir.iterdir()
            if path.is_file() and path.name != "manifest.json")
        manifest = {
            "schema_version": 1,
            "step": "B-X07",
            "extension_version": "b_plus_v1_B-X07_v1",
            "source_session_sha256": source_session.get("sha256"),
            "files": {
                path.name: {
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
                }
                for path in package_files
            },
        }
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8")
        return {
            "status": "OK",
            "step": "B-X07",
            "export_id": export_id,
            "package_path": str(out_dir.relative_to(HERE)).replace("\\", "/"),
            "files": [path.name for path in package_files] + ["manifest.json"],
            "summary": summary,
            "manifest": manifest,
        }

    def frame_payload(self, run_id, frame_id):
        run = self.runs.get(run_id)
        if run is None:
            raise ReplayError("unknown run_id: " + str(run_id), 404)
        samples = self.samples_by_run.get(run_id, [])
        sample_index = None
        sample = None
        for index, candidate in enumerate(samples, 1):
            if candidate["frame_id"] == frame_id:
                sample_index, sample = index, candidate
                break
        if sample is None:
            raise ReplayError("该 frame 未留存完整频谱：{} / {}".format(run_id, frame_id), 404)

        key = (run_id, int(frame_id))
        if key not in self._cache:
            import session_reader
            frame = session_reader.load_spectral_sample(sample)
            payload = {
                "status": "OK",
                "step": "B-X07",
                "source": "PL_FFT",
                "mode": "REPLAY",
                "display_source": "REPLAY",
                "source_mode": "LIVE",
                "original_context": "BOARD_LIVE",
                "run_id": run_id,
                "run_label": run["label"],
                "frame_id": sample["frame_id"],
                "sample_index": sample_index,
                "stem": sample["stem"],
                "sequence": sample["sequence"],
                "elapsed_s": sample["elapsed_s"],
                "capture_elapsed_s": sample.get("capture_elapsed_s"),
                "window": sample["window"],
                "fs_hz": sample["fs_hz"],
                "N": sample["N"],
                "frequency_hz": [float(value) for value in frame["frequency_hz"]],
                "amplitude": [float(value) for value in frame["amplitude"]],
                "dbfs": [float(value) for value in frame["dbfs"]],
                "quality": {
                    "tone_checks_passed": sample.get("tone_checks_passed"),
                    "nonzero_bins": sample.get("nonzero_bins"),
                    "amplitude_calibrated": False,
                    "complete_spectrum": True,
                },
                "note": "saved PL result loaded in REPLAY; no new board acquisition",
            }
            self._cache[key] = payload
            if len(self._cache) > 32:
                self._cache.pop(next(iter(self._cache)))
        return self._cache[key]


def offline_status() -> dict:
    from verify_baseline import verify

    baseline = verify(require_source=False)
    b_x11_signal = (
        HERE / "reports" / "B-X11" / "signal_generator_20261101"
        / "channel_calibration.json"
    )
    b_x11_pc = (
        HERE / "reports" / "B-X11" / "full_20261101"
        / "channel_calibration.json"
    )
    b_x11_signal_payload = (
        json.loads(b_x11_signal.read_text(encoding="utf-8"))
        if b_x11_signal.is_file() else {}
    )
    b_x11_pc_payload = (
        json.loads(b_x11_pc.read_text(encoding="utf-8"))
        if b_x11_pc.is_file() else {}
    )
    b_x12 = HERE / "reports" / "B-X12" / "measured_20261101" / "rc_measured.json"
    b_x12_payload = (
        json.loads(b_x12.read_text(encoding="utf-8"))
        if b_x12.is_file() else {}
    )
    replay = HERE / "baseline_readonly" / "host_tools" / "sw" / "pynq" / "replay_examples"
    index_path = REPLAY_INDEX
    index = None
    if index_path.is_file():
        index = json.loads(index_path.read_text(encoding="utf-8"))
    b_x03 = {"ready": False, "error": None}
    try:
        service = ReplayService()
        payload = service.index_payload()
        b_x03 = {
            "ready": True,
            "error": None,
            "runs": len(payload["runs"]),
            "metric_rows": payload["metric_rows"],
            "spectral_samples": payload["spectral_samples"],
        }
    except Exception as exc:
        b_x03 = {"ready": False, "error": str(exc)}
    return {
        "extension": "b_plus_v1",
        "step": "B-X07",
        "project_step": "B-X12",
        "status": "OFFLINE_READY" if baseline["ok"] and b_x03["ready"] else "BASELINE_OR_INDEX_FAILED",
        "hardware_access": False,
        "pynq_imported": "pynq" in sys.modules,
        "baseline_ok": baseline["ok"],
        "baseline_failures": baseline["failures"],
        "replay_examples": len(list(replay.glob("*_words.npy"))),
        "b_x02": {
            "index_present": index is not None,
            "runs": len(index["runs"]) if index else 0,
            "metric_rows": index["verification"]["metric_rows"] if index else 0,
            "spectral_samples": index["verification"]["spectral_samples"] if index else 0,
        },
        "b_x03": b_x03,
        "b_x04": {
            "ready": True,
            "average_lengths": [8, 32],
            "average_name": "均方幅度平均谱",
            "hold_name": "峰值保持",
            "calculation": "linear mean-square average + elementwise peak hold",
        },
        "b_x05": {
            "ready": True,
            "cursors": ["A", "B"],
            "measurement_curves": ["当前谱", "均方幅度平均谱", "峰值保持"],
            "zoom_ranges_hz": [5000, 12000, 24000],
        },
        "b_x06": {
            "ready": (HERE / "reports" / "B-X06" / "events.json").is_file(),
            "events_path": str(HERE / "reports" / "B-X06" / "events.json"),
            "trend_analysis": "saved local peaks; missing target band is not reconstructed",
        },
        "b_x07": {
            "ready": (HERE / "reports" / "B-X07" / "demo_export" / "manifest.json").is_file(),
            "export_root": str(HERE / "reports" / "B-X07" / "exports"),
            "features": ["replay", "average/hold", "A/B cursors", "trend/events", "analysis export"],
        },
        "b_x08": {
            "ready": (HERE / "reports" / "B-X08" / "subscription_report.json").is_file(),
            "scope": "offline read-only /api/status fixture; BOARD_LIVE pending",
            "dedupe_key": "(service_address, process_id, run_id, frame_id)",
        },
        "b_x09": {
            "ready": (HERE / "reports" / "B-X09" / "rc_points.json").is_file(),
            "scope": "theory and SYNTHETIC RC baseline; no measured RC",
            "fc_hz": 1591.5494309189535,
            "design_points": 16,
            "synthetic_cases": 4,
        },
        "b_x10": {
            "ready": (HERE / "reports" / "B-X10" / "fit_results.json").is_file(),
            "scope": "synchronous (2,1024) synthetic phasor fit; no board RC data",
            "source": "M4_RAW_STEREO",
            "board_accepted": False,
        },
        "b_x11": {
            "ready": b_x11_signal.is_file(),
            "status": b_x11_signal_payload.get(
                "status", "BOARD_DATA_VALIDATED_CONDITIONS_PENDING"),
            "scope": (
                "16 signal-generator frequency points passed; 6 kHz retry excluded; "
                "OWON XDG3122, 0.2 Vpp, 26 C, L/R parallel direct-through"),
            "conditions_complete": b_x11_signal_payload.get(
                "conditions_complete", False),
            "pc_reference_status": b_x11_pc_payload.get("status"),
            "board_accepted": False,
        },
        "b_x12": {
            "ready": b_x12.is_file(),
            "status": b_x12_payload.get("status"),
            "measured_points": b_x12_payload.get("measured_point_count"),
            "passed_points": b_x12_payload.get("pass_count"),
            "theory_cutoff_hz": b_x12_payload.get("theory_cutoff_hz"),
            "fitted_cutoff_hz": b_x12_payload.get("measured_cutoff_hz"),
            "actual_r_ohm": b_x12_payload.get("conditions", {}).get("actual_r_ohm"),
            "actual_c_f": b_x12_payload.get("conditions", {}).get("actual_c_f"),
            "temperature": b_x12_payload.get("conditions", {}).get("temperature"),
            "board_accepted": False,
        },
        "board_deployed": "spectrum_software_1_r2",
        "r3_status": "CANDIDATE_NOT_DEPLOYED",
        "note": "B-X07 integrated replay, trend, cursors, feature analysis and export.",
    }


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write("[offline] " + (format % args) + "\n")


class ReplayHandler(NoCacheHandler):
    service = None

    def _send_json(self, status, payload):
        blob = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/replay/"):
            try:
                if self.service is None:
                    raise ReplayError("replay service unavailable", 503)
                if parsed.path == "/api/replay/index":
                    self._send_json(200, self.service.index_payload())
                    return
                if parsed.path == "/api/replay/frame":
                    params = parse_qs(parsed.query)
                    run_id = (params.get("run_id") or [""])[0]
                    frame_text = (params.get("frame_id") or [""])[0]
                    if not run_id or not frame_text:
                        raise ReplayError("run_id and frame_id are required", 400)
                    try:
                        frame_id = int(frame_text)
                    except ValueError:
                        raise ReplayError("frame_id must be an integer", 400)
                    self._send_json(200, self.service.frame_payload(run_id, frame_id))
                    return
                if parsed.path == "/api/replay/trend":
                    params = {
                        key: (values[0] if values else "")
                        for key, values in parse_qs(parsed.query).items()
                    }
                    self._send_json(200, self.service.trend_payload(params))
                    return
                raise ReplayError("unknown replay API", 404)
            except ReplayError as exc:
                self._send_json(exc.status, {"status": "ERROR", "step": "B-X07", "error": exc.message})
                return
            except Exception as exc:
                self._send_json(500, {"status": "ERROR", "step": "B-X07", "error": str(exc)})
                return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/export":
            self._send_json(404, {"status": "ERROR", "step": "B-X07", "error": "unknown POST API"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"status": "ERROR", "step": "B-X07", "error": "invalid Content-Length"})
            return
        if length <= 0 or length > 2_000_000:
            self._send_json(400, {"status": "ERROR", "step": "B-X07", "error": "invalid request size"})
            return
        try:
            request = json.loads(self.rfile.read(length).decode("utf-8"))
            if self.service is None:
                raise ReplayError("replay service unavailable", 503)
            self._send_json(200, self.service.export_payload(request))
        except ReplayError as exc:
            self._send_json(exc.status, {"status": "ERROR", "step": "B-X07", "error": exc.message})
        except (UnicodeDecodeError, ValueError) as exc:
            self._send_json(400, {"status": "ERROR", "step": "B-X07", "error": "invalid JSON"})
        except Exception as exc:
            self._send_json(500, {"status": "ERROR", "step": "B-X07", "error": str(exc)})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="print offline status and exit")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    status = offline_status()
    if args.check:
        print(json.dumps(status, indent=2, ensure_ascii=True))
        return 0 if status["status"] == "OFFLINE_READY" else 1
    if status["status"] != "OFFLINE_READY":
        print(json.dumps(status, indent=2, ensure_ascii=True), file=sys.stderr)
        return 1
    service = ReplayService()
    ReplayHandler.service = service
    handler = functools.partial(ReplayHandler, directory=str(WEB_ROOT))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"b_plus_v1 B-X07 OFFLINE_ONLY replay server: http://{args.host}:{server.server_port}/")
    print("No Overlay/PYNQ allocation/DMA access is performed by this entry point.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
