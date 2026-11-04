"""Independently check browser-instrument evidence; never execute received code/HTML."""
import argparse
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import zipfile

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'sw/pynq'))
from fft_session import load_frame
from spectrum_analysis import analyse_frame
from spectrum_recording import APP_REVISION


def require(value, message):
    if not value:
        raise ValueError(message)


def same(actual, expected):
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(same(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(same(a, b) for a, b in zip(actual, expected))
    if isinstance(expected, float):
        return math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-9)
    return actual == expected


def approved_software_identity(identity, root=ROOT):
    approved = set()
    for version in ('spectrum_software_v1', 'spectrum_software_v1_r2', 'spectrum_software_v1_r3'):
        path = root / 'release' / version / 'package_receipt.json'
        if path.is_file():
            approved.add(json.loads(path.read_text(encoding='utf-8'))['board_software_manifest_sha256'])
    return identity.get('verified') is True and identity.get('manifest_sha256') in approved


def state_check(state, info, window):
    before, after = state['before'], state['after']
    require(state['success'] and state['source'] == 'PL_FFT' and state['N'] == 1024
            and state['window'] == window and state['scale_shift'] == 11
            and state['window_sum'] == {'hann': 511.50006103515625, 'rect': 1024.}[window], 'Frame identity/scale')
    require(state['fs_hz'] == info['fs_hz'] and state['overlay_sha256'] == info['overlay_sha256'], 'Frame fs/hardware identity')
    require(before['pl_status'] == 0x100 and after['pl_status'] == 0x106 and after['version'] == 0x46465401, 'Frame PL/version')
    require(after['length'] == state['received_bytes'] == state['requested_bytes'] == 8192
            and after['input_count'] == after['output_count'] == 1024, 'Frame payload/counts')
    require(after['dmasr'] & 0x1002 == 0x1002 and not after['dmasr'] & 0x4071
            and after['i2s_live'] and not after['i2s_snapshot'] & 2, 'Frame DMA/I2S')
    require(after['frame_sequence'] == (before['frame_sequence'] + 1) & 0xffffffff
            and (after['cnt_beat'] - before['cnt_beat']) & 0xffffffff == 1024, 'Frame sequence/beat count')
    require(before['window_requested'] == after['window_requested'] == int(window == 'hann'), 'Frame window readback')


def audit_archive(archive, out):
    out = Path(out).resolve()
    require(not out.exists(), 'Use a fresh audit output folder')
    blob = Path(archive).read_bytes()
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        infos = z.infolist()
        require(len(infos) < 1000 and sum(i.file_size for i in infos) < 100_000_000, 'ZIP size bound')
        require(len({i.filename for i in infos}) == len(infos), 'Duplicate ZIP names')
        roots = set()
        for item in infos:
            path = PurePosixPath(item.filename)
            require(path.parts and not path.is_absolute() and '..' not in path.parts and ':' not in item.filename
                    and '\\' not in item.filename and path.as_posix() == item.filename.rstrip('/'), 'Unsafe ZIP name')
            require(not stat.S_ISLNK(item.external_attr >> 16), 'ZIP symlink')
            roots.add(path.parts[0])
        require(len(roots) == 1 and z.testzip() is None, 'ZIP CRC/root')
        root = roots.pop()
        names = [i.filename[len(root) + 1:] for i in infos if not i.is_dir()]
        manifests = [n for n in names if n.startswith('export_manifest_') and n.endswith('.json')]
        require(len(manifests) == 1, 'Expected one export manifest')
        manifest = json.loads(z.read(root + '/' + manifests[0]))
        require(set(manifest['files_sha256']) == set(names) - set(manifests), 'Manifest file coverage')
        for name, expected in manifest['files_sha256'].items():
            require(hashlib.sha256(z.read(root + '/' + name)).hexdigest().upper() == expected, 'File hash: ' + name)
        out.mkdir(parents=True)
        (out / Path(archive).name).write_bytes(blob)
        for item in infos:
            if item.is_dir():
                continue
            target = out / 'received' / item.filename
            require(target.resolve().is_relative_to((out / 'received').resolve()), 'Extraction escaped')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(item))
    base = out / 'received' / root
    read = lambda name: json.loads((base / name).read_text(encoding='utf-8'))
    summary, metadata = read('summary.json'), read('settings.json')
    settings, info = summary['settings'], summary['source_info']
    require(summary['app_revision'] == metadata['app_revision'] == manifest['app_revision'] == APP_REVISION, 'App revision')
    require(metadata['settings'] == settings and metadata['source_info'] == info and metadata['context'] == summary['context'] == manifest['context'], 'Run metadata')
    mode = summary['mode']
    require(mode == info['mode'] == manifest['mode'] and mode in ('LIVE', 'REPLAY') and info['source'] == summary['source'] == 'PL_FFT', 'Source/mode')
    require((mode == 'LIVE' and summary['context'] in ('BOARD_LIVE', 'HOST_TEST_DRIVER'))
            or (mode == 'REPLAY' and summary['context'] != 'BOARD_LIVE'), 'Context label')
    require(math.isfinite(summary['elapsed_s']) and summary['elapsed_s'] >= 0, 'Run elapsed')
    fs = info['fs_hz']
    require(math.isfinite(fs) and abs(fs / 48000 - 1) <= .01, 'Measured fs')
    rows = [json.loads(line) for line in (base / 'frames.jsonl').read_text().splitlines()]
    require(len(rows) == summary['frames'] <= settings['max_frames'] <= 20000, 'Frame bound/count')
    previous = -1
    for number, row in enumerate(rows, 1):
        require(row['frame_id'] == number and row['source'] == 'PL_FFT' and row['mode'] == mode
                and not row['active_buffer'], 'Row identity/ownership')
        require(previous <= row['elapsed_s'] <= summary['elapsed_s'], 'Frame time')
        previous = row['elapsed_s']
        state_check(row['capture'], info, settings['window'])
        for key in ('capture_call_s', 'analysis_s'):
            require(math.isfinite(row[key]) and row[key] >= 0, 'Timing values')
        if mode == 'LIVE':
            require(row['capture']['after']['frame_sequence'] == (info['initial']['frame_sequence'] + number) & 0xffffffff, 'Live sequence discontinuity')
    if rows:
        times = np.asarray([r['capture_call_s'] for r in rows])
        timing = dict(mean_s=float(times.mean()), maximum_s=float(times.max()),
                      p95_s=float(np.percentile(times, 95)), p99_s=float(np.percentile(times, 99)))
        require(same(summary['capture_timing'], timing), 'Capture timing aggregation')
    require(same(summary['snapshot_frame_rate_hz'], len(rows) / summary['elapsed_s'] if summary['elapsed_s'] else None), 'Measured snapshot rate')
    samples = summary['saved_samples']
    require(len(samples) == len(list(base.glob('*_words.npy'))) <= settings['max_saved_frames'] <= 32, 'Retention bound')
    if rows:
        require(samples and samples[0]['frame_id'] == 1 and samples[-1]['frame_id'] == len(rows), 'First/last retention')
    for sample in samples:
        stem = sample['stem']; frame_id = sample['frame_id']
        require(type(frame_id) is int and 1 <= frame_id <= len(rows)
                and stem == 'frame_{:06d}'.format(frame_id), 'Sample path/identity')
        frame = load_frame(base / (stem + '_words.npy'), base / (stem + '_state.json'))
        require(frame['sequence'] == sample['sequence'], 'Sample sequence')
        require(np.array_equal(frame['X'], np.load(base / (stem + '_fft.npy'), allow_pickle=False)), 'Raw complex reconstruction')
        sample_state = read(stem + '_state.json')
        state = dict(rows[frame_id - 1]['capture']); state.pop('words_sha256', None)
        sample_state.pop('words_sha256', None)
        require(sample_state == state, 'Sample/row state')
        require(same(analyse_frame(frame, settings['expected_tones_hz']), rows[frame_id - 1]['metrics']), 'Raw spectrum/metrics')
    viewers = {}
    for line in (base / 'renders.jsonl').read_text().splitlines():
        row = json.loads(line); viewer = row['viewer_id']
        require(1 <= row['frame_id'] <= len(rows) and 0 <= row['elapsed_s'] <= summary['elapsed_s']
                and math.isfinite(row['render_ms']) and 0 <= row['render_ms'] <= 60000
                and type(row['visible']) is bool, 'Browser record')
        if viewer not in viewers:
            require(len(viewers) < 4, 'Viewer bound')
            viewers[viewer] = dict(count=0, last_frame_id=0, first_s=None, last_s=None, last_visible=False,
                                   segment_start=None, longest_visible_s=0, max_gap_s=0, render_ms_sum=0, render_ms_max=0)
        stats = viewers[viewer]
        require(row['frame_id'] > stats['last_frame_id'] and (stats['last_s'] is None or row['elapsed_s'] >= stats['last_s']), 'Browser duplicate/order')
        now = row['elapsed_s']; gap = now - stats['last_s'] if stats['last_s'] is not None else 0
        if stats['first_s'] is None: stats['first_s'] = now
        if row['visible']:
            if not stats['last_visible'] or gap > 2: stats['segment_start'] = now
            stats['longest_visible_s'] = max(stats['longest_visible_s'], now - stats['segment_start'])
        else: stats['segment_start'] = None
        stats.update(count=stats['count'] + 1, last_frame_id=row['frame_id'], last_s=now, last_visible=row['visible'],
                     max_gap_s=max(stats['max_gap_s'], gap), render_ms_sum=stats['render_ms_sum'] + row['render_ms'],
                     render_ms_max=max(stats['render_ms_max'], row['render_ms']))
    require(same(viewers, summary['browser_viewers']), 'Browser telemetry aggregation')
    screenshots = read('screenshots.json') if (base / 'screenshots.json').exists() else []
    for shot in screenshots:
        require(shot['file'] == Path(shot['file']).name and 1 <= shot['frame_id'] <= len(rows), 'Screenshot identity')
        data = (base / shot['file']).read_bytes()
        require(data.startswith(b'\x89PNG\r\n\x1a\n') and hashlib.sha256(data).hexdigest().upper() == shot['sha256'], 'Screenshot file')
    hardware_match = False
    identity = info.get('software_identity', {})
    if summary['context'] == 'BOARD_LIVE':
        receipt = json.loads((ROOT / 'release/fft_campaign_v1/package_receipt.json').read_text())
        expected = {'fft.bit': receipt['bit_sha256'], 'fft.hwh': receipt['hwh_sha256']}
        hardware_match = {k: v.upper() for k, v in info['overlay_sha256'].items()} == expected
        require(hardware_match, 'Board hardware identity')
        require(approved_software_identity(identity), 'Board software bundle identity')
    quality_errors = sum(not row['metrics']['tone_checks_passed'] for row in rows)
    functional = bool(rows and summary['reason'] in ('DURATION_COMPLETE', 'STOP_REQUESTED', 'FRAME_LIMIT')
                      and summary['error'] is None and summary['stop']['stop_verified'] and quality_errors == 0)
    if mode == 'LIVE' and functional:
        final = summary['stop']['final']
        require(final['dmasr'] & 1 and final['pl_status'] == 0x100
                and final['frame_sequence'] == rows[-1]['capture']['after']['frame_sequence'], 'Final live stop')
    visible_s = max((v['longest_visible_s'] for v in viewers.values()), default=0)
    ui_met = bool(functional and summary['context'] == 'BOARD_LIVE' and hardware_match
                  and identity.get('verified') is True and summary['reason'] == 'DURATION_COMPLETE'
                  and summary['elapsed_s'] >= 600 and visible_s >= 600 and screenshots)
    memory = {}
    for key in ('rss_bytes', 'cma_free_bytes', 'open_fds'):
        values = [h[key] for h in summary['memory_samples'] if h[key] is not None]
        memory[key] = dict(first=values[0], last=values[-1], minimum=min(values), maximum=max(values),
                           change=values[-1] - values[0]) if values else None
    result = dict(status=('BOARD_UI_RUN_DATA_VERIFIED' if summary['context'] == 'BOARD_LIVE' else 'HOST_OR_REPLAY_DATA_VERIFIED')
                         if functional else 'FAILED_RUN_DIAGNOSTIC_VERIFIED',
                  archive_sha256=hashlib.sha256(blob).hexdigest().upper(), mode=mode, context=summary['context'],
                  frames=len(rows), elapsed_s=summary['elapsed_s'], snapshot_frame_rate_hz=summary['snapshot_frame_rate_hz'],
                  reason=summary['reason'], quality_errors=quality_errors, stop_verified=summary['stop']['stop_verified'],
                  functional_run_passed=functional, raw_samples_verified=len(samples), screenshots_verified=len(screenshots),
                  software_identity=identity, browser_viewers=viewers, longest_visible_browser_s=visible_s,
                  ui_10min_evidence_met=ui_met, memory_diagnostics=memory, cma_trend_requires_review=True,
                  board_accepted=False, amplitude_calibrated=False,
                  scope='Browser canvas/visibility telemetry and PL snapshot evidence; no synchronized physical display latency or gap-free audio claim.')
    (out / 'audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def audit_session(archive, out):
    """Audit the single downloadable ZIP containing all runs from one service instance."""
    out = Path(out).resolve()
    require(not out.exists(), 'Use a fresh session audit folder')
    blob = Path(archive).read_bytes()
    with zipfile.ZipFile(io.BytesIO(blob)) as outer:
        infos = outer.infolist()
        require(len(infos) <= 33 and len({i.filename for i in infos}) == len(infos)
                and sum(i.file_size for i in infos) < 100_000_000 and outer.testzip() is None, 'Session ZIP bounds/CRC')
        roots = set()
        for item in infos:
            path = PurePosixPath(item.filename)
            require(path.parts and not path.is_absolute() and '..' not in path.parts and ':' not in item.filename
                    and '\\' not in item.filename and path.as_posix() == item.filename
                    and not stat.S_ISLNK(item.external_attr >> 16), 'Session ZIP path')
            roots.add(path.parts[0])
        require(len(roots) == 1, 'Session root')
        root = roots.pop()
        manifest = json.loads(outer.read(root + '/session_manifest.json'))
        require(manifest['app_revision'] == APP_REVISION and len(manifest['runs']) <= 32
                and len(set(manifest['runs'])) == len(manifest['runs']), 'Session run bound')
        require(set(i.filename[len(root) + 1:] for i in infos) == set(manifest['files_sha256']) | {'session_manifest.json'}, 'Session file coverage')
        expanded = 0
        for name, expected in manifest['files_sha256'].items():
            require(re.fullmatch(r'runs/spectrum_[0-9a-f]{12}_export[0-9]{2,}\.zip', name), 'Session inner archive name')
            content = outer.read(root + '/' + name)
            require(hashlib.sha256(content).hexdigest().upper() == expected, 'Session inner hash')
            with zipfile.ZipFile(io.BytesIO(content)) as inner:
                expanded += sum(i.file_size for i in inner.infolist())
        require(expanded < 200_000_000, 'Session expanded size bound')
        out.mkdir(parents=True)
        (out / Path(archive).name).write_bytes(blob)
        for item in infos:
            target = out / 'received' / item.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(outer.read(item))
    rows = []
    for name in manifest['files_sha256']:
        path = out / 'received' / root / name
        run_id = path.name.split('_export')[0]
        require(run_id in manifest['runs'], 'Unlisted run')
        audit = audit_archive(path, out / 'run_audits' / run_id)
        base = out / 'run_audits' / run_id / 'received' / run_id
        summary = json.loads((base / 'summary.json').read_text())
        require(summary['context'] == manifest['context'] and summary['mode'] == manifest['mode']
                and summary['source_info']['instance_id'] == manifest['instance_id'], 'Mixed service/source session')
        rows.append(dict(run_id=run_id, audit=audit, summary=summary))
    require(len(rows) == len(manifest['runs']), 'Missing session run')
    passed = [row for row in rows if row['audit']['functional_run_passed']]
    visible = lambda row: bool(row['audit']['browser_viewers'] and row['audit']['screenshots_verified'])
    board = manifest['context'] == 'BOARD_LIVE' and manifest['mode'] == 'LIVE'
    stop_restart = False
    if board:
        ordered = sorted(passed, key=lambda row: row['summary']['source_info']['initial']['frame_sequence'])
        for first, second in zip(ordered, ordered[1:]):
            if (first['summary']['reason'] == 'STOP_REQUESTED' and min(first['audit']['frames'], second['audit']['frames']) >= 10
                    and first['summary']['stop']['final']['frame_sequence'] == second['summary']['source_info']['initial']['frame_sequence']
                    and visible(first) and visible(second)):
                stop_restart = True
    def has(scenario, window):
        return board and any(row['summary']['settings']['scenario'] == scenario
                             and row['summary']['settings']['window'] == window and visible(row) for row in passed)
    checks = dict(stop_restart_same_overlay=stop_restart,
                  visible_ui_10min=any(row['audit']['ui_10min_evidence_met'] and row['summary']['settings']['scenario'] == 'tone1k'
                                       and row['summary']['settings']['window'] == 'hann' for row in passed),
                  dual_rect=has('dual', 'rect'), dual_hann=has('dual', 'hann'), analog_silence_observed=has('silence', 'hann'))
    complete = board and all(checks.values())
    result = dict(status='BOARD_UI_FUNCTIONAL_EVIDENCE_COMPLETE_CMA_REVIEW_PENDING' if complete
                  else 'SESSION_DATA_VERIFIED_REQUIREMENTS_PENDING' if board else 'HOST_OR_REPLAY_SESSION_VERIFIED',
                  archive_sha256=hashlib.sha256(blob).hexdigest().upper(), context=manifest['context'], mode=manifest['mode'],
                  instance_id=manifest['instance_id'], runs=len(rows), functional_runs=len(passed),
                  failed_or_incomplete_runs=[row['run_id'] for row in rows if not row['audit']['functional_run_passed']],
                  regression=checks, complete_ui_regression=complete, ui_10min_evidence_met=checks['visible_ui_10min'],
                  board_accepted=False, cma_review_pending=True, amplitude_calibrated=False,
                  results=[dict(run_id=row['run_id'], **row['audit']) for row in rows])
    (out / 'audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    import csv
    with (out / 'regression.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f); writer.writerow(['check', 'met', 'scope'])
        writer.writerows((name, met, 'BOARD_LIVE functional UI; full project acceptance separate') for name, met in checks.items())
    with (out / 'performance.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['run', 'mode', 'scenario', 'window', 'frames', 'elapsed_s', 'snapshot_hz', 'browser_hz', 'capture_mean_ms', 'capture_max_ms'])
        for row in rows:
            summary, audit = row['summary'], row['audit']
            browser_hz = max(((v['count'] - 1) / (v['last_s'] - v['first_s'])
                             for v in audit['browser_viewers'].values() if v['count'] > 1 and v['last_s'] > v['first_s']), default=0)
            timing = summary['capture_timing'] or {}
            writer.writerow([row['run_id'], summary['mode'], summary['settings']['scenario'], summary['settings']['window'],
                             audit['frames'], audit['elapsed_s'], audit['snapshot_frame_rate_hz'], browser_hz,
                             timing.get('mean_s', 0) * 1000, timing.get('maximum_s', 0) * 1000])
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--require-live-ui-10min', action='store_true')
    args = parser.parse_args()
    with zipfile.ZipFile(args.archive) as z:
        session = any(n.endswith('/session_manifest.json') for n in z.namelist())
    result = (audit_session if session else audit_archive)(args.archive, args.out)
    print(json.dumps(result, indent=2))
    if args.require_live_ui_10min and not result['ui_10min_evidence_met']:
        raise SystemExit('Verified data do not meet BOARD LIVE + visible browser600-second evidence requirements')
