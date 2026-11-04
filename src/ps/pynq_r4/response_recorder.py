"""Multi-frequency user response measurements built from stereo M4 captures."""

import copy
from datetime import datetime
import json
import math
from pathlib import Path
import sys
import threading

import numpy as np

BPLUS_ROOT = Path(__file__).resolve().parent / "bplus"
if str(BPLUS_ROOT) not in sys.path:
    sys.path.insert(0, str(BPLUS_ROOT))

from rc.build_bx12 import fit_one_pole_model, summarize_complex_ratios
from rc.phasor_fit import fit_stereo
from rc.rc_model import DESIGN_FREQUENCIES_HZ, cutoff_hz, transfer


class ResponseRecorderError(RuntimeError):
    """Raised for invalid user frequency-response recording operations."""


class UserResponseRecorder:
    RESPONSE_KINDS = ("rc_lowpass", "generic_system")

    def __init__(self, calibration_path, max_points=16,
                 response_kind="rc_lowpass"):
        self.calibration_path = Path(calibration_path)
        self.max_points = int(max_points)
        self.response_kind = str(response_kind)
        if self.response_kind not in self.RESPONSE_KINDS:
            raise ValueError("unknown response kind")
        if not 3 <= self.max_points <= 32:
            raise ValueError("max_points must be 3..32")
        self._lock = threading.RLock()
        self._active = False
        self._started = None
        self._stopped = None
        self._metadata = None
        self._points = []
        self._error = None
        self._last_rejected = None
        self._c0 = self._load_c0()

    def _load_c0(self):
        if not self.calibration_path.is_file():
            return {}
        payload = json.loads(self.calibration_path.read_text(encoding="utf-8"))
        return {
            float(point["target_hz"]): point["C0"]
            for point in payload.get("points", [])
        }

    def start(self, metadata):
        with self._lock:
            if self._active:
                raise ResponseRecorderError("频率响应记录已经开始")
            if self._points:
                raise ResponseRecorderError("请先保存或放弃上一次响应记录")
            temperature = str(metadata.get("temperature") or "").strip()
            if not temperature:
                raise ResponseRecorderError("请填写温度")
            if self.response_kind == "rc_lowpass":
                r_ohm = float(metadata.get("actual_r_ohm"))
                c_nf = float(metadata.get("actual_c_nf"))
                if not math.isfinite(r_ohm) or r_ohm <= 0:
                    raise ResponseRecorderError("电阻必须为正数")
                if not math.isfinite(c_nf) or c_nf <= 0:
                    raise ResponseRecorderError("电容必须为正数")
                component_metadata = {
                    "actual_r_ohm": r_ohm,
                    "actual_c_f": c_nf * 1e-9,
                }
            else:
                dut_name = str(metadata.get("dut_name") or "").strip()
                if not dut_name:
                    raise ResponseRecorderError("请填写被测系统名称")
                component_metadata = {
                    "dut_name": dut_name,
                    "dut_model": str(metadata.get("dut_model") or "").strip(),
                    "dut_serial": str(metadata.get("dut_serial") or "").strip(),
                    "input_description": str(
                        metadata.get("input_description") or "").strip(),
                    "output_description": str(
                        metadata.get("output_description") or "").strip(),
                    "attenuation_note": str(
                        metadata.get("attenuation_note") or "").strip(),
                }
            self._active = True
            self._started = datetime.now().astimezone().isoformat()
            self._stopped = None
            self._metadata = {
                "response_kind": self.response_kind,
                "temperature": temperature,
                "generator": str(metadata.get("generator") or "").strip(),
                "amplitude": str(metadata.get("amplitude") or "").strip(),
                "wiring": str(metadata.get("wiring") or "").strip(),
                **component_metadata,
            }
            self._points = []
            self._error = None
            self._last_rejected = None
            return self.status()

    def add_capture(self, target_hz, samples, fs_hz, label, source_file=None):
        with self._lock:
            if not self._active:
                raise ResponseRecorderError("请先开始频率响应记录")
            if len(self._points) >= self.max_points:
                raise ResponseRecorderError("频率点数量已达到上限")
            target_hz = float(target_hz)
            if not math.isfinite(target_hz) or target_hz <= 0:
                raise ResponseRecorderError("目标频率必须为正数")
            if any(abs(item["target_hz"] - target_hz) < 0.5
                   for item in self._points):
                raise ResponseRecorderError("该目标频率已经采集")
            samples = np.asarray(samples)
            if samples.shape != (2, 1024):
                raise ResponseRecorderError("双声道数据必须是 (2, 1024)")
            fit = fit_stereo(
                samples, float(fs_hz), target_hz,
                search_span_hz=5.0, search_resolution_hz=0.01,
                source="USER_RESPONSE_M4")
            if not fit["quality"]["valid"]:
                relative_residual = fit["fit"]["relative_residual"]
                self._last_rejected = {
                    "target_hz": target_hz,
                    "label": str(label),
                    "estimated_frequency_hz": fit["estimated_frequency_hz"],
                    "frequency_offset_hz": fit["frequency_offset_hz"],
                    "relative_residual": relative_residual,
                    "reference_amplitude": fit["reference_amplitude"],
                    "output_amplitude": fit["output_amplitude"],
                    "reasons": list(fit["quality"]["reasons"]),
                }
                raise ResponseRecorderError(
                    "正弦相量估计失败："
                    "目标 {:.3f} Hz，估计 {:.3f} Hz，"
                    "相对残差 {:.4f}，原因 {}".format(
                        target_hz,
                        fit["estimated_frequency_hz"],
                        relative_residual,
                        ",".join(fit["quality"]["reasons"]),
                    ))
            raw = complex(
                fit["transfer_ratio_raw"]["real"],
                fit["transfer_ratio_raw"]["imag"],
            )
            calibration = self._c0.get(target_hz)
            if calibration:
                c0 = complex(float(calibration["real"]), float(calibration["imag"]))
                calibrated = True
            else:
                c0 = 1 + 0j
                calibrated = False
            corrected = raw / c0
            summary = summarize_complex_ratios([corrected])
            point = {
                "response_kind": self.response_kind,
                "target_hz": target_hz,
                "estimated_frequency_hz": fit["estimated_frequency_hz"],
                "label": str(label),
                "source_file": source_file,
                "raw_samples": np.asarray(samples, dtype=np.int32).copy(),
                "fit": fit,
                "calibration_used": calibrated,
                "C0": calibration,
                "H_raw": fit["transfer_ratio_raw"],
                "H_cal_calibration_mean": summary,
                "H_cal_validation_mean": copy.deepcopy(summary),
                "status": (
                    "RESPONSE_PASS" if calibrated else "RESPONSE_RAW_ONLY"),
            }
            if self.response_kind == "rc_lowpass":
                theory = complex(transfer(
                    target_hz, self._metadata["actual_r_ohm"],
                    self._metadata["actual_c_f"]))
                point["theory"] = {
                    "real": float(theory.real),
                    "imag": float(theory.imag),
                    "gain_db": 20 * math.log10(abs(theory)),
                    "phase_deg": math.degrees(
                        math.atan2(theory.imag, theory.real)),
                }
            self._points.append(point)
            self._points.sort(key=lambda item: item["target_hz"])
            self._last_rejected = None
            return self.status()

    def stop(self):
        with self._lock:
            if not self._active:
                raise ResponseRecorderError("当前没有正在进行的响应记录")
            self._active = False
            self._stopped = datetime.now().astimezone().isoformat()
            return self.status()

    def discard(self):
        with self._lock:
            self._active = False
            self._points = []
            self._metadata = None
            self._started = None
            self._stopped = None
            self._error = None
            self._last_rejected = None
            return self.status()

    def snapshot(self):
        with self._lock:
            if self._active:
                raise ResponseRecorderError("请先停止响应记录")
            if not self._points:
                raise ResponseRecorderError("没有可保存的频率响应数据")
            frequencies = [point["target_hz"] for point in self._points]
            values = [
                complex(
                    point["H_cal_calibration_mean"]["complex"]["real"],
                    point["H_cal_calibration_mean"]["complex"]["imag"],
                )
                for point in self._points
            ]
            fit = (
                fit_one_pole_model(frequencies, values)
                if self.response_kind == "rc_lowpass"
                and len(frequencies) >= 3 else None)
            required = set(DESIGN_FREQUENCIES_HZ)
            if (
                self.response_kind == "rc_lowpass"
                and required.issubset({float(value) for value in frequencies})
            ):
                record_status = "COMPLETE_FREQUENCY_RESPONSE"
            elif (
                self.response_kind == "rc_lowpass"
                and len(frequencies) >= 3
            ):
                record_status = "PARTIAL_FREQUENCY_RESPONSE"
            elif (
                self.response_kind == "generic_system"
                and len(frequencies) >= 3
            ):
                record_status = "COMPLETE_GENERIC_RESPONSE"
            else:
                record_status = "INSUFFICIENT_POINTS"
            return {
                "response_kind": self.response_kind,
                "started": self._started,
                "stopped": self._stopped,
                "metadata": copy.deepcopy(self._metadata),
                "points": copy.deepcopy(self._points),
                "one_pole_fit": fit,
                "theory_cutoff_hz": (
                    cutoff_hz(
                        self._metadata["actual_r_ohm"],
                        self._metadata["actual_c_f"])
                    if self.response_kind == "rc_lowpass" else None),
                "record_status": record_status,
            }

    def status(self):
        with self._lock:
            return {
                "response_kind": self.response_kind,
                "active": self._active,
                "started": self._started,
                "stopped": self._stopped,
                "point_count": len(self._points),
                "max_points": self.max_points,
                "frequencies_hz": [point["target_hz"] for point in self._points],
                "metadata": copy.deepcopy(self._metadata),
                "error": self._error,
                "last_rejected": copy.deepcopy(self._last_rejected),
                "can_save": not self._active and bool(self._points),
            }
