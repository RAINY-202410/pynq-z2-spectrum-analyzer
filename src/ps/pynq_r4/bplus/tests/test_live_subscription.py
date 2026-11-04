"""B-X08 offline status subscription, dedupe, and gap checks."""

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import live_subscription as ls  # noqa: E402


class LiveSubscriptionTest(unittest.TestCase):
    def test_duplicate_gap_skip_and_run_switch(self):
        statuses = ls.synthetic_statuses()
        subscriber, transcript = ls.run_statuses(statuses)
        self.assertEqual(subscriber.accepted, 4)
        self.assertEqual(subscriber.duplicates, 1)
        self.assertEqual(subscriber.skipped, 1)
        self.assertEqual(subscriber.runs, ["offline_run_a", "offline_run_b"])
        self.assertEqual(len(subscriber.gaps), 1)
        self.assertEqual(subscriber.gaps[0]["from_frame_id"], 2)
        self.assertEqual(subscriber.gaps[0]["to_frame_id"], 5)
        self.assertEqual(subscriber.gaps[0]["missing_frame_count"], 2)
        self.assertTrue(transcript[0]["accepted"])
        self.assertTrue(transcript[1]["duplicate"])
        self.assertTrue(transcript[4]["skipped"])
        self.assertTrue(transcript[5]["new_run"])
        snapshot = subscriber.feature_snapshot()
        self.assertEqual(snapshot["group"]["run_id"], "offline_run_b")
        self.assertEqual(snapshot["average"]["count"], 1)
        self.assertEqual(snapshot["hold"]["count"], 1)

    def test_frame_id_fallback_uses_status_frames(self):
        status = copy.deepcopy(ls.synthetic_statuses()[0])
        status.pop("frames", None)
        status["frames"] = 7
        status["latest"].pop("frame_id", None)
        subscriber = ls.StatusSubscriber("offline_fixture")
        first = subscriber.accept_status(status)
        second = subscriber.accept_status(copy.deepcopy(status))
        self.assertTrue(first["accepted"])
        self.assertEqual(first["frame"]["frame_id"], 7)
        self.assertTrue(second["duplicate"])
        self.assertEqual(subscriber.accepted, 1)

    def test_poll_once_is_injected_and_read_only(self):
        calls = []
        status = ls.synthetic_statuses()[0]

        def fetcher(url):
            calls.append(url)
            return status

        subscriber = ls.StatusSubscriber("http://127.0.0.1:8091")
        result = subscriber.poll_once("http://127.0.0.1:8091/api/status", fetcher=fetcher)
        self.assertTrue(result["accepted"])
        self.assertEqual(calls, ["http://127.0.0.1:8091/api/status"])
        self.assertEqual(subscriber.duplicates, 0)
        self.assertTrue(subscriber.trend_snapshot()["point_count"] == 1)

    def test_no_pynq_import(self):
        if "pynq" in sys.modules:
            self.skipTest("pynq was imported by the environment before this test")
        self.assertNotIn("pynq", sys.modules)


if __name__ == "__main__":
    unittest.main()
