"""Single-owner hardware worker. HTTP/UI threads never operate MMIO."""
import asyncio
import copy
import math
import os
from pathlib import Path
import platform
import queue
import sys
import threading
import time
import traceback
import uuid
import zipfile

import numpy as np

from spectrum_analysis import analyse_frame, public_frame
from spectrum_recording import APP_REVISION, BUILD_REVISION, Recorder, save_json, sha256
from spectrum_sources import LiveSource, ReplaySource


def validated_settings(data, cases):
    window = data.get('window', 'hann')
    duration = float(data.get('duration_s', 620))
    target = float(data.get('target_hz', 5))
    max_frames = data.get('max_frames', min(20000, int(math.ceil(duration * target)) + 1)) if math.isfinite(duration * target) else 0
    save_every, max_saved = data.get('save_every', 250), data.get('max_saved_frames', 32)
    scenario = data.get('scenario', 'observe')
    scenarios = {'observe': [], 'tone1k': [1000.0], 'dual': [1000.0, 3000.0], 'silence': []}
    if scenario not in scenarios:
        raise ValueError('Unknown test scenario')
    expected = [float(v) for v in data.get('expected_tones_hz', scenarios[scenario])]
    if scenario != 'observe' and expected != scenarios[scenario]:
        raise ValueError('Tone targets do not match the declared scenario')
    if (window not in ('rect', 'hann') or not math.isfinite(duration) or not 0.1 <= duration <= 3600
            or not math.isfinite(target) or not 1 <= target <= 10
            or type(max_frames) is not int or not 1 <= max_frames <= 20000
            or type(save_every) is not int or not 1 <= save_every <= 20000
            or type(max_saved) is not int or not 2 <= max_saved <= 32
            or len(expected) > 3 or any(not math.isfinite(x) or not 0 < x < 23000 for x in expected)):
        raise ValueError('Invalid bounded run settings')
    case = data.get('replay_case')
    if cases and case not in cases:
        raise ValueError('Select a saved replay example')
    return dict(window=window, duration_s=duration, target_hz=target, max_frames=max_frames,
                save_every=save_every, max_saved_frames=max_saved, expected_tones_hz=expected,
                replay_case=case, scenario=scenario)


