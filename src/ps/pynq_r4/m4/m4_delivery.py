"""M4 candidate v1: bounded MMIO capture for the matching patched bit/hwh.

No hardware is touched on import. Use the supplied Notebook in one kernel.
Codec sequence derived from reed-foster/pynq-audio (MIT, Copyright 2020
Reed Foster), with corrected PLL byte address and line input routing.
"""
import gc
import hashlib
import json
import shutil
import time
import zipfile
from pathlib import Path

import numpy as np

BEATS = 1024
NBYTES = BEATS * 8
CR, SR, DA, LENGTH = 0x30, 0x34, 0x48, 0x58
RUN, RESET, HALTED, IDLE, IOC = 1, 4, 1, 2, 0x1000
ERROR_MASK = 0x70
STATUS_BITS = {0: 'Halted', 1: 'Idle', 3: 'SGIncld', 4: 'DMAIntErr',
               5: 'DMASlvErr', 6: 'DMADecErr', 12: 'IOC', 14: 'ErrIRQ'}


def sha256(file):
    return hashlib.sha256(Path(file).read_bytes()).hexdigest()


def decode_status(value):
    return [name for bit, name in STATUS_BITS.items() if value & (1 << bit)]


def _wait(predicate, seconds, message):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.001)
    raise TimeoutError(message)


