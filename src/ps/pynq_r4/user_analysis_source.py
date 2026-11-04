"""Replay-compatible adapter for user-created live-analysis records."""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import threading
import uuid

import numpy as np
from plus_app import ReplayError, ReplayService


class UserAnalysisService(ReplayService):
    """Use the demo viewer against an activated user analysis record."""

    def __init__(self, record_store):
        self.record_store = record_store
        self.index = {}
        self.runs = {}
        self.samples_by_run = {}
        self._cache = {}
        self._metric_records_cache = None
        self._run_payloads = {}
        self._record_id = None
        self._record_folder = None
        self._lock = threading.RLock()

    def activate(self, record_id):
        with self._lock:
            record = self.record_store.load(record_id)
            if record.get("record_type") != "analysis":
                raise ReplayError("记录不是频谱分析记录", 400)
            folder = self.record_store._record_dir(record_id)
            index_path = folder / "sample_index.json"
            if not index_path.is_file():
                raise ReplayError("用户记录缺少 sample_index.json", 404)
            index = json.loads(index_path.read_text(encoding="utf-8"))
            run_id = index.get("run_id")
            if run_id != record_id:
                raise ReplayError("用户记录 run_id 不一致", 409)
            samples = list(index.get("samples") or [])
            samples.sort(key=lambda item: item["frame_id"])
            run = {
                "run_id": run_id,
                "label": record["title"],
                "description": "用户主动保存的当前实时频谱分析",
                "scenario": (record.get("settings") or {}).get("scenario"),
                "window": (
                    samples[0]["window"] if samples else
                    (record.get("settings") or {}).get("window", "hann")),
                "fs_hz": samples[0]["fs_hz"] if samples else None,
                "N": samples[0]["N"] if samples else 1024,
                "expected_tones_hz": (
                    (record.get("settings") or {}).get("expected_tones_hz") or []),
                "metric_rows": int(record.get("metric_row_count") or 0),
                "saved_samples": len(samples),
                "summary_elapsed_s": (
                    samples[-1]["elapsed_s"] if samples else 0),
                "first_sequence": samples[0]["sequence"] if samples else None,
                "last_sequence": samples[-1]["sequence"] if samples else None,
                "first_elapsed_s": samples[0]["elapsed_s"] if samples else None,
                "last_elapsed_s": samples[-1]["elapsed_s"] if samples else None,
            }
            self.index = {
                "schema_version": index.get("schema_version"),
                "step": "USER_ANALYSIS",
                "source_session": {
                    "record_id": record_id,
                    "title": record["title"],
                    "created": record["created"],
                    "source": record["source"],
                    "is_demo": False,
                    "record_status": record.get("record_status"),
                },
                "verification": {
                    "metric_rows": run["metric_rows"],
                    "spectral_samples": len(samples),
                    "warnings": (
                        [] if record.get("record_status") == "COMPLETE_REPLAY"
                        else ["当前用户记录不是完整多帧回放数据"]),
                },
                "runs": [run],
            }
            self.runs = {run_id: run}
            self.samples_by_run = {run_id: samples}
            self._run_payloads = {run_id: self._run_payload(run)}
            self._cache = {}
            self._metric_records_cache = None
            self._record_id = record_id
            self._record_folder = folder
            return self.index_payload()

    def _load_sample_frame(self, sample):
        folder = self._record_folder
        if folder is None:
            raise ReplayError("用户记录尚未打开", 503)
        stem = sample.get("stem")
        if not stem:
            raise ReplayError("用户频谱缺少 stem", 409)
        path = (folder / "frames" / (stem + "_render.json")).resolve()
        path.relative_to(folder)
        if not path.is_file():
            raise ReplayError("用户频谱文件不存在", 404)
        frame = json.loads(path.read_text(encoding="utf-8"))
        frame["run_id"] = sample["run_id"]
        frame["frame_id"] = sample["frame_id"]
        frame["elapsed_s"] = sample["elapsed_s"]
        frame["mode"] = "USER_RECORD"
        frame["display_source"] = "USER_RECORD"
        return frame

    def _metric_records(self):
        if self._metric_records_cache is None:
            if self._record_folder is None:
                raise ReplayError("用户记录尚未打开", 503)
            path = self._record_folder / "metric_timeline.jsonl"
            rows = []
            if path.is_file():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        rows.append(json.loads(line))
            self._metric_records_cache = rows
        return self._metric_records_cache

    def index_payload(self):
        payload = super().index_payload()
        payload.update({
            "step": "USER_ANALYSIS",
            "source": "USER_RECORD",
            "display_source": "USER_RECORD",
            "original_context": "CURRENT_LIVE_ANALYSIS",
            "is_demo": False,
        })
        return payload

    def frame_payload(self, run_id, frame_id):
        run = self.runs.get(run_id)
        if run is None:
            raise ReplayError("未知的用户记录：" + str(run_id), 404)
        samples = self.samples_by_run.get(run_id, [])
        sample_index = None
        sample = None
        for index, candidate in enumerate(samples, 1):
            if candidate["frame_id"] == frame_id:
                sample_index, sample = index, candidate
                break
        if sample is None:
            raise ReplayError("用户记录中没有该完整频谱", 404)
        key = (run_id, int(frame_id))
        if key not in self._cache:
            frame = self._load_sample_frame(sample)
            metrics = frame.get("metrics") or {}
            payload = {
                "status": "OK",
                "step": "USER_ANALYSIS",
                "source": "PL_FFT",
                "mode": "USER_RECORD",
                "display_source": "USER_RECORD",
                "source_mode": "LIVE",
                "original_context": "CURRENT_LIVE_ANALYSIS",
                "run_id": run_id,
                "run_label": run["label"],
                "frame_id": sample["frame_id"],
                "sample_index": sample_index,
                "stem": sample["stem"],
                "sequence": sample["sequence"],
                "elapsed_s": sample["elapsed_s"],
                "capture_elapsed_s": None,
                "window": sample["window"],
                "window_name": sample["window"],
                "window_sum": frame.get("window_sum"),
                "fs_hz": sample["fs_hz"],
                "N": sample["N"],
                "frequency_hz": [float(value) for value in frame["frequency_hz"]],
                "amplitude": [float(value) for value in frame["amplitude"]],
                "dbfs": [float(value) for value in frame["dbfs"]],
                "metrics": metrics,
                "quality": {
                    "tone_checks_passed": metrics.get("tone_checks_passed"),
                    "nonzero_bins": metrics.get("nonzero_bins"),
                    "amplitude_calibrated": False,
                    "complete_spectrum": True,
                },
                "note": "用户主动保存的当前实时频谱分析",
            }
            self._cache[key] = payload
            if len(self._cache) > 32:
                self._cache.pop(next(iter(self._cache)))
        return self._cache[key]

    def trend_payload(self, request):
        payload = super().trend_payload(request)
        payload.update({
            "step": "USER_ANALYSIS",
            "source": "USER_RECORD",
        })
        return payload

    def export_payload(self, request):
        if not isinstance(request, dict):
            raise ReplayError("导出请求必须为 JSON 对象", 400)
        run_id = str(request.get("run_id", ""))
        if run_id not in self.runs:
            raise ReplayError("未知的用户记录", 404)
        run = self.runs[run_id]
        samples = self.samples_by_run[run_id]
        sample_by_id = {item["frame_id"]: item for item in samples}
        observed = []
        for value in request.get("observed_frame_ids", []):
            try:
                frame_id = int(value)
            except (TypeError, ValueError):
                raise ReplayError("观察帧编号必须为整数", 400)
            if frame_id not in sample_by_id:
                raise ReplayError("观察帧没有完整频谱", 400)
            if frame_id not in observed:
                observed.append(frame_id)
        if not observed:
            raise ReplayError("没有可导出的完整频谱", 400)
        try:
            current_frame_id = int(request.get("current_frame_id"))
        except (TypeError, ValueError):
            raise ReplayError("当前帧编号必须为整数", 400)
        if current_frame_id not in sample_by_id:
            raise ReplayError("当前帧没有完整频谱", 400)
        if current_frame_id not in observed:
            observed.append(current_frame_id)
        average_length = int(request.get("average_length", 8))
        if average_length not in (8, 32):
            raise ReplayError("平均长度只能为 8 或 32", 400)
        curve_key = str(request.get("cursor_curve", "current"))
        if curve_key not in ("current", "average", "hold"):
            raise ReplayError("未知的游标曲线", 400)

        import spectrum_features
        import cursor_features
        frames_by_id = {
            frame_id: self._load_sample_frame(sample_by_id[frame_id])
            for frame_id in observed
        }
        accumulator = spectrum_features.SpectrumAccumulator(
            average_length=average_length)
        for frame_id in observed:
            accumulator.add(frames_by_id[frame_id])
        snapshot = accumulator.snapshot()
        current = frames_by_id[current_frame_id]
        curve_linear = {
            "current": np.asarray(current["amplitude"], dtype=float),
            "average": np.asarray(snapshot["average"]["linear"], dtype=float),
            "hold": np.asarray(snapshot["hold"]["linear"], dtype=float),
        }[curve_key]
        frequency = np.asarray(current["frequency_hz"], dtype=float)
        readings = {}
        curve_names = {
            "current": "当前谱",
            "average": "均方幅度平均谱",
            "hold": "峰值保持",
        }
        for key in ("A", "B"):
            value = (request.get("cursors") or {}).get(key)
            readings[key] = (
                None if value is None else cursor_features.cursor_reading(
                    frequency, curve_linear, int(value), curve_names[curve_key]))
        delta = (
            cursor_features.dual_cursor_delta(readings["A"], readings["B"])
            if readings["A"] and readings["B"] else None)
        trend_request = dict(request.get("trend") or {})
        trend_request["run_id"] = run_id
        settings = self._trend_settings(trend_request)
        trend = self._trend_analysis(settings)

        export_id = "{}_{}_{}".format(
            run_id, datetime.now().strftime("%Y%m%d_%H%M%S"),
            uuid.uuid4().hex[:6])
        out_dir = self._record_folder / "exports" / export_id
        out_dir.mkdir(parents=True, exist_ok=False)
        np.save(out_dir / "frequency_hz.npy", frequency, allow_pickle=False)
        np.save(
            out_dir / "current_amplitude.npy",
            np.asarray(current["amplitude"], dtype=float),
            allow_pickle=False,
        )
        np.save(
            out_dir / "selected_curve_amplitude.npy",
            curve_linear, allow_pickle=False)
        np.save(
            out_dir / "mean_square_average.npy",
            np.asarray(snapshot["average"]["linear"], dtype=float),
            allow_pickle=False,
        )
        np.save(
            out_dir / "peak_hold.npy",
            np.asarray(snapshot["hold"]["linear"], dtype=float),
            allow_pickle=False,
        )
        source_index = {
            "source": "USER_RECORD",
            "record_id": self._record_id,
            "record_title": run["label"],
            "run_id": run_id,
            "window": run["window"],
            "fs_hz": run["fs_hz"],
            "N": run["N"],
            "observed_frame_ids": observed,
            "current_frame_id": current_frame_id,
            "samples": [{
                "frame_id": sample["frame_id"],
                "stem": sample["stem"],
                "sequence": sample["sequence"],
                "elapsed_s": sample["elapsed_s"],
                "words_file": "frames/" + sample["stem"] + "_words.npy",
                "state_file": "frames/" + sample["stem"] + "_state.json",
                "render_file": "frames/" + sample["stem"] + "_render.json",
            } for sample in (sample_by_id[frame_id] for frame_id in observed)],
        }
        cursor_payload = {
            "curve": curve_key,
            "curve_name": curve_names[curve_key],
            "A": readings["A"],
            "B": readings["B"],
            "delta": delta,
        }
        trend_payload = {
            "source": "USER_RECORD",
            "run_id": run_id,
            "parameters": settings,
            "points": trend["points"],
            "events": trend["events"],
        }
        summary = {
            "schema_version": 1,
            "created": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source": {
                "context": "USER_SAVED_LIVE_ANALYSIS",
                "record_id": self._record_id,
                "is_demo": False,
            },
            "run": {
                "run_id": run_id,
                "label": run["label"],
                "window": run["window"],
                "fs_hz": run["fs_hz"],
                "N": run["N"],
            },
            "metric_rows": run["metric_rows"],
            "saved_samples": run["saved_samples"],
            "observed_frames": observed,
            "current_frame_id": current_frame_id,
            "average": {
                "name": snapshot["average"]["name"],
                "count": snapshot["average"]["count"],
                "array_file": "mean_square_average.npy",
            },
            "hold": {
                "name": snapshot["hold"]["name"],
                "count": snapshot["hold"]["count"],
                "array_file": "peak_hold.npy",
            },
            "cursors": cursor_payload,
            "trend": {
                "mode": trend["mode"],
                "parameters": settings,
                "point_count": trend["point_count"],
                "event_count": len(trend["events"]),
            },
        }
        for name, value in (
                ("source_index.json", source_index),
                ("parameters.json", {
                    "observed_frame_ids": observed,
                    "current_frame_id": current_frame_id,
                    "average_length": average_length,
                    "cursor_curve": curve_key,
                    "cursors": request.get("cursors"),
                    "trend": settings,
                }),
                ("cursor_readings.json", cursor_payload),
                ("trend.json", trend_payload),
                ("events.json", {
                    "source": "USER_RECORD",
                    "run_id": run_id,
                    "events": trend["events"],
                }),
                ("analysis_summary.json", summary)):
            (out_dir / name).write_text(
                json.dumps(value, indent=2, ensure_ascii=False,
                           allow_nan=False) + "\n",
                encoding="utf-8")
        (out_dir / "README.md").write_text(
            "# 用户频谱分析导出包\n\n"
            "- 来源：用户主动保存的当前实时采集。\n"
            "- 包含当前谱、均方幅度平均、峰值保持、游标和趋势数组。\n"
            "- 不是内置演示数据。\n",
            encoding="utf-8")
        package_files = sorted(
            path for path in out_dir.iterdir() if path.is_file())
        manifest = {
            "schema_version": 1,
            "source": "USER_RECORD",
            "record_id": self._record_id,
            "files": {
                path.name: {
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
                } for path in package_files
            },
        }
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        return {
            "status": "OK",
            "export_id": export_id,
            "package_path": str(out_dir),
            "files": [path.name for path in package_files] + ["manifest.json"],
            "summary": summary,
            "manifest": manifest,
        }
