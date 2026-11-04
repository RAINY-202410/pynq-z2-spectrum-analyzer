"""Bounded evidence collection for the browser instrument."""
import base64
import hashlib
import json
from pathlib import Path
import time
import uuid
import zipfile

import numpy as np

from fft_campaign import memory_sample

APP_REVISION = 'spectrum_software_1'
BUILD_REVISION = 'spectrum_software_1_r4_bplus'


def save_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


class Recorder:
    def __init__(self, output, settings, source_info, context):
        self.folder = Path(output) / ('spectrum_' + uuid.uuid4().hex[:12])
        self.folder.mkdir(parents=True, exist_ok=False)
        self.settings, self.source_info, self.context = settings, source_info, context
        self.started = time.monotonic()
        self.frames = 0
        self.saved, self.health, self.capture_times = [], [], []
        self.viewers = {}
        self.last = None
        self.next_health = 0
        self.snapshots = []
        self.closed = False
        self.summary = None
        self.frames_log = (self.folder / 'frames.jsonl').open('x', encoding='utf-8')
        self.render_log = (self.folder / 'renders.jsonl').open('x', encoding='utf-8')
        save_json(self.folder / 'settings.json', dict(app_revision=APP_REVISION, context=context,
                  settings=settings, source_info=source_info, continuous_audio=False,
                  amplitude_calibrated=False, board_accepted=False))

    def elapsed(self):
        return time.monotonic() - self.started

    def _sample(self, number, words, state, frame):
        stem = 'frame_{:06d}'.format(number)
        path = self.folder / (stem + '_words.npy')
        np.save(path, words, allow_pickle=False)
        state = dict(state, words_sha256=sha256(path))
        save_json(self.folder / (stem + '_state.json'), state)
        np.save(self.folder / (stem + '_fft.npy'), frame['X'], allow_pickle=False)
        self.saved.append(dict(frame_id=number, stem=stem, sequence=frame['sequence'], words_sha256=state['words_sha256']))

    def record(self, words, state, frame, metrics, capture_s, analysis_s):
        self.frames += 1
        number = self.frames
        row = dict(frame_id=number, elapsed_s=self.elapsed(), capture=state, mode=frame['mode'],
                   capture_call_s=capture_s, analysis_s=analysis_s, metrics=metrics,
                   source='PL_FFT', active_buffer=False)
        self.frames_log.write(json.dumps(row, allow_nan=False) + '\n')
        self.frames_log.flush()
        self.capture_times.append(capture_s)
        self.last = words, state, frame
        if (number == 1 or number % self.settings['save_every'] == 0) and len(self.saved) < self.settings['max_saved_frames'] - 1:
            self._sample(number, words, state, frame)
        if self.elapsed() >= self.next_health:
            self.health.append(dict(elapsed_s=self.elapsed(), **memory_sample()))
            self.next_health = self.elapsed() + 30
        return row

    def render(self, payload):
        if self.closed:
            return False
        viewer = payload.get('viewer_id')
        number, duration = payload.get('frame_id'), payload.get('render_ms')
        visible = payload.get('visible')
        if (not isinstance(viewer, str) or not 1 <= len(viewer) <= 64
                or type(number) is not int or not 1 <= number <= self.frames
                or type(visible) is not bool or type(duration) not in (int, float)
                or not np.isfinite(duration) or not 0 <= duration <= 60000):
            raise ValueError('Invalid browser render acknowledgement')
        if viewer not in self.viewers:
            if len(self.viewers) >= 4:
                raise ValueError('At most four browser viewers may be recorded per run')
            self.viewers[viewer] = dict(count=0, last_frame_id=0, first_s=None, last_s=None,
                                       last_visible=False, segment_start=None, longest_visible_s=0,
                                       max_gap_s=0, render_ms_sum=0, render_ms_max=0)
        stats = self.viewers[viewer]
        if number <= stats['last_frame_id']:
            return False
        now = self.elapsed()
        gap = now - stats['last_s'] if stats['last_s'] is not None else 0
        if stats['first_s'] is None:
            stats['first_s'] = now
        if visible:
            if not stats['last_visible'] or gap > 2:
                stats['segment_start'] = now
            stats['longest_visible_s'] = max(stats['longest_visible_s'], now - stats['segment_start'])
        else:
            stats['segment_start'] = None
        stats.update(count=stats['count'] + 1, last_frame_id=number, last_s=now, last_visible=visible,
                     max_gap_s=max(stats['max_gap_s'], gap), render_ms_sum=stats['render_ms_sum'] + duration,
                     render_ms_max=max(stats['render_ms_max'], duration))
        self.render_log.write(json.dumps(dict(viewer_id=viewer, frame_id=number, elapsed_s=now,
                                             render_ms=duration, visible=visible), allow_nan=False) + '\n')
        self.render_log.flush()
        return True

    def screenshot(self, payload):
        number = payload.get('frame_id')
        encoded = payload.get('png_base64', '')
        if not isinstance(number, int) or not 1 <= number <= self.frames or not isinstance(encoded, str):
            raise ValueError('Invalid screenshot frame')
        if len(self.snapshots) >= 8 or len(encoded) > 2_000_000:
            raise ValueError('Screenshot retention limit')
        data = base64.b64decode(encoded, validate=True)
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Expected PNG screenshot')
        name = 'ui_snapshot_{:02d}.png'.format(len(self.snapshots) + 1)
        (self.folder / name).write_bytes(data)
        self.snapshots.append(dict(file=name, frame_id=number, sha256=sha256(self.folder / name)))
        save_json(self.folder / 'screenshots.json', self.snapshots)
        return name

    def finish(self, reason, stop, error=None):
        if self.closed:
            return self.summary
        if self.last is not None and (not self.saved or self.saved[-1]['frame_id'] != self.frames):
            self._sample(self.frames, *self.last)
        elapsed = self.elapsed()
        self.frames_log.close()
        self.render_log.close()
        self.closed = True
        self.health.append(dict(elapsed_s=elapsed, **memory_sample()))
        values = np.asarray(self.capture_times)
        timing = dict(mean_s=float(values.mean()), maximum_s=float(values.max()),
                      p95_s=float(np.percentile(values, 95)), p99_s=float(np.percentile(values, 99))) if len(values) else None
        self.summary = dict(app_revision=APP_REVISION, context=self.context, source='PL_FFT',
                            mode=self.source_info['mode'], reason=reason, frames=self.frames, elapsed_s=elapsed,
                            snapshot_frame_rate_hz=self.frames / elapsed if elapsed else None,
                            settings=self.settings, source_info=self.source_info, stop=stop, error=error,
                            capture_timing=timing, browser_viewers=self.viewers, saved_samples=self.saved,
                            memory_samples=self.health, retained_raw_limit=self.settings['max_saved_frames'],
                            latest_frame_limit=1, continuous_audio=False, board_accepted=False,
                            browser_timing_scope='Client canvas callback and visibility telemetry; not a synchronized physical display latency measurement')
        save_json(self.folder / 'summary.json', self.summary)
        (self.folder / 'performance.csv').write_text(
            'mode,frames,elapsed_s,snapshot_frame_rate_hz,capture_mean_ms,capture_max_ms\n' +
            '{},{},{:.9f},{:.9f},{},{}\n'.format(self.source_info['mode'], self.frames, elapsed,
                self.frames / elapsed if elapsed else 0, timing['mean_s'] * 1000 if timing else '',
                timing['maximum_s'] * 1000 if timing else ''), encoding='ascii')
        self.last = None
        self.capture_times.clear()
        return self.summary

    def export(self):
        if not self.closed:
            raise RuntimeError('Stop acquisition before exporting')
        index = 1
        while (self.folder.parent / (self.folder.name + '_export{:02d}.zip'.format(index))).exists():
            index += 1
        paths = sorted(p for p in self.folder.iterdir() if p.is_file() and not p.name.startswith('export_manifest_'))
        if any(p.is_symlink() for p in paths):
            raise ValueError('Evidence must not contain symlinks')
        manifest = dict(app_revision=APP_REVISION, mode=self.source_info['mode'], context=self.context,
                        files_sha256={p.name: sha256(p) for p in paths}, board_accepted=False)
        manifest_path = self.folder / 'export_manifest_{:02d}.json'.format(index)
        save_json(manifest_path, manifest)
        archive = self.folder.parent / (self.folder.name + '_export{:02d}.zip'.format(index))
        with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as z:
            for path in paths + [manifest_path]:
                z.write(path, self.folder.name + '/' + path.name)
        with zipfile.ZipFile(archive) as z:
            if z.testzip() is not None:
                raise RuntimeError('Export CRC failure')
        return archive
