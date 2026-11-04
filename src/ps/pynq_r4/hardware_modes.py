"""Coordinate mutually exclusive FFT and M4 hardware owners in one process."""

import asyncio
import copy
import math
import queue
import re
import threading
import time
import traceback
import uuid

import numpy as np


class ModeError(RuntimeError):
    """Raised when a hardware operation is invalid for the active mode."""


class M4Worker:
    """Own M4Capture inside a dedicated worker thread and asyncio loop."""

    def __init__(self, capture_factory):
        self.capture_factory = capture_factory
        self.commands = queue.Queue(maxsize=16)
        self.thread = threading.Thread(
            target=self._worker, name="m4-hardware-owner", daemon=True)
        self.capture = None
        self.error = None
        self.thread.start()
        self.last_capture = None

    def _worker(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            while True:
                action, payload, event, result = self.commands.get()
                if action == "shutdown":
                    try:
                        if self.capture is not None:
                            self.capture.close()
                        result["value"] = {"closed": True}
                    except Exception as exc:
                        result["error"] = "{}: {}".format(type(exc).__name__, exc)
                    finally:
                        event.set()
                    break
                try:
                    result["value"] = self._command(action, payload)
                except Exception as exc:
                    self.error = traceback.format_exc()
                    result["error"] = "{}: {}".format(type(exc).__name__, exc)
                finally:
                    event.set()
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    def _command(self, action, payload):
        if action == "enter":
            if self.capture is not None:
                return self.status()
            self.capture = self.capture_factory()
            return self.status()
        if action == "configure":
            if self.capture is None:
                raise ModeError("请先进入电路测量模式")
            self.capture.configure_codec()
            fs = self.capture.measure_fs(seconds=float(payload.get("seconds", 2.0)))
            return self.status()
        if action == "selftest":
            if self.capture is None:
                raise ModeError("请先进入电路测量模式")
            label = "m4_selftest_" + uuid.uuid4().hex[:8]
            words = self.capture.capture(test=True, label=label)
            expected = np.arange(1024, dtype=np.uint64)
            if not np.array_equal(words, expected):
                raise RuntimeError("双声道计数器自检失败")
            return {
                "label": label,
                "passed": True,
                "shape": list(words.shape),
                "dtype": str(words.dtype),
            }
        if action == "capture":
            if self.capture is None:
                raise ModeError("请先进入电路测量模式")
            if not self.capture.codec_ready or self.capture.fs is None:
                raise ModeError("请先完成接口配置并测量采样率")
            label = str(payload.get("label") or (
                "m4_capture_" + time.strftime("%Y%m%d_%H%M%S")))
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", label):
                raise ValueError("label must contain only letters, digits, dot, dash and underscore")
            candidate = label
            index = 1
            while (self.capture.output / (candidate + ".npy")).exists():
                candidate = "{}_{:02d}".format(label, index)
                index += 1
            label = candidate
            samples = self.capture.capture(label=label)
            normalized = samples.astype(np.float64) / (2 ** 23)
            self.last_capture = {
                "label": label,
                "shape": list(samples.shape),
                "dtype": str(samples.dtype),
                "channel_min": samples.min(axis=1).tolist(),
                "channel_max": samples.max(axis=1).tolist(),
                "channel_rms": np.sqrt(np.mean(normalized ** 2, axis=1)).tolist(),
                "fs_hz": self.capture.fs,
                "output": str(self.capture.output),
            }
            return self.last_capture
        raise ValueError("未知的电路测量操作：" + action)

    def call(self, action, payload=None, timeout=30):
        if not self.thread.is_alive():
            raise ModeError("电路测量工作线程未运行")
        event, result = threading.Event(), {}
        self.commands.put_nowait((action, payload or {}, event, result))
        if not event.wait(timeout):
            raise TimeoutError("电路测量命令仍未完成")
        if "error" in result:
            raise ModeError(result["error"])
        return result.get("value")

    def status(self):
        capture = self.capture
        return {
            "mode": "M4",
            "loaded": capture is not None,
            "phase": "READY" if capture is not None else "NOT_ENTERED",
            "codec_ready": bool(capture and capture.codec_ready),
            "fs_hz": getattr(capture, "fs", None),
            "capture_count": len(getattr(capture, "history", [])) if capture else 0,
            "last_capture": self.last_capture,
            "unsafe": bool(getattr(capture, "_unsafe", False)) if capture else False,
            "last_error": self.error,
        }

    def close(self):
        if not self.thread.is_alive():
            return {"closed": True}
        event, result = threading.Event(), {}
        self.commands.put_nowait(("shutdown", {}, event, result))
        if not event.wait(30):
            raise TimeoutError("电路测量工作线程未能关闭")
        self.thread.join(timeout=10)
        if self.thread.is_alive():
            raise ModeError("电路测量工作线程未退出")
        if "error" in result:
            raise ModeError(result["error"])
        return result.get("value")


class HardwareModeCoordinator:
    """Single owner for the mutually exclusive FFT and M4 hardware modes."""

    def __init__(self, fft_runtime, fft_factory, m4_factory):
        self._lock = threading.RLock()
        self._fft = fft_runtime
        self._fft_factory = fft_factory
        self._m4_factory = m4_factory
        self._m4 = None
        self._fft_observers = []
        self._mode = "FFT"
        self._fault = None

    def add_fft_observer(self, observer):
        with self._lock:
            if observer not in self._fft_observers:
                self._fft_observers.append(observer)
            attach = getattr(self._fft, "add_frame_observer", None)
            if callable(attach):
                attach(observer)

    def status(self):
        if self._mode == "FFT":
            return self._fft.status()
        switched_mode = "FAULT" if self._mode == "FAULT" else "M4"
        return {
            "build_revision": "spectrum_software_1_r4_bplus",
            "mode": switched_mode,
            "source": "M4_RAW_STEREO" if switched_mode == "M4" else "HARDWARE_MODE_FAULT",
            "phase": "FAULT" if switched_mode == "FAULT" else "MODE_SWITCHED",
            "run_id": None,
            "frames": 0,
            "elapsed_s": 0,
            "snapshot_frame_rate_hz": 0,
            "cases": [],
            "settings": None,
            "browser_viewers": {},
            "completed_runs": 0,
            "stop_verified": None,
            "screenshot_count": 0,
            "screenshot_limit": 8,
            "export_ready": False,
            "latest": None,
            "error": self._fault,
            "reason": (
                "HARDWARE_MODE_FAULT" if switched_mode == "FAULT"
                else "FFT_DISABLED_WHILE_M4"),
        }

    @property
    def downloads(self):
        return getattr(self._fft, "downloads", {}) if self._fft is not None else {}

    def call(self, action, payload=None, timeout=15):
        if self._mode != "FFT":
            raise ModeError("电路测量模式激活时不能操作实时频谱")
        return self._fft.call(action, payload, timeout=timeout)

    def hardware_status(self):
        with self._lock:
            return {
                "mode": self._mode,
                "fault": self._fault,
                "fft": self._fft.status() if self._fft is not None else None,
                "m4": self._m4.status() if self._m4 is not None else None,
            }

    def fft_diagnostics(self):
        with self._lock:
            runtime = self._fft
            if runtime is None:
                return {
                    "observer_errors": [],
                    "runtime_frames": 0,
                    "runtime_phase": None,
                }
            status = runtime.status()
            return {
                "observer_errors": list(
                    getattr(runtime, "observer_errors", []))[-4:],
                "runtime_frames": int(status.get("frames") or 0),
                "runtime_phase": status.get("phase"),
            }

    def enter_m4(self):
        with self._lock:
            if self._mode == "M4":
                return self.hardware_status()
            if self._mode != "FFT" or self._fft is None:
                raise ModeError("FFT mode is not available")
            status = self._fft.status()
            if status.get("phase") in ("RUNNING", "CONFIGURING"):
                self._fft.call("stop", {}, timeout=30)
                status = self._fft.status()
                if status.get("phase") in ("RUNNING", "CONFIGURING"):
                    raise ModeError("实时频谱未安全停止，未进入电路测量模式")
            try:
                self._fft.close()
            except Exception:
                self._fault = traceback.format_exc()
                self._mode = "FAULT"
                raise
            self._fft = None
            worker = M4Worker(self._m4_factory)
            try:
                worker.call("enter", timeout=30)
            except Exception:
                self._fault = traceback.format_exc()
                self._mode = "FAULT"
                try:
                    worker.close()
                except Exception:
                    pass
                raise
            self._m4 = worker
            self._mode = "M4"
            self._fault = None
            return self.hardware_status()

    def m4_command(self, action, payload=None, timeout=30):
        with self._lock:
            if self._mode != "M4" or self._m4 is None:
                raise ModeError("当前未处于电路测量模式")
            return self._m4.call(action, payload, timeout=timeout)

    def restore_fft(self):
        with self._lock:
            if self._mode == "FFT" and self._fft is not None:
                return self.hardware_status()
            if self._m4 is not None:
                self._m4.close()
                self._m4 = None
            if self._fft_factory is None:
                raise ModeError("实时频谱运行时无法重新创建")
            try:
                self._fft = self._fft_factory()
                for observer in self._fft_observers:
                    self._fft.add_frame_observer(observer)
            except Exception:
                self._fault = traceback.format_exc()
                self._mode = "FAULT"
                raise
            self._mode = "FFT"
            self._fault = None
            return self.hardware_status()

    def close(self):
        with self._lock:
            if self._m4 is not None:
                self._m4.close()
                self._m4 = None
            if self._fft is not None:
                self._fft.close()
                self._fft = None
