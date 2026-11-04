"""Shared PL-frame adapter and bounded acquisition checks; no display framework."""
import json
from pathlib import Path

import numpy as np
from fft_delivery import N, VERSION, WINDOW_SUM, sha256, spectrum


def frame_record(words, state, mode='LIVE'):
    """B-facing frame contract; X is already restored, never run a second FFT."""
    if mode not in ('LIVE', 'REPLAY'):
        raise ValueError('mode must be LIVE or REPLAY')
    after = state['after']
    if (not state['success'] or state['source'] != 'PL_FFT' or state['N'] != N or
            after['version'] != VERSION or after['pl_status'] != 0x106 or
            after['input_count'] != N or after['output_count'] != N or after['length'] != N * 8 or
            after['window_requested'] != int(state['window']=='hann') or
            after['dmasr'] & 0x1002 != 0x1002 or after['dmasr'] & 0x4071):
        raise ValueError('Invalid PL frame metadata')
    if state['window_sum'] != WINDOW_SUM[state['window']] or state['scale_shift'] != 11:
        raise ValueError('Window/scale contract mismatch')
    data = spectrum(words, state['fs_hz'], state['window'])
    return dict(source='PL_FFT', mode=mode, X=data['complex_fft'], fs_hz=state['fs_hz'],
                N=N, window_name=state['window'], window_sum=state['window_sum'],
                sequence=after['frame_sequence'], elapsed_s=state['elapsed_s'],
                overflow=False, version=after['version'], frequency_hz=data['frequency_hz'],
                amplitude=data['amplitude'], dbfs=data['dbfs'])


def load_frame(words_path, state_path):
    """Read a saved raw frame with hash checking; no hardware is touched."""
    state = json.loads(Path(state_path).read_text(encoding='utf-8'))
    if sha256(words_path) != state['words_sha256'].lower():
        raise ValueError('Raw frame file hash mismatch')
    words = np.load(words_path, allow_pickle=False)
    return frame_record(words, state, mode='REPLAY')


def tone_observations(frame, expected_hz):
    """Report each target's neighbouring peak; physical presence also needs input evidence."""
    result = []
    for target in expected_hz:
        if not np.isfinite(target) or not 0 < target < frame['fs_hz'] / 2:
            raise ValueError('Tone frequency outside positive non-Nyquist range')
        k = int(round(target * frame['N'] / frame['fs_hz']))
        lo, hi = max(1, k - 1), min(frame['N'] // 2, k + 1)
        peak = int(lo + np.argmax(frame['amplitude'][lo:hi + 1]))
        amplitude = float(frame['amplitude'][peak])
        result.append(dict(expected_hz=float(target), peak_bin=peak,
                           peak_hz=float(frame['frequency_hz'][peak]), amplitude=amplitude,
                           dbfs=float(frame['dbfs'][peak]),
                           within_one_bin=bool(abs(frame['frequency_hz'][peak]-target) <= frame['fs_hz']/frame['N']),
                           nonzero=bool(amplitude > 0)))
    return result
