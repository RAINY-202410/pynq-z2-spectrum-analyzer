"""B-X08 offline read-only status subscription and dedupe.

The offline part only GETs an existing /api/status JSON response. It never
posts start/stop/render commands and never imports PYNQ. A fixture or an
actual status endpoint can be used; the latter is intentionally not run here.
"""

import argparse
import json
import math
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

import numpy as np

from spectrum_features import SpectrumAccumulator

STEP = "B-X08"
EXTENSION_ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = EXTENSION_ROOT / "reports" / "B-X08"


class SubscriptionError(ValueError):
    """Raised for malformed status payloads."""


class StatusSubscriber:
    """Read-only latest-frame subscriber with explicit dedupe and gaps."""

    def __init__(self, service_address, average_length=8, max_seen=4096,
                 max_history=4096):
        self.service_address = service_address.rstrip("/")
        self.average_length = average_length
        self.max_seen = max_seen
        self.max_history = max_history
        self.seen = set()
        self.seen_order = []
        self.duplicates = 0
        self.skipped = 0
        self.accepted = 0
        self.gaps = []
        self.runs = []
        self.run_id = None
        self.process_id = None
        self.last_frame_id = None
        self.last_sequence = None
        self.features = SpectrumAccumulator(average_length=average_length)
        self.history = []

    def _remember(self, key):
        if key in self.seen:
            return
        self.seen.add(key)
        self.seen_order.append(key)
        while len(self.seen_order) > self.max_seen:
            old = self.seen_order.pop(0)
            self.seen.discard(old)

    def _reset_run(self, run_id, process_id):
        if run_id == self.run_id and process_id == self.process_id:
            return False
        self.run_id = run_id
        self.process_id = process_id
        self.last_frame_id = None
        self.last_sequence = None
        self.features = SpectrumAccumulator(average_length=self.average_length)
        self.history = []
        if run_id not in self.runs:
            self.runs.append(run_id)
        return True

    @staticmethod
    def _frame_id(status, latest):
        if latest.get("frame_id") is not None:
            return int(latest["frame_id"])
        if status.get("frames") is None:
            return None
        return int(status["frames"])

    def accept_status(self, status):
        if not isinstance(status, dict):
            raise SubscriptionError("status must be a JSON object")
        latest = status.get("latest")
        run_id = status.get("run_id")
        if not run_id or not isinstance(latest, dict):
            self.skipped += 1
            return {"accepted": False, "skipped": True, "reason": "no latest frame/run_id"}
        process_id = status.get("process_id", "UNKNOWN")
        frame_id = self._frame_id(status, latest)
        if frame_id is None:
            self.skipped += 1
            return {"accepted": False, "skipped": True, "reason": "no frame_id"}
        key = (self.service_address, process_id, run_id, frame_id)
        if key in self.seen:
            self.duplicates += 1
            return {
                "accepted": False,
                "duplicate": True,
                "key": list(key),
                "reason": "same service/process/run/frame already observed",
            }
        self._remember(key)
        new_run = self._reset_run(run_id, process_id)
        sequence = latest.get("sequence")
        if sequence is None:
            raise SubscriptionError("latest frame must contain sequence")
        sequence = int(sequence)
        gap = None
        sequence_gap = None
        out_of_order = False
        if self.last_frame_id is not None:
            if frame_id > self.last_frame_id + 1:
                gap = {
                    "from_frame_id": self.last_frame_id,
                    "to_frame_id": frame_id,
                    "missing_frame_count": frame_id - self.last_frame_id - 1,
                }
                self.gaps.append(gap)
            elif frame_id < self.last_frame_id:
                out_of_order = True
            if sequence != ((self.last_sequence + 1) & 0xFFFFFFFF):
                sequence_gap = {
                    "from_sequence": self.last_sequence,
                    "to_sequence": sequence,
                }
        window = latest.get("window_name", latest.get("window"))
        fs_hz = float(latest["fs_hz"])
        n_fft = int(latest["N"])
        elapsed = float(status.get("elapsed_s"))
        if not math.isfinite(fs_hz) or fs_hz <= 0 or n_fft <= 0:
            raise SubscriptionError("invalid fs_hz/N")
        if not math.isfinite(elapsed):
            raise SubscriptionError("elapsed_s must be finite")
        amplitude = [float(value) for value in latest.get("amplitude", [])]
        frame = {
            "source": latest.get("source", "PL_FFT"),
            "mode": latest.get("mode", status.get("mode", "LIVE")),
            "run_id": run_id,
            "frame_id": frame_id,
            "sequence": sequence,
            "elapsed_s": elapsed,
            "window_name": window,
            "fs_hz": fs_hz,
            "N": n_fft,
            "amplitude": amplitude,
            "metrics": latest.get("metrics") if isinstance(latest.get("metrics"), dict) else {},
        }
        feature = self.features.add(frame)
        history_record = {
            "record_type": "metric",
            "run_id": run_id,
            "run_label": run_id,
            "frame_id": frame_id,
            "sequence": sequence,
            "elapsed_s": elapsed,
            "window": window,
            "fs_hz": fs_hz,
            "N": n_fft,
            "metrics": frame["metrics"],
        }
        self.history.append(history_record)
        if len(self.history) > self.max_history:
            self.history.pop(0)
        self.last_frame_id = frame_id
        self.last_sequence = sequence
        self.accepted += 1
        return {
            "accepted": True,
            "duplicate": False,
            "new_run": new_run,
            "key": list(key),
            "frame": {
                "run_id": run_id,
                "process_id": process_id,
                "frame_id": frame_id,
                "sequence": sequence,
                "elapsed_s": elapsed,
                "window": window,
                "fs_hz": fs_hz,
                "N": n_fft,
            },
            "gap": gap,
            "sequence_gap": sequence_gap,
            "out_of_order": out_of_order,
            "feature_average_count": feature["average"]["count"] if feature["average"] else 0,
            "feature_hold_count": feature["hold"]["count"] if feature["hold"] else 0,
        }

    def poll_once(self, status_url=None, timeout=3.0, fetcher=None):
        url = status_url or (self.service_address.rstrip("/") + "/api/status")
        if fetcher is not None:
            status = fetcher(url)
        else:
            with urlopen(url, timeout=timeout) as response:
                if response.status != 200:
                    raise SubscriptionError("status HTTP " + str(response.status))
                status = json.loads(response.read().decode("utf-8"))
        return self.accept_status(status)

    def feature_snapshot(self):
        return self.features.snapshot()

    def trend_snapshot(self, mode="max_peak", target_hz=None, bandwidth_hz=None,
                       rules=None):
        if not self.history:
            return None
        import timeline_features
        return timeline_features.analyze(
            self.history, self.run_id, mode, target_hz, bandwidth_hz,
            rules=rules,
        )

    def summary(self):
        return {
            "service_address": self.service_address,
            "accepted": self.accepted,
            "duplicates": self.duplicates,
            "skipped": self.skipped,
            "runs": list(self.runs),
            "gaps": list(self.gaps),
            "latest_frame_id": self.last_frame_id,
            "latest_sequence": self.last_sequence,
            "feature_average_count": self.feature_snapshot()["average"]["count"]
            if self.feature_snapshot()["average"] else 0,
            "feature_hold_count": self.feature_snapshot()["hold"]["count"]
            if self.feature_snapshot()["hold"] else 0,
        }


