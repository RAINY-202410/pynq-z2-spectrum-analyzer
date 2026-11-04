"""B-X04 mean-square amplitude average and peak hold.

Only single-sided linear amplitudes are averaged. Complex FFTs are never
averaged across frames, and dBFS values are never averaged. dBFS is a display
conversion with an epsilon floor; the linear zero remains zero.
"""

import argparse
import json
import math
from collections import deque
from pathlib import Path

import numpy as np

STEP = "B-X04"
AVERAGE_LENGTHS = (8, 32)
MAX_HISTORY = 32
SPECTRUM_POINTS = 513
EPSILON = 1e-12
AVERAGE_NAME = "均方幅度平均谱"
HOLD_NAME = "峰值保持"


class SpectrumFeatureError(ValueError):
    """Raised when amplitude frames cannot form a comparable data group."""


def to_dbfs(linear, epsilon=EPSILON):
    """Convert nonnegative linear values to dBFS for display only."""
    values = np.asarray(linear, dtype=np.float64)
    if np.any(~np.isfinite(values)) or np.any(values < 0):
        raise SpectrumFeatureError("linear amplitude must be finite and nonnegative")
    return 20.0 * np.log10(np.maximum(values, float(epsilon)))


def mean_square_spectrum(amplitudes):
    """Return sqrt(mean(A_i[k]^2)) over the supplied one-sided frames."""
    arrays = [np.asarray(item, dtype=np.float64) for item in amplitudes]
    if not arrays:
        raise SpectrumFeatureError("at least one amplitude frame is required")
    if any(item.ndim != 1 or item.shape != arrays[0].shape for item in arrays):
        raise SpectrumFeatureError("amplitude frames must be one-dimensional and equal length")
    stack = np.stack(arrays, axis=0)
    if np.any(~np.isfinite(stack)) or np.any(stack < 0):
        raise SpectrumFeatureError("amplitude frames must be finite and nonnegative")
    return np.sqrt(np.mean(np.square(stack), axis=0))


def peak_hold(amplitudes):
    """Return the elementwise maximum over the supplied one-sided frames."""
    arrays = [np.asarray(item, dtype=np.float64) for item in amplitudes]
    if not arrays:
        raise SpectrumFeatureError("at least one amplitude frame is required")
    if any(item.ndim != 1 or item.shape != arrays[0].shape for item in arrays):
        raise SpectrumFeatureError("amplitude frames must be one-dimensional and equal length")
    stack = np.stack(arrays, axis=0)
    if np.any(~np.isfinite(stack)) or np.any(stack < 0):
        raise SpectrumFeatureError("amplitude frames must be finite and nonnegative")
    return np.max(stack, axis=0)


def _validate_amplitude(amplitude, points=SPECTRUM_POINTS):
    values = np.asarray(amplitude, dtype=np.float64)
    if values.ndim != 1 or values.shape[0] != points:
        raise SpectrumFeatureError("amplitude must have {} one-sided points".format(points))
    if np.any(~np.isfinite(values)) or np.any(values < 0):
        raise SpectrumFeatureError("amplitude must be finite and nonnegative")
    return values.copy()


