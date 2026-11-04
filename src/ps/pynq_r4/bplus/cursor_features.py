"""B-X05 dual-cursor readings on actual FFT bins.

Cursor positions are integer FFT bin indices. Frequency and amplitude are
looked up from the selected curve at that exact index; display zoom never
changes the bin grid.
"""

import math

import numpy as np

from spectrum_features import to_dbfs

STEP = "B-X05"


class CursorError(ValueError):
    """Raised for invalid cursor arrays or bin indices."""


def _vector(values, name):
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or not len(array):
        raise CursorError(name + " must be a non-empty one-dimensional vector")
    if np.any(~np.isfinite(array)):
        raise CursorError(name + " must be finite")
    return array


def nearest_bin(frequency_hz, target_hz):
    """Return the actual FFT bin nearest to target_hz."""
    frequency = _vector(frequency_hz, "frequency_hz")
    if not math.isfinite(float(target_hz)):
        raise CursorError("target_hz must be finite")
    distances = np.abs(frequency - float(target_hz))
    return int(np.argmin(distances))


def cursor_reading(frequency_hz, linear, bin_index, curve="current"):
    """Return bin/frequency/linear/dBFS for one exact bin."""
    frequency = _vector(frequency_hz, "frequency_hz")
    amplitude = _vector(linear, "linear")
    if frequency.shape != amplitude.shape:
        raise CursorError("frequency and linear arrays must have equal shape")
    if type(bin_index) is not int or not 0 <= bin_index < len(frequency):
        raise CursorError("bin_index is outside the actual FFT grid")
    return {
        "curve": str(curve),
        "bin": bin_index,
        "frequency_hz": float(frequency[bin_index]),
        "linear": float(amplitude[bin_index]),
        "dbfs": float(to_dbfs(np.array([amplitude[bin_index]]))[0]),
    }


def dual_cursor_delta(a, b):
    """Compute f_B-f_A, L_B-L_A, and linear ratio when applicable."""
    for item in (a, b):
        if not isinstance(item, dict) or not {"frequency_hz", "linear", "dbfs"} <= set(item):
            raise CursorError("cursor readings must contain frequency_hz, linear and dbfs")
    if not all(math.isfinite(float(item[key])) for item in (a, b)
               for key in ("frequency_hz", "linear", "dbfs")):
        raise CursorError("cursor readings must be finite")
    same_curve = a.get("curve") == b.get("curve")
    a_linear = float(a["linear"])
    b_linear = float(b["linear"])
    ratio = None
    ratio_db = None
    if same_curve and a_linear > 0 and b_linear > 0:
        ratio = b_linear / a_linear
        ratio_db = 20.0 * math.log10(ratio)
    return {
        "delta_f_hz": float(b["frequency_hz"]) - float(a["frequency_hz"]),
        "delta_dbfs": float(b["dbfs"]) - float(a["dbfs"]),
        "ratio": ratio,
        "ratio_db": ratio_db,
        "same_curve": same_curve,
        "ratio_applicable": ratio is not None,
    }
