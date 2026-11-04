"""R4 single-port integration and hardware-mode coordination tests."""

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis_recorder import AnalysisRecorderError, LiveAnalysisRecorder  # noqa: E402
from hardware_modes import HardwareModeCoordinator, ModeError  # noqa: E402
from record_store import RecordStore, RecordStoreError  # noqa: E402
from response_recorder import ResponseRecorderError, UserResponseRecorder  # noqa: E402
from spectrum_app import make_server  # noqa: E402
from spectrum_integrity import verify_software  # noqa: E402
from user_analysis_source import UserAnalysisService  # noqa: E402


class FakeFftRuntime:
    def __init__(self):
        self.downloads = {}
        self.phase = "IDLE"
        self.run_id = "spectrum_test_run"
        self.frames = 0
        self.closed = False
        self.calls = []
        self.frame_observers = []
        self.observer_errors = []

    def add_frame_observer(self, observer):
        if observer not in self.frame_observers:
            self.frame_observers.append(observer)

    def status(self):
        return {
            "build_revision": "spectrum_software_1_r4_bplus",
            "mode": "LIVE",
            "source": "PL_FFT",
            "phase": self.phase,
            "run_id": self.run_id,
            "frames": self.frames,
            "elapsed_s": 0,
            "snapshot_frame_rate_hz": 0,
            "cases": [],
            "browser_viewers": {},
            "completed_runs": 0,
            "latest": None,
            "error": None,
            "reason": None,
            "settings": {
                "window": "hann",
                "scenario": "observe",
                "expected_tones_hz": [],
            },
        }

    def emit_analysis_frame(self):
        self.frames += 1
        frequency = np.arange(513, dtype=float) * 48000.0 / 1024.0
        amplitude = np.zeros(513, dtype=float)
        amplitude[21] = 0.1
        dbfs = 20 * np.log10(np.maximum(amplitude, 1e-12))
        metrics = {
            "peaks": [{
                "bin": 21,
                "frequency_hz": float(frequency[21]),
                "dbfs": float(dbfs[21]),
            }],
            "tone_checks_passed": True,
            "nonzero_bins": 1,
        }
        payload = {
            "run_id": self.run_id,
            "frame_id": self.frames,
            "sequence": 100 + self.frames,
            "window_name": "hann",
            "fs_hz": 48000.0,
            "N": 1024,
            "frequency_hz": frequency.tolist(),
            "amplitude": amplitude.tolist(),
            "dbfs": dbfs.tolist(),
            "metrics": metrics,
        }
        for observer in list(self.frame_observers):
            observer(
                np.arange(1024, dtype=np.uint64),
                {"frame_sequence": 100 + self.frames},
                {"window_name": "hann"},
                metrics,
                payload,
                {"elapsed_s": self.frames * 0.2},
            )

    def call(self, action, payload=None, timeout=15):
        self.calls.append(action)
        if action == "stop":
            self.phase = "IDLE"
            return self.status()
        return {"actions": action}

    def close(self):
        self.closed = True


class FakeM4:
    def __init__(self):
        self.codec_ready = False
        self.fs = None
        self.history = []
        self._unsafe = False
        self.output = Path("m4_test_output")
        self.closed = False

    def configure_codec(self):
        self.codec_ready = True

    def measure_fs(self, seconds=2.0):
        self.fs = 48000.0
        return self.fs

    def capture(self, test=False, label="cap"):
        if test:
            import numpy as np
            return np.arange(1024, dtype=np.uint64)
        import numpy as np
        self.history.append({"label": label, "success": True})
        return np.zeros((2, 1024), dtype=np.int32)

    def close(self):
        self.closed = True