def _frame_group(frame):
    source = str(frame.get("source", "PL_FFT"))
    mode = str(frame.get("mode", "UNSPECIFIED"))
    run_id = str(frame.get("run_id", "UNSPECIFIED"))
    window = frame.get("window_name", frame.get("window"))
    if window not in ("hann", "rect"):
        raise SpectrumFeatureError("window must be hann or rect")
    try:
        fs_hz = float(frame["fs_hz"])
        n_fft = int(frame["N"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SpectrumFeatureError("frame must contain finite fs_hz and integer N") from exc
    if not math.isfinite(fs_hz) or fs_hz <= 0 or n_fft <= 0:
        raise SpectrumFeatureError("fs_hz/N must be positive")
    return {
        "source": source,
        "mode": mode,
        "run_id": run_id,
        "window": window,
        "fs_hz": round(fs_hz, 9),
        "N": n_fft,
    }


def _frame_meta(frame):
    frame_id = frame.get("frame_id")
    if frame_id is None:
        frame_id = frame.get("sequence")
    if frame_id is None:
        raise SpectrumFeatureError("frame must contain frame_id or sequence")
    try:
        elapsed = float(frame["elapsed_s"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SpectrumFeatureError("frame must contain finite elapsed_s") from exc
    if not math.isfinite(elapsed):
        raise SpectrumFeatureError("elapsed_s must be finite")
    return {
        "frame_id": frame_id,
        "sequence": frame.get("sequence"),
        "elapsed_s": elapsed,
    }


def _range_info(records):
    if not records:
        return {
            "start_frame_id": None,
            "end_frame_id": None,
            "start_sequence": None,
            "end_sequence": None,
            "start_elapsed_s": None,
            "end_elapsed_s": None,
        }
    first, last = records[0], records[-1]
    return {
        "start_frame_id": first["meta"]["frame_id"],
        "end_frame_id": last["meta"]["frame_id"],
        "start_sequence": first["meta"]["sequence"],
        "end_sequence": last["meta"]["sequence"],
        "start_elapsed_s": first["meta"]["elapsed_s"],
        "end_elapsed_s": last["meta"]["elapsed_s"],
    }


class SpectrumAccumulator:
    """Bounded accumulator for one comparable spectrum group.

    Average uses the latest ``average_length`` observed frames. Peak hold uses
    all frames observed since reset, while only the latest ``max_history``
    amplitude arrays are retained for the average window.
    """

    def __init__(self, average_length=8, max_history=MAX_HISTORY):
        if not isinstance(max_history, int) or max_history < 1:
            raise SpectrumFeatureError("max_history must be a positive integer")
        if max_history > MAX_HISTORY:
            raise SpectrumFeatureError("max_history must not exceed {}".format(MAX_HISTORY))
        if not isinstance(average_length, int) or not 1 <= average_length <= max_history:
            raise SpectrumFeatureError("average_length must be between 1 and max_history")
        self.max_history = max_history
        self.average_length = average_length
        self.reset("initial")

    def reset(self, reason="manual_clear"):
        self._frames = deque(maxlen=self.max_history)
        self._seen = set()
        self._total_observed = 0
        self._hold = None
        self._hold_count = 0
        self._hold_start = None
        self._hold_end = None
        self._group = None
        self._last_reset_reason = reason
        return self.snapshot()

    def clear(self):
        return self.reset("manual_clear")

    def set_average_length(self, value):
        if not isinstance(value, int) or not 1 <= value <= self.max_history:
            raise SpectrumFeatureError("average_length must be between 1 and max_history")
        self.average_length = value
        return self.snapshot()

    def _key_for(self, group, meta):
        return (
            group["source"], group["mode"], group["run_id"],
            group["window"], group["fs_hz"], group["N"],
            str(meta["frame_id"]),
        )

    def add(self, frame):
        group = _frame_group(frame)
        meta = _frame_meta(frame)
        reset_reason = None
        if self._group is not None and group != self._group:
            self.reset("group_changed")
            reset_reason = "group_changed"
        if self._group is None:
            self._group = group

        key = self._key_for(group, meta)
        if key in self._seen:
            snapshot = self.snapshot()
            snapshot["duplicate_ignored"] = True
            snapshot["reset_reason"] = reset_reason
            return snapshot

        points = int(group["N"]) // 2 + 1
        amplitude = _validate_amplitude(frame["amplitude"], points)
        record = {"meta": meta, "amplitude": amplitude, "key": key}
        if len(self._frames) == self.max_history:
            old = self._frames.popleft()
            self._seen.discard(old["key"])
        self._frames.append(record)
        self._seen.add(key)
        self._total_observed += 1

        if self._hold is None:
            self._hold = amplitude.copy()
            self._hold_start = dict(meta)
        else:
            self._hold = np.maximum(self._hold, amplitude)
        self._hold_end = dict(meta)
        self._hold_count += 1

        snapshot = self.snapshot()
        snapshot["duplicate_ignored"] = False
        snapshot["reset_reason"] = reset_reason
        return snapshot

    def snapshot(self):
        if not self._frames:
            return {
                "name": AVERAGE_NAME,
                "current": None,
                "average": None,
                "hold": None,
                "group": dict(self._group) if self._group else None,
                "average_length": self.average_length,
                "max_history": self.max_history,
                "total_observed": 0,
                "stored_frames": 0,
                "hold_count": 0,
                "zero_bins": {"current": 0, "average": 0, "hold": 0},
                "display_floor_dbfs": float(20.0 * np.log10(EPSILON)),
                "method": self._method(),
                "last_reset_reason": self._last_reset_reason,
                "duplicate_ignored": False,
                "reset_reason": None,
            }

        recent = list(self._frames)[-self.average_length:]
        average_linear = mean_square_spectrum([item["amplitude"] for item in recent])
        hold_linear = self._hold.copy()
        current_record = self._frames[-1]
        current_linear = current_record["amplitude"].copy()
        average_range = _range_info(recent)
        hold_range = _range_info([
            {"meta": self._hold_start},
            {"meta": self._hold_end},
        ]) if self._hold_start and self._hold_end else _range_info([])
        return {
            "name": AVERAGE_NAME,
            "group": dict(self._group),
            "average_length": self.average_length,
            "max_history": self.max_history,
            "total_observed": self._total_observed,
            "stored_frames": len(self._frames),
            "current": {
                "name": "当前谱",
                "linear": current_linear,
                "dbfs": to_dbfs(current_linear),
                "count": 1,
                "frame_id": current_record["meta"]["frame_id"],
                "sequence": current_record["meta"]["sequence"],
                "elapsed_s": current_record["meta"]["elapsed_s"],
            },
            "average": {
                "name": AVERAGE_NAME,
                "linear": average_linear,
                "dbfs": to_dbfs(average_linear),
                "count": len(recent),
                "window": self.average_length,
                **average_range,
            },
            "hold": {
                "name": HOLD_NAME,
                "linear": hold_linear,
                "dbfs": to_dbfs(hold_linear),
                "count": self._hold_count,
                **hold_range,
            },
            "hold_count": self._hold_count,
            "zero_bins": {
                "current": int(np.count_nonzero(current_linear == 0)),
                "average": int(np.count_nonzero(average_linear == 0)),
                "hold": int(np.count_nonzero(hold_linear == 0)),
            },
            "display_floor_dbfs": float(20.0 * np.log10(EPSILON)),
            "method": self._method(),
            "last_reset_reason": self._last_reset_reason,
            "duplicate_ignored": False,
            "reset_reason": None,
        }

    def _method(self):
        return {
            "average": "sqrt(mean(A_i[k]^2)) over latest average_length actual spectra",
            "hold": "elementwise max(A_i[k]) over all observed spectra since reset",
            "complex_fft_averaging": False,
            "dbfs_averaging": False,
            "epsilon_is_plot_floor_only": True,
        }


def accumulate(frames, average_length=8, max_history=MAX_HISTORY):
    accumulator = SpectrumAccumulator(average_length, max_history)
    result = accumulator.snapshot()
    for frame in frames:
        result = accumulator.add(frame)
    return result


def plot_three_curves(snapshot, frequency_hz, output_path=None, title=None):
    """Render current/average/hold curves; import matplotlib lazily."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    frequency = np.asarray(frequency_hz, dtype=float)
    fig, ax = plt.subplots(figsize=(12, 5.4), dpi=140)
    _draw_three_curves(ax, snapshot, frequency, title)
    fig.tight_layout()
    if output_path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output, bbox_inches="tight")
        svg = output.with_suffix(".svg")
        fig.savefig(svg, bbox_inches="tight")
    plt.close(fig)
    return Path(output_path) if output_path else None


def _draw_three_curves(ax, snapshot, frequency, title=None):
    current = snapshot["current"]
    average = snapshot["average"]
    hold = snapshot["hold"]
    if current is None:
        ax.text(0.5, 0.5, "No spectra", transform=ax.transAxes, ha="center", va="center")
        return
    ax.plot(frequency, current["dbfs"], color="#0f766e", linewidth=1.4, label="Current spectrum")
    ax.plot(frequency, average["dbfs"], color="#2563eb", linewidth=1.8,
            label="Mean-square amplitude average (M={}, n={})".format(
                average["window"], average["count"]))
    ax.plot(frequency, hold["dbfs"], color="#d97706", linewidth=1.5, linestyle="--",
            label="Peak hold (n={})".format(hold["count"]))
    ax.set_xlim(0, min(5000, float(frequency[-1])))
    ax.set_ylim(-100, 0)
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Display level (dBFS)")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper right", fontsize=9)
    if title:
        ax.set_title(title, fontsize=11)
    ax.text(0.01, 0.02,
            "REPLAY / real archived PL frames | linear mean-square amplitude, not PSD/RMS",
            transform=ax.transAxes, fontsize=8, color="#475569")


def build_demo_plot(output_path):
    """Build a two-panel real-data comparison for M=8 and M=32."""
    import session_reader
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    index = json.loads((Path(__file__).resolve().parent / "reports" / "B-X02" / "sample_index.json")
                       .read_text(encoding="utf-8"))
    run = next(item for item in index["runs"] if item["label"] == "long_hann_tone1k")
    samples = [item for item in index["spectral_samples"] if item["run_id"] == run["run_id"]]
    samples.sort(key=lambda item: item["frame_id"])
    frames = []
    for sample in samples:
        frame = dict(session_reader.load_spectral_sample(sample))
        frame["run_id"] = sample["run_id"]
        frame["frame_id"] = sample["frame_id"]
        frame["elapsed_s"] = sample["elapsed_s"]
        frames.append(frame)
    frequency = np.asarray(frames[-1]["frequency_hz"], dtype=float)
    snapshots = []
    for average_length in AVERAGE_LENGTHS:
        accumulator = SpectrumAccumulator(average_length=average_length)
        for frame in frames:
            snapshot = accumulator.add(frame)
        snapshots.append(snapshot)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(15, 5.8), dpi=140, sharey=True)
    for ax, snapshot in zip(axes, snapshots):
        _draw_three_curves(
            ax, snapshot, frequency,
            title="M={} · average n={} / hold n={}".format(
                snapshot["average_length"], snapshot["average"]["count"], snapshot["hold"]["count"]),
        )
    fig.suptitle("B-X04 three-curve comparison · long_hann_tone1k · REPLAY", fontsize=13)
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight")
    fig.savefig(output.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)
    return output, snapshots


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).resolve().parent / "reports" / "B-X04" / "three_curves.png")
    args = parser.parse_args(argv)
    output, snapshots = build_demo_plot(args.out)
    summary = {
        "step": STEP,
        "output": str(output),
        "panels": [
            {
                "average_length": item["average_length"],
                "average_count": item["average"]["count"],
                "hold_count": item["hold"]["count"],
            }
            for item in snapshots
        ],
        "source": "REPLAY / long_hann_tone1k / real archived PL frames",
    }
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
