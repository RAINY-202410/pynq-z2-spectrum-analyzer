"""Small local store for user-created analysis and frequency-response records."""

from datetime import datetime
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import uuid

import numpy as np


class RecordStoreError(ValueError):
    """Raised for invalid or unknown user records."""


def _jsonable(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    return value


class RecordStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _record_dir(self, record_id):
        if not isinstance(record_id, str) or not re.fullmatch(
                r"(?:analysis|response|response_rc|response_generic)_"
                r"[0-9]{8}_[0-9]{6}_[0-9a-f]{8}",
                record_id):
            raise RecordStoreError("无效的记录编号")
        path = (self.root / record_id).resolve()
        path.relative_to(self.root)
        return path

    def save(self, record_type, title, source, payload):
        if record_type not in ("analysis", "response"):
            raise RecordStoreError("未知的记录类型")
        title = str(title or "").strip()
        if not title or len(title) > 100:
            raise RecordStoreError("记录名称必须为 1～100 个字符")
        now = datetime.now().astimezone()
        record_id = "{}_{}_{}".format(
            record_type, now.strftime("%Y%m%d_%H%M%S"), uuid.uuid4().hex[:8])
        folder = self._record_dir(record_id)
        folder.mkdir(parents=False, exist_ok=False)
        data = {
            "schema_version": 1,
            "record_id": record_id,
            "record_type": record_type,
            "title": title,
            "source": str(source),
            "created": now.isoformat(),
            "payload": _jsonable(payload),
        }
        blob = (
            json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)
            + "\n"
        ).encode("utf-8")
        record_path = folder / "record.json"
        record_path.write_bytes(blob)
        (folder / "record.sha256").write_text(
            hashlib.sha256(blob).hexdigest().upper() + "\n",
            encoding="ascii",
        )
        return self.summary(folder)

    def save_analysis(self, title, snapshot):
        title = str(title or "").strip()
        if not title or len(title) > 100:
            raise RecordStoreError("记录名称必须为 1～100 个字符")
        frames = list(snapshot.get("frames") or [])
        metric_rows = list(snapshot.get("metric_rows") or [])
        if len(frames) > 32:
            raise RecordStoreError("完整频谱数量超过上限")
        if len(metric_rows) > 5000:
            raise RecordStoreError("指标行数量超过上限")
        if not frames and not metric_rows:
            raise RecordStoreError("没有可保存的实时分析数据")

        now = datetime.now().astimezone()
        record_id = "analysis_{}_{}".format(
            now.strftime("%Y%m%d_%H%M%S"), uuid.uuid4().hex[:8])
        folder = self._record_dir(record_id)
        temporary = self.root / (".tmp_analysis_" + uuid.uuid4().hex)
        temporary.mkdir(parents=False, exist_ok=False)
        run_id = record_id
        try:
            frames_dir = temporary / "frames"
            frames_dir.mkdir()
            samples = []
            for sample_index, frame in enumerate(frames, 1):
                frame_id = int(frame["frame_id"])
                stem = "frame_{:06d}".format(frame_id)
                words_path = frames_dir / (stem + "_words.npy")
                state_path = frames_dir / (stem + "_state.json")
                render_path = frames_dir / (stem + "_render.json")
                np.save(
                    words_path,
                    np.asarray(frame["words"], dtype=np.uint64),
                    allow_pickle=False,
                )
                state_path.write_text(
                    json.dumps(
                        _jsonable(frame["state"]),
                        indent=2, ensure_ascii=False, allow_nan=False,
                    ) + "\n",
                    encoding="utf-8",
                )
                render = dict(frame.get("render") or {})
                render.update({
                    "run_id": run_id,
                    "mode": "USER_RECORD",
                    "display_source": "USER_RECORD",
                    "source_mode": "LIVE",
                })
                render_path.write_text(
                    json.dumps(
                        _jsonable(render),
                        indent=2, ensure_ascii=False, allow_nan=False,
                    ) + "\n",
                    encoding="utf-8",
                )
                metrics = render.get("metrics") or {}
                peaks = metrics.get("peaks") or []
                peak = peaks[0] if peaks else {}
                samples.append({
                    "run_id": run_id,
                    "frame_id": frame_id,
                    "stem": stem,
                    "sequence": int(frame["sequence"]),
                    "elapsed_s": float(frame["elapsed_s"]),
                    "window": frame["window"],
                    "fs_hz": float(frame["fs_hz"]),
                    "N": int(frame["N"]),
                    "sample_index": sample_index,
                    "parsed_peak_hz": peak.get("frequency_hz"),
                    "parsed_peak_dbfs": peak.get("dbfs"),
                    "parsed_peak_bin": peak.get("bin"),
                    "tone_checks_passed": metrics.get("tone_checks_passed"),
                    "nonzero_bins": metrics.get("nonzero_bins"),
                    "complete_spectrum": True,
                })

            metric_path = temporary / "metric_timeline.jsonl"
            with metric_path.open("w", encoding="utf-8", newline="\n") as handle:
                for row in metric_rows:
                    normalized_row = dict(row)
                    normalized_row["run_id"] = run_id
                    normalized_row["run_label"] = title
                    handle.write(json.dumps(
                        _jsonable(normalized_row), ensure_ascii=False,
                        allow_nan=False) + "\n")

            complete = len(samples) >= 2
            record_status = (
                "INTERRUPTED" if snapshot.get("error") else
                "COMPLETE_REPLAY" if complete else
                "SINGLE_FRAME" if len(samples) == 1 else
                "METRICS_ONLY"
            )
            index = {
                "schema_version": 1,
                "source": "USER_LIVE_ANALYSIS",
                "is_demo": False,
                "run_id": run_id,
                "label": title,
                "record_status": record_status,
                "metric_rows": len(metric_rows),
                "saved_samples": len(samples),
                "samples": samples,
            }
            (temporary / "sample_index.json").write_text(
                json.dumps(index, indent=2, ensure_ascii=False,
                           allow_nan=False) + "\n",
                encoding="utf-8",
            )
            data = {
                "schema_version": 2,
                "record_id": record_id,
                "record_type": "analysis",
                "record_status": record_status,
                "title": title,
                "source": "当前实时频谱采集",
                "is_demo": False,
                "created": now.isoformat(),
                "run_id": run_id,
                "started": snapshot.get("started"),
                "stopped": snapshot.get("stopped"),
                "settings": _jsonable(snapshot.get("settings")),
                "total_frame_count": int(snapshot.get("total_frames") or 0),
                "complete_spectrum_count": len(samples),
                "metric_row_count": len(metric_rows),
                "dropped_complete_count": int(
                    snapshot.get("dropped_complete_count") or 0),
                "dropped_metric_count": int(
                    snapshot.get("dropped_metric_count") or 0),
                "recording_error": snapshot.get("error"),
            }
            record_blob = (
                json.dumps(data, indent=2, ensure_ascii=False,
                           allow_nan=False) + "\n"
            ).encode("utf-8")
            (temporary / "record.json").write_bytes(record_blob)
            (temporary / "record.sha256").write_text(
                hashlib.sha256(record_blob).hexdigest().upper() + "\n",
                encoding="ascii",
            )

            files = {}
            for path in sorted(temporary.rglob("*")):
                if path.is_file() and path.name not in (
                        "manifest.json", "record.sha256"):
                    files[path.relative_to(temporary).as_posix()] = (
                        hashlib.sha256(path.read_bytes()).hexdigest().upper())
            manifest = {
                "schema_version": 1,
                "record_id": record_id,
                "files_sha256": files,
            }
            (temporary / "manifest.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            temporary.rename(folder)
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise
        return self.summary(folder)

    def save_response(self, title, snapshot):
        title = str(title or "").strip()
        if not title or len(title) > 100:
            raise RecordStoreError("记录名称必须为 1～100 个字符")
        points = list(snapshot.get("points") or [])
        metadata = dict(snapshot.get("metadata") or {})
        response_kind = snapshot.get("response_kind") or (
            metadata.get("response_kind") or "rc_lowpass")
        if not points:
            raise RecordStoreError("没有可保存的频率响应数据")
        if len(points) < 3:
            raise RecordStoreError("至少需要三个有效频率点")
        if len(points) > 16:
            raise RecordStoreError("频率点数量超过上限")
        now = datetime.now().astimezone()
        response_prefix = (
            "response_rc" if response_kind == "rc_lowpass"
            else "response_generic")
        record_id = "{}_{}_{}".format(
            response_prefix,
            now.strftime("%Y%m%d_%H%M%S"), uuid.uuid4().hex[:8])
        folder = self._record_dir(record_id)
        temporary = self.root / (".tmp_response_" + uuid.uuid4().hex)
        temporary.mkdir(parents=False, exist_ok=False)
        try:
            raw_dir = temporary / "raw"
            raw_dir.mkdir()
            for point in points:
                frequency = int(round(point["target_hz"]))
                np.save(
                    raw_dir / ("f{:04d}_stereo.npy".format(frequency)),
                    np.asarray(point["raw_samples"], dtype=np.int32),
                    allow_pickle=False,
                )
            with (temporary / "points.csv").open(
                    "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "target_hz", "estimated_frequency_hz",
                    "gain_db", "phase_deg", "theory_gain_db",
                    "theory_phase_deg", "calibration_used", "status",
                ])
                writer.writeheader()
                for point in points:
                    writer.writerow({
                        "target_hz": point["target_hz"],
                        "estimated_frequency_hz": point["estimated_frequency_hz"],
                        "gain_db": point["H_cal_calibration_mean"]["gain_db"],
                        "phase_deg": point["H_cal_calibration_mean"]["phase_deg"],
                        "theory_gain_db": (
                            point.get("theory") or {}).get("gain_db"),
                        "theory_phase_deg": (
                            point.get("theory") or {}).get("phase_deg"),
                        "calibration_used": point["calibration_used"],
                        "status": point["status"],
                    })
            plot_points = []
            for point in points:
                plot_point = dict(point)
                plot_point.pop("raw_samples", None)
                plot_point.pop("fit", None)
                plot_points.append(plot_point)
            from rc.build_bx12 import (
                plot_generic_response, plot_measurement_summary)
            cutoff = (
                snapshot["one_pole_fit"]["cutoff_hz"]
                if snapshot.get("one_pole_fit") else None)
            if len(points) >= 3 and response_kind == "rc_lowpass":
                plot_measurement_summary(
                    temporary, plot_points,
                    snapshot.get("record_status", "USER_RESPONSE"), cutoff,
                    r_ohm=float(metadata["actual_r_ohm"]),
                    c_f=float(metadata["actual_c_f"]))
                for source_name, target_name in (
                        ("magnitude_phase.png", "gain_phase.png"),
                        ("magnitude_phase.svg", "gain_phase.svg")):
                    source = temporary / source_name
                    if source.is_file():
                        source.rename(temporary / target_name)
            elif len(points) >= 3:
                plot_generic_response(
                    temporary, plot_points,
                    snapshot.get("record_status", "GENERIC_RESPONSE"))
            record_data = {
                "schema_version": 1,
                "record_id": record_id,
                "record_type": "response",
                "response_kind": response_kind,
                "record_status": snapshot.get("record_status"),
                "title": title,
                "source": (
                    "RC 低通滤波器频率响应测量"
                    if response_kind == "rc_lowpass"
                    else "通用系统频率响应测量"),
                "is_demo": False,
                "created": now.isoformat(),
                "started": snapshot.get("started"),
                "stopped": snapshot.get("stopped"),
                "conditions": _jsonable(metadata),
                "dut": (
                    {
                        "name": metadata.get("dut_name"),
                        "model": metadata.get("dut_model"),
                        "serial": metadata.get("dut_serial"),
                    }
                    if response_kind == "generic_system" else
                    {
                        "name": "RC 低通滤波器",
                        "model": "R={}Ω C={}nF".format(
                            metadata.get("actual_r_ohm"),
                            float(metadata.get("actual_c_f") or 0) * 1e9),
                    }
                ),
                "point_count": len(points),
                "theory_cutoff_hz": snapshot.get("theory_cutoff_hz"),
                "fitted_cutoff_hz": cutoff,
                "one_pole_fit": _jsonable(snapshot.get("one_pole_fit")),
                "points": _jsonable(plot_points),
            }
            blob = (
                json.dumps(record_data, indent=2, ensure_ascii=False,
                           allow_nan=False) + "\n"
            ).encode("utf-8")
            (temporary / "record.json").write_bytes(blob)
            (temporary / "record.sha256").write_text(
                hashlib.sha256(blob).hexdigest().upper() + "\n",
                encoding="ascii",
            )
            files = {}
            for path in sorted(temporary.rglob("*")):
                if path.is_file() and path.name not in (
                        "manifest.json", "record.sha256"):
                    files[path.relative_to(temporary).as_posix()] = (
                        hashlib.sha256(path.read_bytes()).hexdigest().upper())
            (temporary / "manifest.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "record_id": record_id,
                    "files_sha256": files,
                }, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            temporary.rename(folder)
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise
        return self.summary(folder)

    def summary(self, folder):
        data = json.loads((folder / "record.json").read_text(encoding="utf-8"))
        result = {
            "record_id": data["record_id"],
            "record_type": data["record_type"],
            "title": data["title"],
            "source": data["source"],
            "created": data["created"],
        }
        for key in (
            "record_status", "complete_spectrum_count", "metric_row_count",
            "run_id", "point_count", "response_kind", "dut",
        ):
            if key in data:
                result[key] = data[key]
        return result

    def list(self, record_type=None):
        records = []
        for folder in sorted(self.root.iterdir(), reverse=True):
            if not folder.is_dir() or not (folder / "record.json").is_file():
                continue
            try:
                summary = self.summary(folder)
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if record_type and summary["record_type"] != record_type:
                continue
            records.append(summary)
        return records

    def load(self, record_id):
        folder = self._record_dir(record_id)
        path = folder / "record.json"
        if not path.is_file():
            raise RecordStoreError("记录不存在")
        data = json.loads(path.read_text(encoding="utf-8"))
        expected = (folder / "record.sha256").read_text(
            encoding="ascii").strip()
        actual = hashlib.sha256(path.read_bytes()).hexdigest().upper()
        if actual != expected:
            raise RecordStoreError("记录完整性校验失败")
        return data

    def response_download(self, record_id, download_format):
        data = self.load(record_id)
        if data.get("record_type") != "response":
            raise RecordStoreError("记录不是频率响应记录")
        formats = {
            "csv": ("points.csv", record_id + "_points.csv",
                    "text/csv; charset=utf-8"),
            "json": ("record.json", record_id + ".json",
                     "application/json; charset=utf-8"),
        }
        selected = formats.get(str(download_format or "").lower())
        if selected is None:
            raise RecordStoreError("下载格式必须为 csv 或 json")
        source_name, filename, mime = selected
        folder = self._record_dir(record_id)
        path = (folder / source_name).resolve()
        path.relative_to(folder)
        if not path.is_file():
            raise RecordStoreError("记录文件不存在")
        return path.read_bytes(), mime, filename

    def delete(self, record_id):
        folder = self._record_dir(record_id)
        if not folder.is_dir():
            raise RecordStoreError("记录不存在")
        shutil.rmtree(folder)
        return {"deleted": record_id}