class SpectrumRuntime:
    def __init__(self, mode, output, replay_folder=None, bit='fft.bit', capture_factory=None, context=None, software_identity=None):
        if mode not in ('LIVE', 'REPLAY'):
            raise ValueError('Unknown source mode')
        if capture_factory is not None and context != 'HOST_TEST_DRIVER':
            raise ValueError('Injected drivers must be labelled HOST_TEST_DRIVER')
        self.mode = mode
        self.instance_id = 'instrument_' + uuid.uuid4().hex[:12]
        self.software_identity = software_identity or dict(verified=False, context='SOURCE_TREE_DEVELOPMENT')
        self.context = context or ('BOARD_LIVE' if mode == 'LIVE' else 'PL_REPLAY_NOT_BOARD_ACCEPTANCE')
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.source = (ReplaySource(replay_folder) if mode == 'REPLAY'
                       else LiveSource(bit, self.output / 'driver_metadata', capture_factory))
        self.cases = self.source.cases if mode == 'REPLAY' else {}
        self.lock = threading.RLock()
        self.commands = queue.Queue(maxsize=32)
        self.stop_requested = threading.Event()
        self.exit_requested = False
        self.recorder = None
        self.runs = []
        self.latest = None
        self.phase, self.error, self.reason = 'IDLE', None, None
        self.next_due = 0
        self.downloads = {}
        self.frame_observers = []
        self.observer_errors = []
        self.thread = threading.Thread(target=self._worker, name='spectrum-hardware-owner', daemon=True)
        self.thread.start()

    def add_frame_observer(self, observer):
        if not callable(observer):
            raise ValueError('frame observer must be callable')
        with self.lock:
            if observer not in self.frame_observers:
                self.frame_observers.append(observer)

    def status(self):
        with self.lock:
            recorder = self.recorder
            elapsed = (recorder.summary['elapsed_s'] if recorder and recorder.closed else recorder.elapsed() if recorder else 0)
            frames = recorder.frames if recorder else 0
            data = dict(app_revision=APP_REVISION, build_revision=BUILD_REVISION, process_id=os.getpid(),
                        software_identity=self.software_identity, mode=self.mode, source='PL_FFT', context=self.context,
                        phase=self.phase, error=self.error, reason=self.reason,
                        run_id=recorder.folder.name if recorder else None, frames=frames, elapsed_s=elapsed,
                        snapshot_frame_rate_hz=frames / elapsed if elapsed else 0,
                        cases=list(self.cases.values()), settings=recorder.settings if recorder else None,
                        source_info=recorder.source_info if recorder else None,
                        browser_viewers=recorder.viewers if recorder else {},
                        stop_verified=recorder.summary['stop']['stop_verified'] if recorder and recorder.closed else None,
                        export_ready=bool(recorder and recorder.closed), continuous_audio=False,
                        amplitude_calibrated=False, board_accepted=False, queue_capacity=32,
                        screenshot_count=len(recorder.snapshots) if recorder else 0, screenshot_limit=8)
            data['completed_runs'] = sum(r.closed for r in self.runs)
            if self.latest:
                data['latest'] = self.latest
                data['frame_age_s'] = max(0, recorder.elapsed() - self.latest['published_elapsed_s'])
            else:
                data['latest'] = None
                data['frame_age_s'] = None
            return copy.deepcopy(data)

    def call(self, action, payload=None, timeout=15):
        if not self.thread.is_alive():
            raise RuntimeError('Hardware worker is not running')
        if action in ('stop', 'shutdown'):
            self.stop_requested.set()
        event, result = threading.Event(), {}
        try:
            self.commands.put_nowait((action, payload or {}, event, result))
        except queue.Full:
            raise RuntimeError('Command queue is full; wait for current operation')
        if not event.wait(timeout):
            raise TimeoutError('Worker command still pending; do not start another acquisition')
        if 'error' in result:
            raise RuntimeError(result['error'])
        return result.get('value')

    def close(self):
        self.call('shutdown')
        self.thread.join(timeout=10)
        if self.thread.is_alive():
            raise RuntimeError('Worker did not stop')

    def _start(self, payload):
        if self.phase in ('RUNNING', 'CONFIGURING'):
            raise RuntimeError('Stop the current run before starting another')
        if len(self.runs) >= 32:
            raise RuntimeError('32-run session limit reached; export results and restart this service')
        settings = validated_settings(payload, self.cases)
        with self.lock:
            self.phase, self.error, self.reason = 'CONFIGURING', None, None
        self.stop_requested.clear()
        try:
            info = self.source.start(settings)
            info['software_identity'] = self.software_identity
            info['instance_id'] = self.instance_id
            info['environment'] = dict(python=sys.version, numpy=np.__version__, system=platform.system(),
                                       kernel=platform.release(), pynq=getattr(sys.modules.get('pynq'), '__version__', None))
            recorder = Recorder(self.output, settings, info, self.context)
        except Exception:
            error = traceback.format_exc()
            try:
                stop = self.source.stop()
            except Exception:
                stop = dict(stop_verified=False, error=traceback.format_exc())
            save_json(self.output / ('startup_error_' + uuid.uuid4().hex[:12] + '.json'),
                      dict(context=self.context, mode=self.mode, error=error, stop=stop, settings=settings))
            with self.lock:
                self.phase, self.error, self.reason = 'ERROR', error, 'CONFIGURATION_FAILED'
            raise
        with self.lock:
            self.recorder, self.latest = recorder, None
            self.runs.append(recorder)
            self.phase = 'RUNNING'
            self.next_due = time.monotonic()
        return dict(run_id=recorder.folder.name, phase='RUNNING')

    def _finish(self, reason, error=None):
        recorder = self.recorder
        if recorder is None or recorder.closed:
            return
        try:
            stop = self.source.stop()
        except Exception:
            reason = 'FAILED'
            stop = dict(stop_verified=False, error=traceback.format_exc())
            error = (error or '') + '\nSTOP FAILURE: ' + stop['error']
        try:
            with self.lock:
                recorder.finish(reason, stop, error)
        except Exception:
            error = (error or '') + '\nEVIDENCE SAVE FAILURE: ' + traceback.format_exc()
            reason = 'FAILED'
            recorder.frames_log.close()
            recorder.render_log.close()
        with self.lock:
            self.phase = 'ERROR' if reason == 'FAILED' else 'IDLE'
            self.reason, self.error = reason, error

    def _tick(self):
        recorder = self.recorder
        if self.stop_requested.is_set():
            self._finish('STOP_REQUESTED')
            return
        if recorder.elapsed() >= recorder.settings['duration_s']:
            self._finish('DURATION_COMPLETE')
            return
        if recorder.frames >= recorder.settings['max_frames']:
            self._finish('FRAME_LIMIT')
            return
        if time.monotonic() < self.next_due:
            return
        started = time.monotonic()
        try:
            words, state, frame = self.source.read(recorder.settings['window'])
            capture_s = time.monotonic() - started
            if self.mode == 'LIVE':
                expected_sequence = (recorder.source_info['initial']['frame_sequence'] + recorder.frames + 1) & 0xffffffff
                if frame['sequence'] != expected_sequence:
                    raise RuntimeError('Live sequence discontinuity; check for another acquisition owner')
            analysis_at = time.monotonic()
            metrics = analyse_frame(frame, recorder.settings['expected_tones_hz'])
            payload = public_frame(frame, metrics)
            analysis_s = time.monotonic() - analysis_at
            with self.lock:
                row = recorder.record(words, state, frame, metrics, capture_s, analysis_s)
                payload.update(frame_id=recorder.frames, run_id=recorder.folder.name,
                               elapsed_s=row['elapsed_s'],
                               capture_call_s=capture_s, analysis_s=analysis_s,
                               published_elapsed_s=recorder.elapsed(), frame_elapsed_s=row['elapsed_s'])
                self.latest = payload
                for observer in list(self.frame_observers):
                    try:
                        observer(words, state, frame, metrics, payload, row)
                    except Exception:
                        self.observer_errors.append(traceback.format_exc())
                        del self.observer_errors[:-16]
            if not metrics['tone_checks_passed']:
                raise RuntimeError('Declared tone check failed; verify actual playback/input')
            self.next_due = max(self.next_due + 1 / recorder.settings['target_hz'], time.monotonic())
        except Exception:
            self._finish('FAILED', traceback.format_exc())

    def _command(self, action, payload):
        if action == 'start':
            return self._start(payload)
        if action == 'stop':
            self._finish('STOP_REQUESTED')
            return self.status()
        if action == 'render':
            with self.lock:
                if not self.recorder or payload.get('run_id') != self.recorder.folder.name:
                    return dict(accepted=False)
                return dict(accepted=self.recorder.render(payload))
        if action == 'screenshot':
            with self.lock:
                if not self.recorder or payload.get('run_id') != self.recorder.folder.name:
                    raise ValueError('Screenshot run does not match')
                return dict(file=self.recorder.screenshot(payload))
        if action == 'export':
            if not self.recorder:
                raise ValueError('No completed run to export')
            archive = self.recorder.export()
            self.downloads[archive.name] = archive
            while len(self.downloads) > 16:
                self.downloads.pop(next(iter(self.downloads)))
            return dict(file=archive.name, url='/downloads/' + archive.name)
        if action == 'export-session':
            if not self.runs or self.phase in ('RUNNING', 'CONFIGURING') or any(not r.closed for r in self.runs):
                raise RuntimeError('Stop acquisition before exporting this session')
            name = 'spectrum_session_' + self.instance_id.split('_')[1]
            index = 1
            while (self.output / (name + '_export{:02d}.zip'.format(index))).exists():
                index += 1
            archive = self.output / (name + '_export{:02d}.zip'.format(index))
            inner = [r.export() for r in self.runs]
            manifest = dict(app_revision=APP_REVISION, context=self.context, mode=self.mode,
                            instance_id=self.instance_id, runs=[r.folder.name for r in self.runs],
                            files_sha256={'runs/' + p.name: sha256(p) for p in inner}, board_accepted=False)
            import json
            with zipfile.ZipFile(archive, 'x', zipfile.ZIP_STORED) as z:
                for path in inner:
                    z.write(path, name + '/runs/' + path.name)
                z.writestr(name + '/session_manifest.json', json.dumps(manifest, indent=2))
            with zipfile.ZipFile(archive) as z:
                if z.testzip() is not None:
                    raise RuntimeError('Session ZIP CRC failure')
            self.downloads[archive.name] = archive
            while len(self.downloads) > 16:
                self.downloads.pop(next(iter(self.downloads)))
            return dict(file=archive.name, url='/downloads/' + archive.name, runs=len(inner))
        if action == 'shutdown':
            self._finish('STOP_REQUESTED')
            cap = getattr(self.source, 'capture', None)
            if self.context == 'BOARD_LIVE' and cap is not None and cap._unsafe:
                self.stop_requested.clear()
                raise RuntimeError('Unsafe stop: process retains DMA ownership; reboot board before closing')
            if cap is not None:
                try:
                    self.source.stop()
                    cap.close()
                except BaseException:
                    self.stop_requested.clear()
                    raise RuntimeError('Cannot release hardware safely; reboot before loading M4')
            self.exit_requested = True
            return dict(closed=True)
        raise ValueError('Unknown command')

    def _worker(self):
        # PYNQ's XrtDevice calls get_event_loop during Overlay initialization.
        # The hardware owner needs its own loop before creating any PYNQ objects.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            self._worker_commands()
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    def _worker_commands(self):
        while not self.exit_requested:
            if self.phase == 'RUNNING':
                self._tick()
            try:
                action, payload, event, result = self.commands.get(timeout=0.01 if self.phase == 'RUNNING' else 0.1)
            except queue.Empty:
                continue
            try:
                result['value'] = self._command(action, payload)
            except Exception as error:
                result['error'] = '{}: {}'.format(type(error).__name__, error)
            finally:
                event.set()