class M4Capture:
    def __init__(self, bit='m4.bit', output='m4_results'):
        from pynq import MMIO, Overlay
        self.bit = Path(bit).resolve()
        self.hwh = self.bit.with_suffix('.hwh')
        if not self.hwh.is_file():
            raise FileNotFoundError(str(self.hwh))
        self.hashes = {p.name: sha256(p) for p in (self.bit, self.hwh)}
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.history = []
        self.fs = None
        self.codec_ready = False
        self._active_buf = None
        self._unsafe = False
        self.ol = Overlay(str(self.bit))  # exactly once per session
        for name in ('axi_dma_0', 'axi_lite_ctrl_0', 'dbg_stat_0', 'axi_iic_0'):
            if name not in self.ol.ip_dict:
                raise RuntimeError('Missing IP: ' + name)
        def mmio(name):
            info = self.ol.ip_dict[name]
            return MMIO(info['phys_addr'], info['addr_range'])
        self.dma = mmio('axi_dma_0')
        self.ctrl = mmio('axi_lite_ctrl_0')
        self.dbg = mmio('dbg_stat_0')
        snap = int(self.dbg.read(0x08))
        if snap >> 28 != 0xA:
            raise RuntimeError('Wrong/old bitstream: packet control marker is not 0xA')
        self.quiesce()
        (self.output / 'overlay_hashes.json').write_text(
            json.dumps(self.hashes, indent=2), encoding='utf-8')
        print('Candidate protocol detected. SHA256:', self.hashes)

    def snapshot(self):
        status = int(self.dma.read(SR))
        snap = int(self.dbg.read(0x08))
        return {'dmacr': int(self.dma.read(CR)), 'dmasr': status,
                'status_names': decode_status(status),
                'length': int(self.dma.read(LENGTH)), 'snapshot': snap,
                'busy': bool(snap & 1), 'overflow': bool(snap & 2),
                'test_mode': bool(snap & 4), 'done': bool(snap & 8),
                'i2s_live': bool(snap & (1 << 25)),
                'cnt_lrclk': int(self.dbg.read(0x00)),
                'cnt_beat': int(self.dbg.read(0x04))}

    def quiesce(self):
        """Abort PL first, reset DMA, then confirm it no longer owns memory."""
        self.ctrl.write(0x00, 2)
        self.dma.write(CR, RESET)
        _wait(lambda: not (self.dma.read(CR) & RESET), 1.0,
              'DMA reset stuck; retain CMA buffer and reboot board before reuse')
        _wait(lambda: bool(self.dma.read(SR) & HALTED), 1.0,
              'DMA not halted; retain CMA buffer and reboot board before reuse')
        self.ctrl.write(0x00, 0)

    def close(self):
        """Quiesce and release this Overlay before another bitstream is loaded."""
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

    def configure_codec(self):
        """10 MHz MCLK -> 49.152 MHz PLL -> nominal 48 kHz sample clock."""
        iic = self.ol.axi_iic_0
        address = 0x3B  # seven-bit I2C address; 0x76 is the write address byte
        def write(reg, values):
            data = bytes([0x40, reg]) + bytes(values)
            sent = iic.send(address, data, len(data))
            if sent is not None and sent != len(data):
                raise IOError('Short I2C write at 0x40{:02X}'.format(reg))
        def read(reg, count):
            # AxiIIC passes the buffer directly to CFFI's unsigned char *.
            data = iic._ffi.new('unsigned char[]', count)
            sent = iic.send(address, bytes([0x40, reg]), 2)
            if sent != 2:
                raise IOError('Short I2C register-address write at 0x40{:02X}'.format(reg))
            received = iic.receive(address, data, count)
            if received != count:
                raise IOError('Short I2C read at 0x40{:02X}: {} of {} bytes'.format(
                    reg, received, count))
            return bytes(iic._ffi.buffer(data, count))
        write(0x00, [0x0E])
        pll = bytes([0x02, 0x71, 0x02, 0x3C, 0x21, 0x01])
        write(0x02, pll)  # R1 is at byte address 0x4002, not 0x4001
        deadline = time.monotonic() + 10.0
        while True:
            back = read(0x02, 6)
            if back[:5] != pll[:5] or (back[5] & 1) != 1:
                raise IOError('PLL configuration readback mismatch: ' + back.hex())
            if back[5] & 2:
                break
            if time.monotonic() > deadline:
                raise TimeoutError('Codec PLL failed to lock; inspect 10 MHz MCLK/U5')
            time.sleep(0.05)
        write(0x00, [0x0F])
        time.sleep(0.1)
        # Use the existing verified line route. Serial port is codec master.
        settings = [(0x15, 0x01), (0x19, 0x73), (0x0A, 0x5B), (0x0B, 0x0D),
                    (0x0C, 0x5B), (0x0D, 0x0D), (0x14, 0x20),
                    (0x1C, 0x21), (0x1E, 0x41), (0x23, 0xA7), (0x24, 0xA7),
                    (0x29, 0x03), (0x2A, 0x03), (0xF2, 0x01), (0xF3, 0x01),
                    (0xF9, 0x7F), (0xFA, 0x03)]
        for reg, value in settings:
            write(reg, [value])
        for reg in (0x0A, 0x0B, 0x0C, 0x0D):
            expected = dict(settings)[reg]
            if read(reg, 1)[0] != expected:
                raise IOError('Codec line-route readback failed')
        _wait(lambda: self.snapshot()['i2s_live'], 2.0,
              'PLL locked but LRCLK is absent or outside the expected range')
        self.codec_ready = True
        print('Codec PLL and line-route readback passed. PLL=', back.hex())

    def measure_fs(self, seconds=2.0):
        if not self.codec_ready:
            raise RuntimeError('Run configure_codec() first')
        t0 = time.monotonic()
        c0 = int(self.dbg.read(0x00))
        time.sleep(seconds)
        c1 = int(self.dbg.read(0x00))
        elapsed = time.monotonic() - t0
        # This counter counts BOTH LRCLK edges: two edges per stereo frame.
        self.fs = ((c1 - c0) & 0xFFFFFFFF) / (2.0 * elapsed)
        if not self.snapshot()['i2s_live']:
            raise RuntimeError('LRCLK stopped during sample-rate measurement')
        (self.output / 'sample_rate.json').write_text(
            json.dumps({'fs_estimate_hz': self.fs, 'elapsed_s': elapsed,
                        'method': 'both LRCLK edges / (2 * host elapsed time)'}, indent=2),
            encoding='utf-8')
        print('Measured fs estimate: {:.2f} Hz'.format(self.fs))
        if abs(self.fs / 48000.0 - 1.0) > 0.01:
            raise RuntimeError('Sample rate differs from 48 kHz by >1%; retain logs, do not certify')
        return self.fs

    def capture(self, test=False, label='cap', timeout=5.0):
        from pynq import allocate
        if self._unsafe:
            raise RuntimeError('DMA recovery failed earlier; reboot board, then restart Notebook')
        if not label or Path(label).name != label:
            raise ValueError('label must be a plain filename stem')
        if not test and (not self.codec_ready or self.fs is None):
            raise RuntimeError('Configure codec and measure fs before audio capture')
        self.quiesce()
        if not test and not self.snapshot()['i2s_live']:
            raise RuntimeError('Real capture requested but I2S is not live')
        record = {'label': label, 'test': bool(test), 'fs_hz': self.fs,
                  'requested_bytes': NBYTES, 'success': False, 'before': self.snapshot()}
        buf = allocate(shape=(BEATS,), dtype=np.uint64)
        self._active_buf = buf  # keep a strong reference until hardware is quiescent
        t0 = time.monotonic()
        try:
            addr = int(buf.device_address)
            record['address'] = addr
            if addr % 8 or addr >= 2**32:
                raise RuntimeError('Invalid 32-bit aligned DMA address: ' + hex(addr))
            buf[:] = np.uint64(0xD15EA5E0D15EA5E0)
            buf.flush()
            self.dma.write(SR, 0x7000)  # W1C IRQ flags, after reset
            self.dma.write(CR, RUN)
            _wait(lambda: not (self.dma.read(SR) & HALTED), 1.0, 'DMA did not run')
            self.dma.write(DA, addr)
            self.dma.write(LENGTH, NBYTES)
            self.ctrl.write(0x00, 5 if test else 1)  # ARM only after DMA setup
            deadline = time.monotonic() + timeout
            while True:
                sr = int(self.dma.read(SR))
                if sr & (ERROR_MASK | 0x4000):
                    raise RuntimeError('DMA error 0x{:08X}: {}'.format(sr, decode_status(sr)))
                if (sr & IOC) and (sr & IDLE):
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError('DMA timeout: ' + str(self.snapshot()))
                time.sleep(0.001)
            after = self.snapshot()
            record['after'] = after
            record['received_bytes'] = after['length']
            if after['length'] != NBYTES:
                raise RuntimeError('Short/oversized receive: ' + str(after['length']))
            delta = (after['cnt_beat'] - record['before']['cnt_beat']) & 0xFFFFFFFF
            if delta != BEATS or after['busy'] or not after['done'] or after['overflow']:
                raise RuntimeError('PL packet/overflow check failed: ' + str(after))
            if after['test_mode'] != bool(test):
                raise RuntimeError('Source mode mismatch')
            if not test and not after['i2s_live']:
                raise RuntimeError('Audio clock disappeared during capture')
            buf.invalidate()
            words = np.array(buf, dtype=np.uint64, copy=True)
            if test:
                if not np.array_equal(words, np.arange(BEATS, dtype=np.uint64)):
                    raise RuntimeError('Counter self-test mismatch; inspect DMA/data packing')
                result = words
            else:
                left = (words >> np.uint64(32)).astype(np.uint32).view(np.int32)
                right = (words & np.uint64(0xFFFFFFFF)).astype(np.uint32).view(np.int32)
                result = np.stack([left, right])
                if result.min() < -(1 << 23) or result.max() >= (1 << 23):
                    raise RuntimeError('Invalid 24-bit sign extension')
                if max(np.unique(left).size, np.unique(right).size) < 4:
                    raise RuntimeError('Audio is constant/zero; verify input and codec routing')
                record['channel_min'] = result.min(axis=1).tolist()
                record['channel_max'] = result.max(axis=1).tolist()
            np.save(self.output / (label + '.npy'), result)
            record['success'] = True
            return result
        except BaseException as exc:
            record['error'] = '{}: {}'.format(type(exc).__name__, exc)
            record['failure_snapshot'] = self.snapshot()
            raise
        finally:
            record['elapsed_s'] = time.monotonic() - t0
            try:
                self.quiesce()
            except BaseException as recovery_error:
                self._unsafe = True
                record['success'] = False
                record['recovery_error'] = str(recovery_error)
                # Keep buf alive; freeing memory while DMA may write is unsafe.
                self.history.append(record)
                self._save_history()
                raise RuntimeError('DMA could not stop. Buffer retained. Reboot board.') from recovery_error
            else:
                buf.freebuffer()
                self._active_buf = None
                self.history.append(record)
                self._save_history()
                print(label, 'PASS' if record['success'] else 'FAIL',
                      'bytes=', record.get('received_bytes'),
                      'seconds=', round(record['elapsed_s'], 4))

    def _save_history(self):
        (self.output / 'capture_history.json').write_text(
            json.dumps(self.history, indent=2), encoding='utf-8')

    def batch(self, count=10, prefix='cap'):
        if count < 1:
            raise ValueError('count must be positive')
        result = []
        for index in range(count):
            result.append(self.capture(label='{}_{:02d}'.format(prefix, index + 1)))
        return result

    def make_handoff(self, input_changed_confirmed=False):
        """Package only after automated tests AND a human input-change check."""
        if self._unsafe or not input_changed_confirmed:
            raise RuntimeError('First verify the external tone/volume change in the plots')
        if self.fs is None or abs(self.fs / 48000.0 - 1) > 0.01:
            raise RuntimeError('48 kHz sample-rate check missing/failed')
        if sha256(self.bit) != self.hashes[self.bit.name] or sha256(self.hwh) != self.hashes[self.hwh.name]:
            raise RuntimeError('Overlay files changed during session')
        # Require the latest ten attempts to be audio successes, without reset
        # by overlay reloading. Counter tests must have passed in this session.
        if len(self.history) < 11 or not any(r['test'] and r['success'] for r in self.history):
            raise RuntimeError('Run counter self-test and ten audio captures first')
        last = self.history[-10:]
        if any(r['test'] or not r['success'] for r in last):
            raise RuntimeError('Latest ten attempts must all be successful audio captures')
        if not (self.output / 'audio_input_check.png').is_file():
            raise RuntimeError('Save audio_input_check.png using the supplied Notebook first')
        if not (self.output / 'audio_spectrum_diagnostic.png').is_file():
            raise RuntimeError('Complete the known-tone spectrum diagnostic first')
        target = self.output.parent / 'M4_for_B'
        if target.exists():
            raise FileExistsError('Archive/rename existing M4_for_B before packaging again')
        target.mkdir()
        for source in (self.bit, self.hwh, Path(__file__).resolve()):
            shutil.copy2(source, target / source.name)
        shutil.copytree(self.output, target / 'validation')
        for name in ('README_M4.md', 'LICENSE.reed-foster.txt', 'M4_acceptance.ipynb',
                     'delivery_timing.rpt', 'delivery_clocks.rpt', 'delivery_cdc.rpt',
                     'packetizer_simulation_pass.txt'):
            source = Path(__file__).resolve().parent / name
            if not source.is_file():
                raise FileNotFoundError(str(source))
            shutil.copy2(source, target / name)
        metadata = {'status': 'BOARD_CHECKS_PASSED_WITH_MANUAL_INPUT_CONFIRMATION',
                    'fs_estimate_hz': self.fs, 'shape': [2, BEATS], 'dtype': 'int32',
                    'raw_format': 'uint64: left signed24 in high32, right signed24 in low32',
                    'snapshot_capture': True, 'continuous_between_packets': False,
                    'input_change_confirmed_by_user': True, 'overlay_sha256': self.hashes}
        (target / 'validation_summary.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        archive = target.with_suffix('.zip')
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
            for p in sorted(target.rglob('*')):
                if p.is_file():
                    z.write(p, p.relative_to(target.parent))
        print('Handoff:', archive)
        return str(archive)
