"""B-X06 peak selection, trend, and event-state checks."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import timeline_features as tf  # noqa: E402


def peer_peak(bin_index, frequency, amplitude=0.1, interpolated=False,
              estimated=None):
    return {
        "bin": bin_index,
        "frequency_hz": frequency,
        "estimated_frequency_hz": frequency if estimated is None else estimated,
        "interpolated": interpolated,
        "amplitude": amplitude,
        "dbfs": 20.0 * __import__("math").log10(max(amplitude, 1e-12)),
    }


class TimelineFeaturesTest(unittest.TestCase):
    def test_max_peak_and_target_band_selection(self):
        record = {
            "metrics": {
                "peaks": [
                    peer_peak(21, 984.0, 0.2, True, 1000.7),
                    peer_peak(1, 46.0, 0.01),
                ],
                "tone_checks_passed": True,
            }
        }
        maximum = tf.select_peak(record, "max_peak")
        self.assertTrue(maximum["valid"])
        self.assertEqual(maximum["bin"], 21)
        self.assertEqual(maximum["discrete_frequency_hz"], 984.0)
        self.assertEqual(maximum["estimated_frequency_hz"], 1000.7)
        self.assertTrue(maximum["interpolated"])
        target = tf.select_peak(record, "target_band", 1000.0, 100.0)
        self.assertTrue(target["valid"])
        self.assertEqual(target["bin"], 21)
        missing = tf.select_peak(record, "target_band", 3000.0, 100.0)
        self.assertFalse(missing["valid"])
        self.assertIn("不从标量日志重建频谱", missing["missing_reason"])

    def test_hysteresis_consecutive_gap_and_missing_states(self):
        synthetic = tf.synthetic_validation()
        events = synthetic["events"]
        self.assertEqual(len(events), 4)
        self.assertEqual([item["rule"] for item in events],
                         ["amplitude_below", "frequency_outside",
                          "missing_peak", "amplitude_below"])
        amplitude = events[0]
        self.assertEqual((amplitude["start_frame_id"], amplitude["end_frame_id"]), (2, 3))
        self.assertEqual(amplitude["closure"], "recovered")
        frequency = events[1]
        self.assertEqual((frequency["start_frame_id"], frequency["end_frame_id"]), (7, 8))
        missing = events[2]
        self.assertEqual((missing["start_frame_id"], missing["end_frame_id"]), (11, 13))
        after_gap = events[3]
        self.assertEqual(after_gap["start_frame_id"], 17)
        self.assertEqual(after_gap["end_frame_id"], 18)
        self.assertTrue(after_gap["open_at_end"])
        self.assertTrue(all(item["source"] == "SYNTHETIC_TEST" for item in events))
        self.assertTrue(all(item["board_fault"] is False for item in events))
        self.assertTrue(all(item["continuity_verified"] for item in events))

    def test_real_long_and_silence_analysis(self):
        records = tf.load_metric_records()
        long = tf.analyze(records, "spectrum_569e5f254203", "max_peak",
                          rules={
                              "amplitude_below": {"threshold_dbfs": -20.0},
                              "frequency_outside": {"enabled": False},
                              "missing_peak": {"enabled": True},
                          })
        self.assertEqual(long["point_count"], 3100)
        self.assertEqual(long["valid_count"], 3100)
        self.assertEqual(long["continuity_gap_count"], 0)
        self.assertEqual(long["events"], [])
        silence = tf.analyze(records, "spectrum_15131a729d8b", "target_band",
                             1000.0, 100.0,
                             rules={
                                 "amplitude_below": {"enabled": False},
                                 "frequency_outside": {"enabled": False},
                                 "missing_peak": {"enabled": True,
                                                  "min_consecutive": 2,
                                                  "recover_consecutive": 2},
                             })
        self.assertEqual(silence["point_count"], 40)
        self.assertEqual(silence["missing_count"], 40)
        self.assertTrue(silence["events"])
        self.assertTrue(all(item["rule"] == "missing_peak" for item in silence["events"]))

    def test_gap_breaks_continuity(self):
        records = [
            {"run_id": "r", "frame_id": 1, "elapsed_s": 0.0, "metrics": {"peaks": []}},
            {"run_id": "r", "frame_id": 2, "elapsed_s": 0.2, "metrics": {"peaks": []}},
            {"run_id": "r", "frame_id": 3, "elapsed_s": 10.2, "metrics": {"peaks": []}},
        ]
        trend = tf.build_trend(records, "r", "max_peak", max_gap_s=1.0)
        self.assertTrue(trend["points"][2]["continuity_gap"])
        events = tf.detect_events(trend["points"], {
            "amplitude_below": {"enabled": False},
            "frequency_outside": {"enabled": False},
            "missing_peak": {"enabled": True, "min_consecutive": 1,
                             "recover_consecutive": 1},
        })
        self.assertEqual(len(events), 2)
        self.assertTrue(all(item["open_at_end"] or item["end_frame_id"] == 2 for item in events))


if __name__ == "__main__":
    unittest.main()
