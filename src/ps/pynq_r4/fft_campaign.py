"""Bounded snapshot acquisition, append-only telemetry and limited sample retention."""
import json
import math
from pathlib import Path
import time
import traceback
import uuid

import numpy as np
from fft_delivery import CAPTURE_API_VERSION, WINDOW_SUM, sha256
from fft_session import frame_record, tone_observations


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')


def memory_sample():
    """Linux board readings; unavailable counters remain null, not zero."""
    result = {'rss_bytes': None, 'cma_free_bytes': None, 'open_fds': None}
    for path, key, target in [('/proc/self/status', 'VmRSS:', 'rss_bytes'),
                              ('/proc/meminfo', 'CmaFree:', 'cma_free_bytes')]:
        try:
            for line in Path(path).read_text().splitlines():
                if line.startswith(key): result[target] = int(line.split()[1]) * 1024
        except OSError:
            pass
    try: result['open_fds'] = sum(1 for _ in Path('/proc/self/fd').iterdir())
    except OSError: pass
    return result


class RunningStats:
    def __init__(self):
        self.count, self.mean, self.m2 = 0, 0.0, 0.0
        self.minimum, self.maximum = None, None

    def add(self, value):
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        self.m2 += delta * (value - self.mean)
        self.minimum = value if self.minimum is None else min(value, self.minimum)
        self.maximum = value if self.maximum is None else max(value, self.maximum)

    def report(self):
        return dict(count=self.count, mean=self.mean if self.count else None,
                    minimum=self.minimum, maximum=self.maximum,
                    stddev=math.sqrt(max(0, self.m2 / self.count)) if self.count else None)


