"""Local browser instrument for PYNQ; standard-library HTTP, NumPy and existing driver."""
import argparse
from datetime import datetime
import errno
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import re
import secrets
import signal
from socketserver import ThreadingMixIn
import sys
import threading
from urllib.parse import parse_qs, urlparse

import numpy as np

HERE = Path(__file__).resolve().parent
STATIC = HERE / 'spectrum_web'
BPLUS_ROOT = HERE / 'bplus'
USER_DATA_ROOT = HERE.parent / 'user_data'
if (HERE.parent / 'reference' / 'fft_contract_assets.py').is_file():
    sys.path.append(str(HERE.parent / 'reference'))
if not (BPLUS_ROOT / 'plus_app.py').is_file():
    raise RuntimeError('R4 requires the bplus runtime under: ' + str(BPLUS_ROOT))
sys.path.insert(0, str(BPLUS_ROOT))

from spectrum_runtime import SpectrumRuntime
from spectrum_integrity import verify_software
from spectrum_recording import BUILD_REVISION
from analysis_recorder import AnalysisRecorderError, LiveAnalysisRecorder
from hardware_modes import HardwareModeCoordinator, ModeError
from record_store import RecordStore, RecordStoreError
from response_recorder import ResponseRecorderError, UserResponseRecorder
from user_analysis_source import UserAnalysisService
from plus_app import (
    ReplayError as BPlusReplayError,
    ReplayService as BPlusReplayService,
    offline_status as bplus_offline_status,
)
from live_subscription import StatusSubscriber, write_report


class ThreadedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(runtime, bind='127.0.0.1', port=8091):
    token = secrets.token_hex(24)
    bplus_service = BPlusReplayService()
    record_store = RecordStore(USER_DATA_ROOT / 'records')
    calibration_path = (
        BPLUS_ROOT / 'reports' / 'B-X11'
        / 'signal_generator_20261101' / 'channel_calibration.json')
    response_recorders = {
        'rc': UserResponseRecorder(
            calibration_path, response_kind='rc_lowpass'),
        'generic': UserResponseRecorder(
            calibration_path, response_kind='generic_system'),
    }
    modes = (
        runtime if isinstance(runtime, HardwareModeCoordinator)
        else HardwareModeCoordinator(runtime, None, None)
    )
    analysis_recorder = LiveAnalysisRecorder()
    modes.add_fft_observer(analysis_recorder.observe)
    user_analysis_service = UserAnalysisService(record_store)
    user_analysis_lock = threading.RLock()

    def response_recorder_for(profile):
        key = str(profile or 'rc')
        aliases = {
            'rc': 'rc',
            'rc_lowpass': 'rc',
            'generic': 'generic',
            'generic_system': 'generic',
        }
        if key not in aliases:
            raise ModeError('未知的频率响应测量类型')
        return response_recorders[aliases[key]]

    def parse_response_route(path):
        match = re.fullmatch(
            r'/bx/api/response/(rc|generic)/'
            r'(start|stop|discard|capture|save)', path)
        if match:
            return response_recorders[match.group(1)], match.group(2)
        match = re.fullmatch(
            r'/bx/api/response/record/'
            r'(start|stop|discard|capture|save)', path)
        if match:
            return response_recorders['rc'], match.group(1)
        return None
    live_subscriber = StatusSubscriber("same_process_runtime")
    live_lock = threading.Lock()
    live_transcript = []

    def observe_live_status(status=None):
        status = status if status is not None else modes.status()
        with live_lock:
            result = live_subscriber.accept_status(status)
            live_transcript.append(result)
            if len(live_transcript) > 4096:
                del live_transcript[:-4096]
            summary = live_subscriber.summary()
        return {
            "runtime": status,
            "subscription": result,
            "summary": summary,
        }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, data, content_type, status=200, filename=None):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            if filename:
                self.send_header('Content-Disposition', 'attachment; filename="' + filename + '"')
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def json(self, value, status=200):
            self.send(json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8'), 'application/json; charset=utf-8', status)

        def bx_json(self, value, status=200):
            self.json(value, status)

        def bx_get(self, path, query):
            if path == '/bx/api/replay/index':
                self.bx_json(bplus_service.index_payload())
                return
            if path == '/bx/api/replay/frame':
                run_id = (query.get('run_id') or [''])[0]
                frame_text = (query.get('frame_id') or [''])[0]
                if not run_id or not frame_text:
                    raise BPlusReplayError('run_id and frame_id are required', 400)
                try:
                    frame_id = int(frame_text)
                except ValueError:
                    raise BPlusReplayError('frame_id must be an integer', 400)
                self.bx_json(bplus_service.frame_payload(run_id, frame_id))
                return
            if path == '/bx/api/replay/trend':
                params = {
                    key: (values[0] if values else '')
                    for key, values in query.items()
                }
                self.bx_json(bplus_service.trend_payload(params))
                return
            if path == '/bx/api/live/status':
                self.bx_json(observe_live_status())
                return
            if path == '/bx/api/live/summary':
                with live_lock:
                    summary = live_subscriber.summary()
                    snapshot = live_subscriber.feature_snapshot()
                self.bx_json({
                    "summary": summary,
                    "feature": {
                        "average_length": snapshot["average_length"],
                        "average_count": (
                            snapshot["average"]["count"]
                            if snapshot["average"] else 0),
                        "hold_count": (
                            snapshot["hold"]["count"]
                            if snapshot["hold"] else 0),
                        "group": snapshot["group"],
                        "current_frame_id": (
                            snapshot["current"]["frame_id"]
                            if snapshot["current"] else None),
                    },
                })
                return
            if path == '/bx/api/hardware/status':
                self.bx_json(modes.hardware_status())
                return
            if path == '/bx/api/analysis/record/status':
                status = modes.status()
                if (
                    analysis_recorder.status()['active']
                    and status.get('phase') not in ('RUNNING', 'CONFIGURING')
                ):
                    analysis_recorder.stop()
                recorder_status = analysis_recorder.status()
                recorder_status.update(modes.fft_diagnostics())
                self.bx_json(recorder_status)
                return
            if path == '/bx/api/response/record/status':
                profile = (query.get('profile') or ['rc'])[0]
                self.bx_json({
                    'profile': profile,
                    'status': response_recorder_for(profile).status(),
                })
                return
            if path == '/bx/api/response-record/detail':
                record_id = (query.get('record_id') or [''])[0]
                record = record_store.load(record_id)
                if record.get('record_type') != 'response':
                    raise RecordStoreError('记录不是频率响应记录')
                self.bx_json(record)
                return
            if path == '/bx/api/response-record/download':
                record_id = (query.get('record_id') or [''])[0]
                download_format = (query.get('format') or [''])[0]
                download, mime, filename = record_store.response_download(
                    record_id, download_format)
                self.send(download, mime, filename=filename)
                return
            if path == '/bx/api/response-record/plot':
                record_id = (query.get('record_id') or [''])[0]
                folder = record_store._record_dir(record_id)
                plot = (folder / 'gain_phase.png').resolve()
                plot.relative_to(folder)
                if not plot.is_file():
                    raise RecordStoreError('该记录没有可显示的频率响应图')
                self.send(plot.read_bytes(), 'image/png')
                return
            if path == '/bx/api/user-analysis/index':
                record_id = (query.get('record_id') or [''])[0]
                with user_analysis_lock:
                    self.bx_json(user_analysis_service.activate(record_id))
                return
            if path == '/bx/api/user-analysis/frame':
                record_id = (query.get('record_id') or [''])[0]
                run_id = (query.get('run_id') or [''])[0]
                frame_text = (query.get('frame_id') or [''])[0]
                if not record_id or not run_id or not frame_text:
                    raise BPlusReplayError(
                        'record_id, run_id and frame_id are required', 400)
                with user_analysis_lock:
                    user_analysis_service.activate(record_id)
                    self.bx_json(user_analysis_service.frame_payload(
                        run_id, int(frame_text)))
                return
            if path == '/bx/api/user-analysis/trend':
                params = {
                    key: (values[0] if values else '')
                    for key, values in query.items()
                }
                record_id = params.pop('record_id', '')
                if not record_id:
                    raise BPlusReplayError('record_id is required', 400)
                with user_analysis_lock:
                    user_analysis_service.activate(record_id)
                    self.bx_json(user_analysis_service.trend_payload(params))
                return
            if path == '/bx/api/records':
                record_type = (query.get('type') or [None])[0]
                if record_type not in (None, '', 'analysis', 'response'):
                    raise RecordStoreError('未知的记录类型')
                self.bx_json({
                    'records': record_store.list(record_type or None),
                })
                return
            if path == '/bx/api/records/load':
                record_id = (query.get('record_id') or [''])[0]
                self.bx_json(record_store.load(record_id))
                return
            if path == '/bx/api/extension/status':
                self.bx_json(bplus_offline_status())
                return
            raise BPlusReplayError('unknown B+ API', 404)

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            if path == '/api/status':
                status = modes.status()
                observe_live_status(status)
                if (
                    analysis_recorder.status()['active']
                    and status.get('phase') not in ('RUNNING', 'CONFIGURING')
                ):
                    analysis_recorder.stop()
                self.json(status)
                return
            if path.startswith('/downloads/'):
                name = path[len('/downloads/'):]
                if not re.fullmatch(r'spectrum_(?:session_)?[0-9a-f]{12}_export[0-9]{2,}\.zip', name):
                    self.json({'error': 'Unknown export'}, 404)
                    return
                archive = modes.downloads.get(name)
                if archive is None or not archive.is_file():
                    self.json({'error': 'Unknown export'}, 404)
                    return
                self.send(archive.read_bytes(), 'application/zip', filename=name)
                return
            bx_assets = {
                '/bx': ('index.html', 'text/html; charset=utf-8'),
                '/bx/': ('index.html', 'text/html; charset=utf-8'),
                '/bx/replay.js': ('replay.js', 'text/javascript; charset=utf-8'),
                '/bx/style.css': ('style.css', 'text/css; charset=utf-8'),
                '/bx/report/bx12': (
                    'reports/B-X12/measured_20261101/README.md',
                    'text/markdown; charset=utf-8'),
                '/bx/report/bx12.png': (
                    'reports/B-X12/measured_20261101/magnitude_phase.png',
                    'image/png'),
                '/bx/report/bx12.svg': (
                    'reports/B-X12/measured_20261101/magnitude_phase.svg',
                    'image/svg+xml'),
                '/bx/report/bx12.csv': (
                    'reports/B-X12/measured_20261101/rc_measured.csv',
                    'text/csv; charset=utf-8'),
                '/bx/report/bx12.json': (
                    'reports/B-X12/measured_20261101/rc_measured.json',
                    'application/json; charset=utf-8'),
            }
            if path in bx_assets or path.startswith('/bx/api/'):
                try:
                    if path in bx_assets:
                        name, mime = bx_assets[path]
                        asset_path = (
                            BPLUS_ROOT / 'web' / name
                            if name in ('index.html', 'replay.js', 'style.css')
                            else BPLUS_ROOT / name
                        )
                        content = asset_path.read_bytes()
                        if path in ('/bx', '/bx/'):
                            content = content.replace(
                                b'__CONTROL_TOKEN__', token.encode('ascii'))
                        self.send(content, mime)
                    else:
                        self.bx_get(path, parse_qs(parsed.query))
                except BPlusReplayError as error:
                    self.bx_json(
                        {'status': 'ERROR', 'error': error.message},
                        error.status,
                    )
                except RecordStoreError as error:
                    self.bx_json(
                        {'status': 'ERROR', 'error': str(error)}, 400)
                except FileNotFoundError:
                    self.bx_json({'status': 'ERROR', 'error': 'Not found'}, 404)
                except Exception as error:
                    self.bx_json(
                        {'status': 'ERROR', 'error': str(error)},
                        500,
                    )
                return
            assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                      '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                      '/workspace.js': ('workspace.js', 'text/javascript; charset=utf-8'),
                      '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if path not in assets:
                self.json({'error': 'Not found'}, 404)
                return
            name, mime = assets[path]
            content = (STATIC / name).read_bytes()
            if name == 'index.html':
                content = content.replace(b'__CONTROL_TOKEN__', token.encode('ascii'))
            self.send(content, mime)

        def do_POST(self):
            origin = self.headers.get('Origin')
            if (self.headers.get('X-Spectrum-Token') != token
                    or (origin and urlparse(origin).netloc != self.headers.get('Host'))):
                self.json({'error': 'Reload this instrument page before sending commands'}, 403)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 2_100_000 or self.headers.get_content_type() != 'application/json':
                    raise ValueError('Expected bounded JSON request')
                data = json.loads(self.rfile.read(length).decode('utf-8'))
                if not isinstance(data, dict):
                    raise ValueError('Expected JSON object')
                path = urlparse(self.path).path
                if path == '/bx/api/export':
                    self.json(bplus_service.export_payload(data))
                    return
                if path == '/bx/api/live/export':
                    with live_lock:
                        out_dir = (
                            BPLUS_ROOT / 'reports' / 'B-X08'
                            / ('same_process_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
                        )
                        payload = write_report(
                            out_dir, live_subscriber, list(live_transcript),
                            source='SAME_PROCESS_RUNTIME_STATUS')
                    self.json(payload)
                    return
                if path == '/bx/api/analysis/record/start':
                    self.json(analysis_recorder.start(
                        modes.status(), data.get('max_complete_frames')))
                    return
                if path == '/bx/api/analysis/record/stop':
                    self.json(analysis_recorder.stop())
                    return
                if path == '/bx/api/analysis/record/discard':
                    self.json(analysis_recorder.discard())
                    return
                if path == '/bx/api/records/save-analysis':
                    if analysis_recorder.status()['active']:
                        analysis_recorder.stop()
                    snapshot = analysis_recorder.snapshot()
                    record = record_store.save_analysis(
                        data.get('title') or (
                            '实时分析_' + datetime.now().strftime('%Y%m%d_%H%M%S')),
                        snapshot,
                    )
                    analysis_recorder.discard()
                    self.json(record)
                    return
                if path == '/bx/api/records/save-response':
                    hardware = modes.hardware_status()
                    latest = (
                        hardware.get('m4', {}).get('last_capture')
                        if hardware.get('m4') else None
                    )
                    if not latest:
                        raise ModeError('当前没有可保存的频率响应采集数据')
                    record = record_store.save(
                        'response',
                        data.get('title') or (
                            '频率响应_' + datetime.now().strftime('%Y%m%d_%H%M%S')),
                        '双声道频率响应采集',
                        {'hardware': hardware, 'capture': latest},
                    )
                    self.json(record)
                    return
                if path == '/bx/api/records/delete':
                    self.json(record_store.delete(str(data.get('record_id') or '')))
                    return
                response_route = parse_response_route(path)
                if response_route:
                    response_recorder, response_action = response_route
                    if response_action in ('start', 'capture'):
                        if modes.hardware_status().get('mode') != 'M4':
                            raise ModeError('请先进入电路测量模式')
                    if response_action == 'start':
                        self.json(response_recorder.start(data))
                        return
                    if response_action == 'stop':
                        self.json(response_recorder.stop())
                        return
                    if response_action == 'discard':
                        self.json(response_recorder.discard())
                        return
                    if response_action == 'capture':
                        capture = modes.m4_command('capture', {
                            'label': data.get('label') or (
                                'response_{:.0f}Hz'.format(
                                    float(data.get('target_hz')))),
                        })
                        raw_path = Path(capture['output']) / (
                            str(capture['label']) + '.npy')
                        samples = np.load(raw_path, allow_pickle=False)
                        response_status = response_recorder.add_capture(
                            float(data.get('target_hz')),
                            samples,
                            float(capture['fs_hz']),
                            str(capture['label']),
                            source_file=str(raw_path),
                        )
                        self.json({
                            'capture': capture,
                            'response': response_status,
                        })
                        return
                    if response_action == 'save':
                        if response_recorder.status()['active']:
                            response_recorder.stop()
                        snapshot = response_recorder.snapshot()
                        record = record_store.save_response(
                            data.get('title') or (
                                '频率响应_' + datetime.now().strftime('%Y%m%d_%H%M%S')),
                            snapshot,
                        )
                        response_recorder.discard()
                        self.json(record)
                        return
                if path == '/bx/api/user-analysis/export':
                    record_id = str(
                        data.get('record_id') or data.get('run_id') or '')
                    with user_analysis_lock:
                        user_analysis_service.activate(record_id)
                        self.json(user_analysis_service.export_payload(data))
                    return
                hardware_actions = {
                    '/bx/api/hardware/m4/enter': ('enter_m4', 30),
                    '/bx/api/hardware/m4/configure': ('m4_configure', 30),
                    '/bx/api/hardware/m4/selftest': ('m4_selftest', 30),
                    '/bx/api/hardware/m4/capture': ('m4_capture', 30),
                    '/bx/api/hardware/fft/restore': ('restore_fft', 30),
                }
                if path in hardware_actions:
                    action_name, timeout = hardware_actions[path]
                    if action_name == 'enter_m4':
                        if analysis_recorder.status()['active']:
                            raise ModeError('请先停止当前分析记录')
                        result = modes.enter_m4()
                    elif action_name == 'm4_configure':
                        result = modes.m4_command(
                            'configure', data, timeout=timeout)
                    elif action_name == 'm4_selftest':
                        result = modes.m4_command(
                            'selftest', data, timeout=timeout)
                    elif action_name == 'm4_capture':
                        result = modes.m4_command(
                            'capture', data, timeout=timeout)
                    else:
                        if any(
                                recorder.status()['active']
                                for recorder in response_recorders.values()):
                            raise ModeError('请先停止当前频率响应记录')
                        result = modes.restore_fft()
                    self.json(result)
                    return
                action = {'/api/start': 'start', '/api/stop': 'stop', '/api/render': 'render',
                          '/api/screenshot': 'screenshot', '/api/export': 'export',
                          '/api/export-session': 'export-session'}.get(path)
                if not action:
                    self.json({'error': 'Unknown command'}, 404)
                    return
                # Compression and CRC checks on the board can exceed the control timeout.
                timeout = 300 if action in ('export', 'export-session') else 15
                result = modes.call(action, data, timeout=timeout)
                if action == 'stop' and analysis_recorder.status()['active']:
                    analysis_recorder.stop()
                self.json(result)
            except BPlusReplayError as error:
                self.json({'error': error.message}, error.status)
            except RecordStoreError as error:
                self.json({'error': str(error)}, 400)
            except ModeError as error:
                self.json({'error': str(error), 'mode_conflict': True}, 409)
            except (ValueError, TypeError, RuntimeError, TimeoutError, KeyError) as error:
                self.json({'error': str(error)}, 400)

    server = ThreadedServer((bind, port), Handler)
    server.control_token = token
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('live', 'replay'), default='replay')
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8091)
    parser.add_argument('--bit', type=Path, default=HERE / 'fft.bit')
    parser.add_argument('--replay-folder', type=Path, default=HERE / 'replay_examples')
    parser.add_argument('--output', type=Path, default=HERE / 'spectrum_results')
    parser.add_argument('--allow-source-tree', action='store_true', help='Development only: permit a source checkout without a bundle manifest')
    args = parser.parse_args()
    identity = verify_software(HERE, args.allow_source_tree)

    def make_fft_runtime():
        return SpectrumRuntime(
            args.mode.upper(), args.output, args.replay_folder, args.bit,
            software_identity=identity)

    def make_m4_capture():
        from m4_delivery import M4Capture
        return M4Capture(str(HERE / 'm4' / 'm4.bit'), str(HERE / 'm4_results'))

    modes = HardwareModeCoordinator(
        make_fft_runtime(), make_fft_runtime, make_m4_capture)
    try:
        server = make_server(modes, args.bind, args.port)
    except OSError as error:
        modes.close()
        if error.errno == errno.EADDRINUSE or getattr(error, 'winerror', None) == 10048:
            raise SystemExit('Port {} is already in use; this second service was not started. '
                             'Stop the existing spectrum service first; do not start another LIVE owner on a different port. '
                             'Use: python3 spectrum_service.py stop --port {}'.format(args.port, args.port))
        raise
    except BaseException:
        modes.close()
        raise
    print('Spectrum instrument build=' + BUILD_REVISION + ' mode=' + args.mode.upper(), flush=True)
    print('Listening on {}:{}; open this computer/board address in your browser.'.format(args.bind, server.server_port), flush=True)
    print('LIVE hardware is configured once when Start is pressed. Keep other acquisition programs stopped.', flush=True)

    def interrupt(signum, frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, interrupt)
    while True:
        try:
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            try:
                modes.close()
            except RuntimeError as error:
                print(str(error), flush=True)
                continue
            break
    server.server_close()


if __name__ == '__main__':
    main()