def _synthetic_latest(sequence, amplitude, frame_number):
    frequency = np.arange(513, dtype=float) * 48000.0 / 1024.0
    metrics = {
        "peaks": [{
            "bin": 21,
            "frequency_hz": float(frequency[21]),
            "estimated_frequency_hz": 1000.0,
            "interpolated": True,
            "amplitude": float(amplitude[21]),
            "dbfs": float(20 * np.log10(max(amplitude[21], 1e-12))),
        }],
        "tones": [{"expected_hz": 1000.0, "peak_bin": 21, "peak_hz": float(frequency[21]),
                   "amplitude": float(amplitude[21]),
                   "dbfs": float(20 * np.log10(max(amplitude[21], 1e-12))),
                   "within_one_bin": True, "nonzero": True}],
        "tone_checks_passed": True,
        "max_nondc_dbfs": float(20 * np.log10(max(float(np.max(amplitude[1:])), 1e-12))),
        "nonzero_bins": int(np.count_nonzero(amplitude)),
        "amplitude_calibrated": False,
    }
    return {
        "source": "PL_FFT",
        "mode": "LIVE",
        "sequence": sequence,
        "frame_id": frame_number,
        "fs_hz": 48000.0,
        "N": 1024,
        "window_name": "hann",
        "window_sum": 511.50006103515625,
        "frequency_hz": frequency.tolist(),
        "amplitude": [float(value) for value in amplitude],
        "dbfs": [float(20 * np.log10(max(value, 1e-12))) for value in amplitude],
        "metrics": metrics,
    }