class R4IntegrationTest(unittest.TestCase):
    def test_workspace_assets_and_api_routes(self):
        runtime = FakeFftRuntime()
        runtime.phase = "RUNNING"
        server = make_server(runtime, "127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:{}".format(server.server_port)
        try:
            with urlopen(base + "/", timeout=5) as response:
                root_html = response.read().decode("utf-8")
            self.assertIn("实时频谱", root_html)
            self.assertIn("深入分析", root_html)
            self.assertIn("我的记录", root_html)
            self.assertIn("演示样例", root_html)
            self.assertIn("频率响应", root_html)
            self.assertIn("幅频 / 相频结果演示样例", root_html)
            self.assertIn('id="downloadResponseCsv"', root_html)
            self.assertIn('id="downloadResponseJson"', root_html)
            self.assertIn(
                'id="recordViewerFrame" title="我的分析记录" '
                'data-src="/bx/" hidden', root_html)
            self.assertIn(
                "#recordViewerFrame[hidden]{display:none}", root_html)
            self.assertNotIn("B-X", root_html)
            self.assertNotIn("M4 / RC", root_html)
            self.assertNotIn("__CONTROL_TOKEN__", root_html)

            with urlopen(base + "/bx/", timeout=5) as response:
                bx_html = response.read().decode("utf-8")
            self.assertIn('window.BX_API_BASE = "/bx"', bx_html)
            self.assertIn("window.R4_CONTROL_TOKEN", bx_html)
            self.assertIn("历史实验回放", bx_html)
            self.assertIn("请选择实验记录（可选）", bx_html)
            self.assertNotIn("B-X", bx_html)
            self.assertNotIn("__CONTROL_TOKEN__", bx_html)

            for path in (
                "/workspace.js",
                "/bx/replay.js",
                "/bx/api/live/status",
                "/bx/api/live/summary",
                "/bx/api/hardware/status",
                "/bx/api/records",
                "/bx/api/response/record/status?profile=generic",
            ):
                with urlopen(base + path, timeout=5) as response:
                    self.assertEqual(response.status, 200, path)
                    response.read()
            workspace_source = (
                ROOT / "spectrum_web" / "workspace.js").read_text(
                    encoding="utf-8")
            self.assertIn("recordViewerFrame.hidden = true", workspace_source)
            self.assertIn("recordViewerFrame.hidden = false", workspace_source)
            request = Request(
                base + "/bx/api/hardware/m4/enter",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as raised:
                urlopen(request, timeout=5)
            self.assertEqual(raised.exception.code, 403)

            start_request = Request(
                base + "/bx/api/analysis/record/start",
                data=json.dumps({"max_complete_frames": 8}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "X-Spectrum-Token": server.control_token,
                },
                method="POST",
            )
            with urlopen(start_request, timeout=5) as response:
                started = json.loads(response.read())
            self.assertTrue(started["active"])
            runtime.emit_analysis_frame()
            runtime.emit_analysis_frame()
            with urlopen(base + "/bx/api/analysis/record/status", timeout=5) as response:
                record_status = json.loads(response.read())
            self.assertEqual(record_status["runtime_frames"], 2)
            self.assertEqual(record_status["total_frames"], 2)
            self.assertEqual(record_status["saved_complete_count"], 2)
            self.assertEqual(record_status["saved_metric_count"], 2)
            self.assertEqual(record_status["observer_errors"], [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_response_record_download_api_serves_csv_and_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            user_data = Path(temporary)
            store = RecordStore(user_data / "records")
            response = store.save(
                "response", "频率响应下载测试", "频率响应测量",
                {"points": []})
            folder = store._record_dir(response["record_id"])
            csv_text = (
                "target_hz,estimated_frequency_hz,gain_db,phase_deg\n"
                "1000,999.9,-3.01,-45.0\n"
            )
            (folder / "points.csv").write_bytes(csv_text.encode("utf-8"))
            analysis = store.save(
                "analysis", "分析下载隔离测试", "实时频谱", {})

            with patch("spectrum_app.USER_DATA_ROOT", user_data):
                server = make_server(FakeFftRuntime(), "127.0.0.1", 0)
                thread = threading.Thread(
                    target=server.serve_forever, daemon=True)
                thread.start()
                base = "http://127.0.0.1:{}".format(server.server_port)
                try:
                    for download_format, expected, content_type in (
                            ("csv", csv_text.encode("utf-8"),
                             "text/csv; charset=utf-8"),
                            ("json",
                             (folder / "record.json").read_bytes(),
                             "application/json; charset=utf-8")):
                        path = (
                            "/bx/api/response-record/download?record_id="
                            + response["record_id"] + "&format="
                            + download_format)
                        with urlopen(base + path, timeout=5) as result:
                            self.assertEqual(result.status, 200)
                            self.assertEqual(
                                result.headers["Content-Type"], content_type)
                            self.assertIn(
                                "attachment;",
                                result.headers["Content-Disposition"])
                            self.assertEqual(result.read(), expected)

                    for bad_path in (
                            "/bx/api/response-record/download?record_id="
                            + response["record_id"] + "&format=xml",
                            "/bx/api/response-record/download?record_id="
                            + analysis["record_id"] + "&format=csv",
                            "/bx/api/response-record/download?record_id=bad"
                            "&format=csv"):
                        with self.assertRaises(HTTPError) as raised:
                            urlopen(base + bad_path, timeout=5)
                        self.assertEqual(raised.exception.code, 400)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=3)

    def test_fft_m4_fft_mode_transition_is_exclusive(self):
        first_fft = FakeFftRuntime()
        created = []

        def fft_factory():
            runtime = FakeFftRuntime()
            created.append(runtime)
            return runtime

        coordinator = HardwareModeCoordinator(first_fft, fft_factory, FakeM4)
        first_fft.phase = "RUNNING"
        result = coordinator.enter_m4()
        self.assertEqual(result["mode"], "M4")
        self.assertEqual(first_fft.calls, ["stop"])
        self.assertTrue(first_fft.closed)
        with self.assertRaises(ModeError):
            coordinator.call("start", {})

        configured = coordinator.m4_command("configure", {})
        self.assertTrue(configured["codec_ready"])
        tested = coordinator.m4_command("selftest", {})
        self.assertTrue(tested["passed"])
        captured = coordinator.m4_command(
            "capture", {"label": "r4_test_capture"})
        self.assertEqual(captured["shape"], [2, 1024])

        restored = coordinator.restore_fft()
        self.assertEqual(restored["mode"], "FFT")
        self.assertEqual(len(created), 1)
        self.assertEqual(coordinator.status()["mode"], "LIVE")
        coordinator.close()

    def test_bplus_script_uses_prefixed_api_and_token(self):
        text = (ROOT / "bplus" / "web" / "replay.js").read_text(
            encoding="utf-8")
        self.assertIn('window.BX_API_BASE || ""', text)
        self.assertIn("apiURL(url)", text)
        self.assertIn('"X-Spectrum-Token": R4_CONTROL_TOKEN', text)
        self.assertIn(
            "if (requestedDemo || requestedExport || requestedUserRecord)", text)
        self.assertIn("requestedUserRecord", text)
        self.assertIn('DATA_SOURCE === "user"', text)
        self.assertIn("/bx/api/user-analysis/index", text)
        self.assertIn("/bx/api/user-analysis/frame", text)
        self.assertIn("showEmptyState();", text)

    def test_r4_manifest_and_revision(self):
        manifest = json.loads(
            (ROOT / "software_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["build_revision"], "spectrum_software_1_r4_bplus")
        self.assertEqual(
            manifest["status"], "HOST_VALIDATED_BOARD_PENDING")
        verified = verify_software(ROOT)
        self.assertTrue(verified["verified"])
        self.assertEqual(verified["build_revision"], manifest["build_revision"])
        source = (ROOT / "spectrum_recording.py").read_text(encoding="utf-8")
        self.assertIn(
            "BUILD_REVISION = 'spectrum_software_1_r4_bplus'", source)

    def test_user_record_store_is_separate_from_demo_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = RecordStore(Path(temporary))
            self.assertEqual(store.list(), [])
            analysis = store.save(
                "analysis", "分析记录", "当前实时频谱采集",
                {"summary": {"accepted": 3}})
            response = store.save(
                "response", "响应记录", "双声道频率响应采集",
                {"capture": {"label": "single"}})
            self.assertEqual(len(store.list()), 2)
            self.assertEqual(
                [item["record_id"] for item in store.list("analysis")],
                [analysis["record_id"]])
            self.assertEqual(
                store.load(response["record_id"])["record_type"], "response")
            store.delete(analysis["record_id"])
            self.assertEqual(
                [item["record_id"] for item in store.list()],
                [response["record_id"]])
            with self.assertRaises(RecordStoreError):
                store.load("../../bad")

    def test_analysis_record_round_trips_through_user_viewer(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = RecordStore(Path(temporary))
            recorder = LiveAnalysisRecorder(
                max_complete_frames=3, max_metric_rows=100)
            status = {
                "mode": "LIVE",
                "phase": "RUNNING",
                "run_id": "spectrum_live_test",
                "settings": {
                    "window": "hann",
                    "scenario": "observe",
                    "expected_tones_hz": [],
                },
            }
            with self.assertRaises(AnalysisRecorderError):
                LiveAnalysisRecorder().start({**status, "phase": "IDLE"})
            recorder.start(status, max_complete_frames=3)
            frequency = np.arange(513, dtype=float) * 48000.0 / 1024.0
            for index in range(1, 6):
                amplitude = np.zeros(513, dtype=float)
                amplitude[21] = 0.1 + index / 1000
                dbfs = 20 * np.log10(np.maximum(amplitude, 1e-12))
                metrics = {
                    "peaks": [{
                        "bin": 21,
                        "frequency_hz": float(frequency[21]),
                        "dbfs": float(dbfs[21]),
                    }],
                    "tone_checks_passed": True,
                    "nonzero_bins": 1,
                }
                payload = {
                    "run_id": status["run_id"],
                    "frame_id": index,
                    "sequence": 100 + index,
                    "elapsed_s": index * 0.2,
                    "window_name": "hann",
                    "fs_hz": 48000.0,
                    "N": 1024,
                    "frequency_hz": frequency.tolist(),
                    "amplitude": amplitude.tolist(),
                    "dbfs": dbfs.tolist(),
                    "metrics": metrics,
                }
                recorder.observe(
                    np.arange(1024, dtype=np.uint64),
                    {"frame_sequence": 100 + index},
                    {"window_name": "hann"},
                    metrics,
                    payload,
                    {"elapsed_s": index * 0.2},
                )
            stopped = recorder.stop()
            self.assertEqual(stopped["saved_complete_count"], 3)
            self.assertEqual(stopped["saved_metric_count"], 5)
            snapshot = recorder.snapshot()
            record = store.save_analysis("用户分析测试", snapshot)
            self.assertEqual(record["record_status"], "COMPLETE_REPLAY")
            folder = store._record_dir(record["record_id"])
            self.assertTrue((folder / "sample_index.json").is_file())
            self.assertTrue((folder / "metric_timeline.jsonl").is_file())
            self.assertEqual(len(list((folder / "frames").glob("*_words.npy"))), 3)

            service = UserAnalysisService(store)
            index = service.activate(record["record_id"])
            self.assertEqual(index["source"], "USER_RECORD")
            self.assertEqual(index["runs"][0]["saved_samples"], 3)
            run_id = index["runs"][0]["run_id"]
            frame = service.frame_payload(run_id, 3)
            self.assertEqual(frame["mode"], "USER_RECORD")
            self.assertEqual(frame["frame_id"], 3)
            self.assertEqual(len(frame["amplitude"]), 513)
            exported = service.export_payload({
                "run_id": run_id,
                "observed_frame_ids": [3],
                "current_frame_id": 3,
                "average_length": 8,
                "cursor_curve": "current",
                "cursors": {"A": 21, "B": 22},
                "trend": {"mode": "max_peak"},
            })
            self.assertEqual(exported["status"], "OK")
            self.assertEqual(
                exported["summary"]["source"]["context"],
                "USER_SAVED_LIVE_ANALYSIS")
            self.assertTrue(
                (Path(exported["package_path"]) / "manifest.json").is_file())

    def test_user_response_record_saves_raw_points_and_plot(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = RecordStore(Path(temporary) / "records")
            calibration = (
                ROOT / "bplus" / "reports" / "B-X11"
                / "signal_generator_20261101" / "channel_calibration.json")
            recorder = UserResponseRecorder(calibration)
            recorder.start({
                "actual_r_ohm": 2200.0,
                "actual_c_nf": 100.0,
                "temperature": "25 C",
                "generator": "test generator",
            })
            from rc.rc_model import transfer
            n = np.arange(1024, dtype=float)
            for frequency in (200.0, 300.0, 500.0):
                h = transfer(frequency, 2200.0, 100.0e-9)
                phase = 2 * np.pi * frequency * n / 48000.0 + 0.2
                left = 0.1 * np.cos(phase)
                right = 0.1 * abs(h) * np.cos(phase + np.angle(h))
                samples = np.rint(np.vstack((left, right)) * (2 ** 23)).astype(np.int32)
                recorder.add_capture(
                    frequency, samples, 48000.0,
                    "response_{:.0f}".format(frequency))
            recorder.stop()
            record = store.save_response(
                "用户频率响应测试", recorder.snapshot())
            self.assertEqual(record["point_count"], 3)
            folder = store._record_dir(record["record_id"])
            self.assertTrue((folder / "points.csv").is_file())
            self.assertTrue((folder / "gain_phase.png").is_file())
            self.assertEqual(
                len(list((folder / "raw").glob("*_stereo.npy"))), 3)
            svg = (folder / "gain_phase.svg").read_text(encoding="utf-8")
            self.assertIn("R=2200 ohm", svg)
            self.assertIn("C=100 nF", svg)
            csv_bytes, mime, filename = store.response_download(
                record["record_id"], "csv")
            self.assertEqual(mime, "text/csv; charset=utf-8")
            self.assertEqual(
                filename, record["record_id"] + "_points.csv")
            self.assertIn(
                b"target_hz,estimated_frequency_hz",
                csv_bytes)
            json_bytes, mime, filename = store.response_download(
                record["record_id"], "json")
            self.assertEqual(mime, "application/json; charset=utf-8")
            self.assertEqual(filename, record["record_id"] + ".json")
            self.assertEqual(
                json.loads(json_bytes)["record_id"], record["record_id"])

            analysis = store.save(
                "analysis", "不可下载的分析记录", "实时频谱", {})
            with self.assertRaises(RecordStoreError):
                store.response_download(analysis["record_id"], "csv")
            with self.assertRaises(RecordStoreError):
                store.response_download(record["record_id"], "xml")

    def test_generic_system_response_has_no_rc_theory_assumption(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = RecordStore(Path(temporary) / "records")
            calibration = (
                ROOT / "bplus" / "reports" / "B-X11"
                / "signal_generator_20261101" / "channel_calibration.json")
            recorder = UserResponseRecorder(
                calibration, response_kind="generic_system")
            recorder.start({
                "dut_name": "通用被测系统",
                "dut_model": "TEST-1",
                "temperature": "25 C",
                "generator": "test generator",
            })
            n = np.arange(1024, dtype=float)
            for frequency, gain, phase_deg in (
                    (500.0, 0.8, -20.0),
                    (1000.0, 0.5, -40.0),
                    (2000.0, 0.2, -70.0)):
                phase = 2 * np.pi * frequency * n / 48000.0 + 0.2
                left = 0.1 * np.cos(phase)
                right = 0.1 * gain * np.cos(
                    phase + np.deg2rad(phase_deg))
                samples = np.rint(
                    np.vstack((left, right)) * (2 ** 23)).astype(np.int32)
                recorder.add_capture(
                    frequency, samples, 48000.0,
                    "generic_{:.0f}".format(frequency))
            recorder.stop()
            record = store.save_response(
                "通用系统响应测试", recorder.snapshot())
            self.assertEqual(record["response_kind"], "generic_system")
            self.assertTrue(
                record["record_id"].startswith("response_generic_"))
            data = store.load(record["record_id"])
            self.assertEqual(data["response_kind"], "generic_system")
            self.assertFalse(
                any("theory" in point for point in data["points"]))

    def test_generic_wrong_target_frequency_reports_phasor_diagnostic(self):
        with tempfile.TemporaryDirectory() as temporary:
            calibration = (
                ROOT / "bplus" / "reports" / "B-X11"
                / "signal_generator_20261101" / "channel_calibration.json")
            recorder = UserResponseRecorder(
                calibration, response_kind="generic_system")
            recorder.start({
                "dut_name": "诊断系统",
                "temperature": "25 C",
            })
            n = np.arange(1024, dtype=float)
            phase = 2 * np.pi * 1000.0 * n / 48000.0 + 0.2
            samples = np.rint(
                np.vstack((np.cos(phase), np.cos(phase)))
                * 0.1 * (2 ** 23)).astype(np.int32)
            with self.assertRaises(ResponseRecorderError) as raised:
                recorder.add_capture(
                    1200.0, samples, 48000.0, "wrong_target")
            self.assertIn("正弦相量估计失败", str(raised.exception))
            rejected = recorder.status()["last_rejected"]
            self.assertEqual(rejected["target_hz"], 1200.0)
            self.assertIn(
                "POOR_FIT_OR_SYNC_UNVERIFIED", rejected["reasons"])


if __name__ == "__main__":
    unittest.main()
