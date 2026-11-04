"""Inert-on-import sources for the same frozen PL frame adapter."""
import json
from pathlib import Path

import numpy as np

from fft_delivery import FFTCapture
from fft_session import frame_record, load_frame


class ReplaySource:
    mode = 'REPLAY'

    def __init__(self, folder):
        self.folder = Path(folder).resolve()
        self.cases = {}
        for path in sorted(self.folder.glob('*_words.npy')):
            label = path.name[:-len('_words.npy')]
            state_path = path.with_name(label + '_state.json')
            if state_path.is_file():
                state = json.loads(state_path.read_text(encoding='utf-8'))
                self.cases[label] = dict(label=label, window=state['window'], fs_hz=state['fs_hz'])
        if not self.cases:
            raise ValueError('No complete raw PL replay examples in ' + str(self.folder))
        self.current = None

    def start(self, settings):
        label = settings['replay_case']
        if label not in self.cases:
            raise ValueError('Unknown replay example')
        words_path = self.folder / (label + '_words.npy')
        state_path = self.folder / (label + '_state.json')
        frame = load_frame(words_path, state_path)
        if settings['window'] != frame['window_name']:
            raise ValueError('Replay window must match the saved PL frame')
        words = np.load(words_path, allow_pickle=False)
        words.setflags(write=False)
        state = json.loads(state_path.read_text(encoding='utf-8'))
        self.current = words, state, frame
        return dict(source='PL_FFT', mode=self.mode, fs_hz=frame['fs_hz'],
                    overlay_sha256=state['overlay_sha256'], replay_case=label,
                    original_sequence=frame['sequence'], initial=None)

    def read(self, window):
        return self.current

    def stop(self):
        return dict(stop_verified=True, hardware_access=False, final=None)


class LiveSource:
    mode = 'LIVE'

    def __init__(self, bit, driver_output, capture_factory=None):
        self.bit, self.driver_output = Path(bit), Path(driver_output)
        self.capture_factory = capture_factory or FFTCapture
        self.capture = None

    def start(self, settings):
        if self.capture is None:
            self.capture = self.capture_factory(str(self.bit), output=self.driver_output)
            self.capture.configure_codec()
            self.capture.measure_fs()
        cap = self.capture
        if cap._unsafe or cap._active_buf is not None:
            raise RuntimeError('Unsafe retained capture buffer; preserve evidence and reboot board')
        cap.quiesce()
        initial = cap.snapshot()
        return dict(source='PL_FFT', mode=self.mode, fs_hz=cap.fs, overlay_sha256=cap.hashes,
                    initial=initial, replay_case=None)

    def read(self, window):
        cap = self.capture
        words = cap.capture(window, 'spectrum_live', persist=False, verbose=False)
        state = cap.last_record
        if cap._active_buf is not None or cap.history:
            raise RuntimeError('Unexpected live DMA buffer/history retention')
        return words, state, frame_record(words, state, mode='LIVE')

    def stop(self):
        cap = self.capture
        if cap is None:
            return dict(stop_verified=True, hardware_access=False, final=None)
        if cap._unsafe:
            raise RuntimeError('Capture stop was unsafe; preserve the retained buffer and reboot board')
        try:
            cap.quiesce()
        except BaseException:
            cap._unsafe = True
            raise
        final = cap.snapshot()
        stopped = bool(final['dmasr'] & 1) and final['pl_status'] == 0x100 and cap._active_buf is None
        if not stopped:
            raise RuntimeError('Final DMA/PL stop was not verified')
        return dict(stop_verified=True, hardware_access=True, final=final)