def synthetic_statuses():
    """Controllable offline status sequence: duplicate, gap, run switch."""
    base = np.zeros(513, dtype=float)
    base[21] = 0.1
    base[64] = 0.05

    def status(process_id, run_id, frames, sequence, elapsed, latest=True):
        return {
            "process_id": process_id,
            "run_id": run_id,
            "mode": "LIVE",
            "context": "BOARD_LIVE",
            "phase": "RUNNING",
            "frames": frames,
            "elapsed_s": elapsed,
            "latest": _synthetic_latest(sequence, base, frames) if latest else None,
        }

    first = status(4101, "offline_run_a", 1, 100, 0.2)
    duplicate = status(4101, "offline_run_a", 1, 100, 0.2)
    second = status(4101, "offline_run_a", 2, 101, 0.4)
    gap = status(4101, "offline_run_a", 5, 104, 1.0)
    no_latest = status(4101, "offline_run_a", 6, 105, 1.2, latest=False)
    other_run = status(4102, "offline_run_b", 1, 200, 0.3)
    return [first, duplicate, second, gap, no_latest, other_run]


def run_statuses(statuses, service_address="offline_fixture"):
    subscriber = StatusSubscriber(service_address)
    transcript = []
    for status in statuses:
        transcript.append(subscriber.accept_status(status))
    return subscriber, transcript


def write_report(out_dir, subscriber, transcript, source="OFFLINE_FIXTURE"):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot = subscriber.feature_snapshot()
    payload = {
        "step": STEP,
        "source": source,
        "read_only": True,
        "endpoint_scope": "GET /api/status only",
        "dedupe_key": "(service_address, process_id, run_id, frame_id)",
        "frame_id_fallback": "status.frames when latest.frame_id is absent",
        "summary": subscriber.summary(),
        "transcript": transcript,
        "feature": {
            "average_length": snapshot["average_length"],
            "average_count": snapshot["average"]["count"] if snapshot["average"] else 0,
            "hold_count": snapshot["hold"]["count"] if snapshot["hold"] else 0,
            "group": snapshot["group"],
            "current_frame_id": snapshot["current"]["frame_id"] if snapshot["current"] else None,
        },
    }
    (out_dir / "subscription_report.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8")
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="actual status endpoint; not required for offline fixture")
    parser.add_argument("--fixture", help="JSON object or JSONL status file")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--interval", type=float, default=0.2)
    args = parser.parse_args(argv)

    if args.fixture:
        fixture = Path(args.fixture)
        text = fixture.read_text(encoding="utf-8").strip()
        if text.startswith("["):
            statuses = json.loads(text)
        else:
            statuses = [json.loads(line) for line in text.splitlines() if line.strip()]
        subscriber, transcript = run_statuses(statuses, "offline_fixture")
        source = "OFFLINE_FIXTURE"
    elif args.url:
        service = "{0.scheme}://{0.netloc}".format(urlparse(args.url))
        subscriber = StatusSubscriber(service)
        transcript = []
        for _ in range(max(1, args.count)):
            transcript.append(subscriber.poll_once(args.url))
            time.sleep(max(0, args.interval))
        source = "LIVE_STATUS_READ_ONLY_NOT_RUN_IN_B_X08_OFFLINE"
    else:
        statuses = synthetic_statuses()
        subscriber, transcript = run_statuses(statuses, "offline_fixture")
        source = "OFFLINE_SYNTHETIC_STATUS"

    payload = write_report(args.out, subscriber, transcript, source)
    print(json.dumps({
        "step": STEP,
        "source": source,
        "accepted": payload["summary"]["accepted"],
        "duplicates": payload["summary"]["duplicates"],
        "skipped": payload["summary"]["skipped"],
        "gaps": len(payload["summary"]["gaps"]),
        "runs": payload["summary"]["runs"],
        "read_only": payload["read_only"],
    }, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
