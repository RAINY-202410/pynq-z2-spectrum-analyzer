"""In-memory recorder for turning live PL frames into a replayable user record."""

import copy
from datetime import datetime
import threading

import numpy as np


class AnalysisRecorderError(RuntimeError):
    """Raised when a recording transition is invalid."""


class LiveAnalysisRecorder:
    def __init__(self, max_complete_frames=32, max_metric_rows=5000):
        self.max_complete_frames = int(max_complete_frames)
        self.max_metric_rows = int(max_metric_rows)
        if not 2 <= self.max_complete_frames <= 32:
            raise ValueError("max_complete_frames must be 2..32")
        if not 100 <= self.max_metric_rows <= 5000:
            raise ValueError("max_metric_rows must be 100..5000")
        self._lock = threading.RLock()
        self._active = False
        self._run_id = None
        self._started = None
        self._stopped = None
        self._settings = None
        self._source_status = None
        self._frames = []
        self._metrics = []
        self._total_frames = 0
        self._dropped_complete = 0
        self._dropped_metrics = 0
        self._error = None

    def start(self, status, max_complete_frames=None):
        with self._lock:
            if self._active:
                raise AnalysisRecorderError("记录已经开始")
            if self._frames or self._metrics:
                raise AnalysisRecorderError("请先保存或放弃上一次记录")
            if not isinstance(status, dict) or status.get("mode") != "LIVE":
                raise AnalysisRecorderError("只有实时频谱模式可以开始记录")
            if status.get("phase") != "RUNNING" or not status.get("run_id"):
                raise AnalysisRecorderError("请先启动实时采集，再开始记录")
            if max_complete_frames is not None:
                value = int(max_complete_frames)
                if not 2 <= value <= 32:
                    raise AnalysisRecorderError("完整频谱数量必须为 2～32")
                self.max_complete_frames = value
            self._active = True
            self._run_id = status["run_id"]
            self._started = datetime.now().astimezone().isoformat()
            self._stopped = None
            self._settings = copy.deepcopy(status.get("settings"))
            self._source_status = copy.deepcopy(status)
            self._frames = []
            self._metrics = []
            self._total_frames = 0
            self._dropped_complete = 0
            self._dropped_metrics = 0
            self._error = None
            return self.status()

    def observe(self, words, state, frame, metrics, payload, row):
        with self._lock:
            if not self._active:
                return
            run_id = payload.get("run_id")
            if run_id != self._run_id:
                self._error = "实时采集记录发生变化，记录已停止"
                self._active = False
                self._stopped = datetime.now().astimezone().isoformat()
                return
            elapsed_s = float(row["elapsed_s"])
            self._total_frames += 1
            metric = {
                "record_type": "metric",
                "run_id": run_id,
                "run_label": run_id,
                "frame_id": int(payload["frame_id"]),
                "sequence": int(payload["sequence"]),
                "elapsed_s": elapsed_s,
                "window": payload.get("window_name"),
                "fs_hz": float(payload["fs_hz"]),
                "N": int(payload["N"]),
                "metrics": copy.deepcopy(metrics),
            }
            self._metrics.append(metric)
            if len(self._metrics) > self.max_metric_rows:
                self._metrics.pop(0)
                self._dropped_metrics += 1

            record = {
                "frame_id": int(payload["frame_id"]),
                "sequence": int(payload["sequence"]),
                "elapsed_s": elapsed_s,
                "window": payload.get("window_name"),
                "fs_hz": float(payload["fs_hz"]),
                "N": int(payload["N"]),
                "words": np.asarray(words, dtype=np.uint64).copy(),
                "state": copy.deepcopy(state),
                "render": {
                    **copy.deepcopy(payload),
                    "elapsed_s": elapsed_s,
                },
                "metrics": copy.deepcopy(metrics),
            }
            self._frames.append(record)
            if len(self._frames) > self.max_complete_frames:
                self._frames.pop(0)
                self._dropped_complete += 1

    def stop(self):
        with self._lock:
            if not self._active:
                raise AnalysisRecorderError("当前没有正在进行的记录")
            self._active = False
            self._stopped = datetime.now().astimezone().isoformat()
            return self.status()

    def discard(self):
        with self._lock:
            self._active = False
            self._frames = []
            self._metrics = []
            self._total_frames = 0
            self._started = None
            self._stopped = None
            self._settings = None
            self._source_status = None
            self._error = None
            return self.status()

    def snapshot(self):
        with self._lock:
            if self._active:
                raise AnalysisRecorderError("请先停止记录再保存")
            if not self._frames and not self._metrics:
                raise AnalysisRecorderError("没有可保存的实时分析数据")
            return {
                "run_id": self._run_id,
                "started": self._started,
                "stopped": self._stopped,
                "settings": copy.deepcopy(self._settings),
                "source_status": copy.deepcopy(self._source_status),
                "frames": copy.deepcopy(self._frames),
                "metric_rows": copy.deepcopy(self._metrics),
                "total_frames": self._total_frames,
                "saved_complete_count": len(self._frames),
                "dropped_complete_count": self._dropped_complete,
                "saved_metric_count": len(self._metrics),
                "dropped_metric_count": self._dropped_metrics,
                "error": self._error,
            }

    def status(self):
        with self._lock:
            return {
                "active": self._active,
                "run_id": self._run_id,
                "started": self._started,
                "stopped": self._stopped,
                "total_frames": self._total_frames,
                "saved_complete_count": len(self._frames),
                "saved_metric_count": len(self._metrics),
                "max_complete_frames": self.max_complete_frames,
                "max_metric_rows": self.max_metric_rows,
                "dropped_complete_count": self._dropped_complete,
                "dropped_metric_count": self._dropped_metrics,
                "error": self._error,
                "can_save": not self._active and bool(self._frames or self._metrics),
            }
