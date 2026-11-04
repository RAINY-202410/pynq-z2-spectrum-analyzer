"""Display and acceptance measurements on decoded PL spectra; never recompute an FFT."""
import math

import numpy as np

from fft_session import tone_observations


def analyse_frame(frame, expected_tones=()):
    amplitude = np.asarray(frame['amplitude'], dtype=float)
    frequency = np.asarray(frame['frequency_hz'], dtype=float)
    if (frame['source'] != 'PL_FFT' or frame['mode'] not in ('LIVE', 'REPLAY')
            or frame['N'] != 1024 or amplitude.shape != (513,)
            or not np.all(np.isfinite(amplitude)) or np.any(amplitude < 0)
            or frequency.shape != (513,) or not np.all(np.isfinite(frequency))):
        raise ValueError('Invalid decoded PL spectrum')
    fs = float(frame['fs_hz'])
    if not math.isfinite(fs) or fs <= 0 or not np.allclose(frequency, np.arange(513) * fs / 1024, rtol=0, atol=1e-9):
        raise ValueError('Frequency axis differs from measured sample rate')
    candidates = [k for k in range(1, 513) if amplitude[k] > 0
                  and (k == 1 or amplitude[k] >= amplitude[k - 1])
                  and (k == 512 or amplitude[k] > amplitude[k + 1])]
    peaks = []
    for k in sorted(candidates, key=lambda i: float(amplitude[i]), reverse=True):
        if any(abs(k - p['bin']) < 3 for p in peaks):
            continue
        estimate = float(frequency[k])
        interpolated = False
        if 1 <= k < 512 and np.all(amplitude[k - 1:k + 2] > 0):
            a, b, c = np.log(amplitude[k - 1:k + 2])
            denominator = a - 2 * b + c
            if denominator < 0:
                delta = float(np.clip(0.5 * (a - c) / denominator, -0.5, 0.5))
                estimate = (k + delta) * fs / 1024
                interpolated = True
        peaks.append(dict(bin=k, frequency_hz=float(frequency[k]),
                          estimated_frequency_hz=estimate, interpolated=interpolated,
                          amplitude=float(amplitude[k]), dbfs=float(20 * np.log10(max(amplitude[k], 1e-12)))))
        if len(peaks) == 3:
            break
    top = float(np.max(amplitude[1:]))
    observations = tone_observations(frame, expected_tones)
    for tone in observations:
        tone['relative_peak_db'] = float(20 * np.log10(max(tone['amplitude'] / top, 1e-12))) if top else -240.0
        tone['above_relative_floor'] = bool(top > 0 and tone['amplitude'] >= top * 0.05)
    quality = all(t['nonzero'] and t['within_one_bin'] and t['above_relative_floor'] for t in observations)
    if observations:
        quality = quality and bool(peaks) and any(abs(peaks[0]['frequency_hz'] - t['expected_hz']) <= fs / 1024 for t in observations)
    return dict(peaks=peaks, tones=observations, tone_checks_passed=bool(quality),
                relative_tone_floor_db=float(20 * np.log10(0.05)),
                max_nondc_dbfs=float(20 * np.log10(max(top, 1e-12))),
                nonzero_bins=int(np.count_nonzero(amplitude)), amplitude_calibrated=False,
                bin_width_hz=fs / 1024)


def public_frame(frame, metrics):
    """Finite JSON payload; original full complex values remain in raw evidence."""
    return dict(source='PL_FFT', mode=frame['mode'], sequence=int(frame['sequence']),
                fs_hz=float(frame['fs_hz']), N=1024, window_name=frame['window_name'],
                window_sum=float(frame['window_sum']), version=int(frame['version']),
                frequency_hz=np.asarray(frame['frequency_hz']).tolist(),
                amplitude=np.asarray(frame['amplitude']).tolist(), dbfs=np.asarray(frame['dbfs']).tolist(),
                metrics=metrics)