class FFTCampaign:
    def __init__(self, capture, output, context='BOARD'):
        if CAPTURE_API_VERSION < 2:
            raise RuntimeError('Updated FFT capture API required')
        if context not in ('BOARD', 'HOST_REPLAY_TEST'):
            raise ValueError('Unknown execution context')
        self.capture, self.output, self.context = capture, Path(output), context
        self._running, self._stop_requested = False, False
        self.last_summary, self.last_directory = None, None

    def stop(self):
        """Request a stop after the current bounded frame; does not touch MMIO."""
        self._stop_requested = True

    def _sample(self, folder, number, words, state, saved):
        stem = 'sample_{:06d}'.format(number)
        np.save(folder / (stem + '_words.npy'), words, allow_pickle=False)
        state = dict(state)
        state['words_sha256'] = sha256(folder / (stem + '_words.npy'))
        frame = frame_record(words, state)
        np.save(folder / (stem + '_fft.npy'), frame['X'], allow_pickle=False)
        write_json(folder / (stem + '_state.json'), state)
        saved.append(dict(frame_number=number, stem=stem, sequence=frame['sequence'],
                          words_sha256=state['words_sha256']))

    def run(self, duration_s=600, target_hz=5, max_frames=10000, window='hann',
            expected_tones_hz=(), save_every=250, max_saved_frames=32):
        if self._running:
            raise RuntimeError('This campaign is already running')
        self._stop_requested = False
        if (not math.isfinite(duration_s) or not 0 < duration_s <= 3600 or
                not math.isfinite(target_hz) or not 0 < target_hz <= 50 or
                not isinstance(max_frames, int) or not 1 <= max_frames <= 100000 or
                window not in WINDOW_SUM or not isinstance(save_every, int) or save_every < 1 or
                not isinstance(max_saved_frames, int) or not 2 <= max_saved_frames <= 64):
            raise ValueError('Invalid bounded campaign settings')
        cap = self.capture
        if cap._unsafe or cap._active_buf is not None or not cap.codec_ready or cap.fs is None:
            raise RuntimeError('Capture must be configured with no live/unsafe buffer')
        expected_tones_hz = tuple(float(x) for x in expected_tones_hz)
        if any(not math.isfinite(x) or not 0 < x < cap.fs / 2 for x in expected_tones_hz):
            raise ValueError('Expected tone outside positive frequency range')
        self.output.mkdir(parents=True, exist_ok=True)
        folder = self.output / ('run_' + uuid.uuid4().hex[:12])
        folder.mkdir(exist_ok=False)
        self.last_directory = folder
        settings = dict(context=self.context, duration_s=duration_s, target_hz=target_hz,
                        max_frames=max_frames, window=window, expected_tones_hz=expected_tones_hz,
                        save_every=save_every, max_saved_frames=max_saved_frames,
                        source='PL_FFT', continuous_audio=False, overlay_sha256=cap.hashes)
        write_json(folder / 'settings.json', settings)
        print('Campaign:', folder, '\nStop file:', folder / 'STOP')
        stats = {name: RunningStats() for name in ('capture_call_s','adapter_s','log_s','work_s')}
        saved, health = [], []
        frames, attempts, quality_errors = 0, 0, 0
        reason, failure, cause = 'FAILED', None, None
        last_words, last_state, initial, final = None, None, None, None
        stopped, history_start = False, len(cap.history)
        started = time.monotonic()
        log = None
        self._running = True
        try:
            cap.quiesce()
            initial = cap.snapshot()
            log = (folder / 'frames.jsonl').open('x', encoding='utf-8')
            started = time.monotonic()
            next_due, next_health, next_progress = started, started, started + 30
            while True:
                now = time.monotonic()
                if self._stop_requested or (folder / 'STOP').exists(): reason='STOP_REQUESTED'; break
                if now - started >= duration_s: reason='DURATION_COMPLETE'; break
                if frames >= max_frames: reason='FRAME_LIMIT'; break
                if now < next_due:
                    time.sleep(min(0.05, next_due-now, duration_s-(now-started)))
                    continue
                work_at = time.monotonic()
                attempts += 1
                cap.last_record = None
                words = cap.capture(window, 'campaign_{:06d}'.format(attempts), persist=False, verbose=False)
                call_s = time.monotonic() - work_at
                state = cap.last_record
                frames += 1
                last_words, last_state = words, state
                if cap._active_buf is not None or len(cap.history) != history_start:
                    raise RuntimeError('Capture buffer/history ownership grew in lightweight mode')
                adapter_at = time.monotonic()
                frame = frame_record(words, state)
                if frame['sequence'] != ((initial['frame_sequence'] + frames) & 0xffffffff):
                    raise RuntimeError('Campaign sequence discontinuity')
                tones = tone_observations(frame, expected_tones_hz)
                quality_ok = all(t['nonzero'] and t['within_one_bin'] for t in tones)
                if expected_tones_hz:
                    quality_ok &= any(abs(state['peak_hz']-t) <= cap.fs/1024 for t in expected_tones_hz)
                adapter_s = time.monotonic() - adapter_at
                row = dict(frame_number=frames, capture=state, elapsed_s=time.monotonic()-started,
                           capture_call_s=call_s, adapter_s=adapter_s, tone_observations=tones,
                           tone_checks_passed=bool(quality_ok), active_buffer=False, history_length=len(cap.history))
                log_at = time.monotonic()
                log.write(json.dumps(row, allow_nan=False) + '\n'); log.flush()
                log_s = time.monotonic() - log_at
                if (frames == 1 or frames % save_every == 0) and len(saved) < max_saved_frames - 1:
                    self._sample(folder, frames, words, state, saved)
                work_s = time.monotonic() - work_at
                for name,value in [('capture_call_s',call_s),('adapter_s',adapter_s),('log_s',log_s),('work_s',work_s)]:
                    stats[name].add(value)
                if time.monotonic() >= next_health:
                    health.append(dict(elapsed_s=time.monotonic()-started, driver_history_length=len(cap.history),
                                       active_buffer=cap._active_buf is not None, **memory_sample()))
                    next_health = time.monotonic() + 30
                if time.monotonic() >= next_progress:
                    print('Frames:', frames, 'seconds:', round(time.monotonic()-started, 1))
                    next_progress = time.monotonic() + 30
                if not quality_ok:
                    quality_errors += 1
                    raise RuntimeError('Tone observations failed; verify the actual playback/input')
                # Pace snapshots without queued catch-up bursts after a slow operation.
                next_due = max(next_due + 1.0/target_hz, time.monotonic())
        except KeyboardInterrupt:
            reason = 'INTERRUPTED'
        except Exception as exc:
            reason, cause = 'FAILED', exc
            failure = traceback.format_exc()
        finally:
            try:
                if cap._unsafe:
                    raise RuntimeError('Capture previously failed to stop; retain its buffer and reboot')
                cap.quiesce()
                final = cap.snapshot()
                stopped = bool(final['dmasr'] & 1) and final['pl_status'] == 0x100 and cap._active_buf is None
                if not stopped:
                    raise RuntimeError('Final DMA/PL stop was not verified')
            except BaseException as exc:
                cap._unsafe = True
                reason = 'FAILED'
                failure = (failure or '') + '\nSTOP FAILURE: ' + str(exc)
                cause = exc
            finally:
                self._running = False
                if log is not None: log.close()
        elapsed = time.monotonic() - started
        if last_words is not None and (not saved or saved[-1]['frame_number'] != frames):
            self._sample(folder, frames, last_words, last_state, saved)
        health.append(dict(elapsed_s=elapsed, driver_history_length=len(cap.history),
                           active_buffer=cap._active_buf is not None, **memory_sample()))
        summary = dict(context=self.context, source='PL_FFT', reason=reason, successful_frames=frames,
                       attempts=attempts, quality_errors=quality_errors, elapsed_s=elapsed,
                       snapshot_frame_rate_hz=frames/elapsed if elapsed else None,
                       initial=initial, final=final, stop_verified=stopped, error=failure,
                       failed_or_aborted_attempt=cap.last_record if attempts>frames else None,
                       timing={name:s.report() for name,s in stats.items()}, saved_samples=saved,
                       memory_samples=health, settings=settings, continuous_audio=False,
                       B_display_integrated=False, board_accepted=False)
        self.last_summary = summary
        write_json(folder / 'summary.json', summary)
        print('Campaign finished:', reason, 'frames=', frames, 'stop_verified=', stopped)
        if reason == 'FAILED':
            raise RuntimeError('Campaign failed; evidence: ' + str(folder)) from cause
        return summary
