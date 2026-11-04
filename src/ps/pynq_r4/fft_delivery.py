"""FFT v1 board candidate. Import is inert; capture uses the PL FFT, no CPU FFT.

Codec configuration and fs measurement reuse the corrected M4 implementation.
One snapshot per START; frames need not be contiguous in audio time.
"""
import gc
import json
import time
from pathlib import Path

import numpy as np
from m4_delivery import (M4Capture, CR, SR, DA, LENGTH, RUN, RESET, HALTED,
                         IDLE, IOC, ERROR_MASK, decode_status, sha256, _wait)
from fft_contract_assets import unpack_complex

N, NBYTES, VERSION = 1024, 8192, 0x46465401
CAPTURE_API_VERSION = 2  # Adds optional lightweight capture; FPGA contract stays v1.0.
PL_ERRORS = 0x2F8  # input/FFT overflow, TLAST, ignored START, ABORT
WINDOW_SUM = {'rect': 1024.0, 'hann': 511.50006103515625}


def spectrum(words, fs, window):
    """Restore the frozen Q1.15/S=11 scale once and form a one-sided amplitude."""
    if window not in WINDOW_SUM or not np.isfinite(fs) or fs <= 0:
        raise ValueError('Expected rect/hann and a positive measured fs')
    data = np.asarray(words)
    if data.shape != (N,) or data.dtype.kind != 'u' or data.dtype.itemsize != 8:
        raise ValueError('Expected 1024 uint64 hardware words')
    real, imag = unpack_complex(data)
    full = (real.astype(np.float64) + 1j * imag) * (2048.0 / 32768.0)
    amplitude = np.abs(full[:513]) / WINDOW_SUM[window]
    amplitude[1:-1] *= 2.0
    return {'complex_fft': full, 'frequency_hz': np.arange(513) * fs / N,
            'amplitude': amplitude, 'dbfs': 20 * np.log10(np.maximum(amplitude, 1e-12))}


class FFTCapture:
    configure_codec = M4Capture.configure_codec
    measure_fs = M4Capture.measure_fs

    def __init__(self, bit='fft.bit', output='fft_results'):
        from pynq import MMIO, Overlay
        self.bit = Path(bit).resolve()
        self.hwh = self.bit.with_suffix('.hwh')
        self.hashes = {p.name: sha256(p) for p in (self.bit, self.hwh)}
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.history, self.fs, self.codec_ready = [], None, False
        self.last_record = None
        self._active_buf, self._unsafe = None, False
        self.ol = Overlay(str(self.bit))
        for name in ('axi_dma_0', 'fft_ctrl_0', 'dbg_stat_0', 'axi_iic_0'):
            if name not in self.ol.ip_dict:
                raise RuntimeError('Missing FFT overlay IP: ' + name)
        def mmio(name):
            info = self.ol.ip_dict[name]
            return MMIO(info['phys_addr'], info['addr_range'])
        self.dma, self.ctrl, self.dbg = map(mmio, ('axi_dma_0', 'fft_ctrl_0', 'dbg_stat_0'))
        if int(self.ctrl.read(0x10)) != VERSION or int(self.ctrl.read(0x0C)) != N:
            raise RuntimeError('FFT VERSION/LENGTH mismatch; check matching bit/hwh')
        self.quiesce()
        self._save('overlay_hashes.json', self.hashes)

    def _save(self, name, data):
        (self.output / name).write_text(json.dumps(data, indent=2), encoding='utf-8')

    def snapshot(self):
        sr, status = int(self.dma.read(SR)), int(self.ctrl.read(0x08))
        raw = int(self.dbg.read(0x08))
        return {'dmacr': int(self.dma.read(CR)), 'dmasr': sr,
                'dma_status_names': decode_status(sr), 'length': int(self.dma.read(LENGTH)),
                'pl_status': status, 'input_count': int(self.ctrl.read(0x14)),
                'output_count': int(self.ctrl.read(0x18)), 'frame_sequence': int(self.ctrl.read(0x1C)),
                'window_requested': int(self.ctrl.read(0x04)), 'version': int(self.ctrl.read(0x10)),
                'i2s_snapshot': raw, 'i2s_live': bool(raw & (1 << 25)),
                'cnt_lrclk': int(self.dbg.read(0x00)), 'cnt_beat': int(self.dbg.read(0x04))}

    def quiesce(self):
        """Stop PL before DMA; failed stop retains any live CMA buffer."""
        self.ctrl.write(0x00, 2)
        self.dma.write(CR, RESET)
        _wait(lambda: not (self.dma.read(CR) & RESET), 1.0, 'DMA reset stuck')
        _wait(lambda: bool(self.dma.read(SR) & HALTED), 1.0, 'DMA not halted')
        _wait(lambda: (self.ctrl.read(0x08) & 0x101) == 0x100, 1.0,
              'FFT did not reconfigure after ABORT')
        self.ctrl.write(0x00, 4)

    def close(self):
        """Quiesce and release the FFT Overlay before loading another bitstream."""
        if self._active_buf is not None:
            raise RuntimeError("DMA buffer is still retained; reboot before switching Overlay")
        if self._unsafe:
            raise RuntimeError("Previous DMA stop was unsafe; reboot before switching Overlay")
        self.quiesce()
        self.ol = None
        self.dma = None
        self.ctrl = None
        self.dbg = None
        gc.collect()

    def _record_capture(self, record, persist, verbose):
        self.last_record = record
        if persist:
            self.history.append(record)
            self._save('capture_history.json', self.history)
            self._save(record['label'] + '_state.json', record)
        if verbose:
            print(record['label'], 'PASS' if record['success'] else 'FAIL', record.get('received_bytes'))

    def capture(self, window='rect', label='frame', timeout=5.0, persist=True, verbose=True):
        """Capture one frame; persist=False updates last_record without growing history/files."""
        from pynq import allocate
        if self._unsafe or self._active_buf is not None:
            raise RuntimeError('Unreleased DMA buffer; reboot board before reuse')
        if window not in WINDOW_SUM or not label or Path(label).name != label:
            raise ValueError('Expected rect/hann and a plain filename label')
        if persist and (self.output / (label + '_words.npy')).exists():
            raise FileExistsError('Use a fresh label to preserve earlier captures')
        if not self.codec_ready or self.fs is None or not self.snapshot()['i2s_live']:
            raise RuntimeError('Configure codec and measure fs before capture')
        if self.ctrl.read(0x08) & 1:
            raise RuntimeError('PL busy; recover before starting another frame')
        self.ctrl.write(0x00, 4)
        self.ctrl.write(0x04, int(window == 'hann'))
        before = self.snapshot()
        if before['pl_status'] != 0x100 or before['window_requested'] != int(window == 'hann'):
            raise RuntimeError('CLEAR/config/window readback mismatch: ' + str(before))
        record = {'label': label, 'source': 'PL_FFT', 'window': window, 'N': N,
                  'fs_hz': self.fs, 'window_sum': WINDOW_SUM[window], 'scale_shift': 11,
                  'requested_bytes': NBYTES, 'before': before, 'success': False,
                  'overlay_sha256': self.hashes}
        buf = allocate(shape=(N,), dtype=np.uint64)
        self._active_buf = buf
        started = time.monotonic()
        dma_complete = False
        try:
            address = int(buf.device_address)
            if address % 8 or address < 0 or address + NBYTES > 2**32:
                raise RuntimeError('Invalid DMA address: ' + hex(address))
            buf[:] = np.uint64(0xD15EA5E0D15EA5E0)
            buf.flush()
            armed_at = time.monotonic()
            self.dma.write(SR, 0x7000)
            self.dma.write(CR, RUN)
            _wait(lambda: not (self.dma.read(SR) & HALTED), 1.0, 'DMA did not run')
            self.dma.write(DA, address)
            self.dma.write(LENGTH, NBYTES)
            self.ctrl.write(0x00, 1)  # START only after receive is armed
            deadline = time.monotonic() + timeout
            while True:
                sr, pl = int(self.dma.read(SR)), int(self.ctrl.read(0x08))
                if sr & (ERROR_MASK | 0x4000) or pl & PL_ERRORS:
                    raise RuntimeError('DMA/PL error: ' + str(self.snapshot()))
                if sr & IOC and sr & IDLE and (pl & 0x107) == 0x106:
                    dma_complete = True
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError('Frame timeout: ' + str(self.snapshot()))
                time.sleep(0.001)
            record['arm_through_completion_s'] = time.monotonic() - armed_at
            after = self.snapshot()
            record['after'] = after
            if (after['length'] != NBYTES or after['input_count'] != N or
                    after['output_count'] != N or after['pl_status'] != 0x106 or
                    after['frame_sequence'] != ((before['frame_sequence'] + 1) & 0xFFFFFFFF) or
                    not after['i2s_live']):
                raise RuntimeError('Frame/sequence/clock validation failed: ' + str(after))
            copy_at = time.monotonic()
            buf.invalidate()
            words = np.array(buf, dtype='<u8', copy=True)
            record['buffer_copy_s'] = time.monotonic() - copy_at
            decode_at = time.monotonic()
            decoded = spectrum(words, self.fs, window)  # also validates sign extension
            record['decode_s'] = time.monotonic() - decode_at
            save_at = time.monotonic()
            if persist:
                np.save(self.output / (label + '_words.npy'), words, allow_pickle=False)
                np.save(self.output / (label + '_fft.npy'), decoded['complex_fft'], allow_pickle=False)
            peak = int(np.argmax(decoded['amplitude'][1:]) + 1)
            record.update(success=True, received_bytes=after['length'], peak_bin=peak,
                          peak_hz=float(decoded['frequency_hz'][peak]),
                          peak_dbfs=float(decoded['dbfs'][peak]))
            if persist:
                record['words_sha256'] = sha256(self.output / (label + '_words.npy'))
            record['artifact_save_s'] = time.monotonic() - save_at if persist else 0.0
            return words
        except BaseException as exc:
            record['error'] = '{}: {}'.format(type(exc).__name__, exc)
            record['failure_snapshot'] = self.snapshot()
            raise
        finally:
            record['elapsed_s'] = time.monotonic() - started
            # Completion proves DMA idle. All other exits must stop it before freeing CMA.
            try:
                if not dma_complete or not record['success']:
                    self.quiesce()
            except BaseException as recovery_error:
                self._unsafe = True
                record.update(success=False, recovery_error=str(recovery_error), buffer_retained=True)
                self._record_capture(record, persist, verbose)
                raise RuntimeError('DMA stop failed; buffer retained. Reboot board.') from recovery_error
            else:
                buf.freebuffer()
                self._active_buf = None
                self._record_capture(record, persist, verbose)

    def batch(self, count=10, window='hann', prefix='repeat'):
        return [self.capture(window, '{}_{:02d}'.format(prefix, i + 1)) for i in range(count)]
