"""
Tests for the generator adapter (anomaly_eval/generated.py).

They run the real generator with a fixed seed into a temporary folder, so they
check the adapter against the generator's actual output format.

    python3 -m unittest tests.test_generated -v
"""

import csv
import tempfile
import unittest
from pathlib import Path

from anomaly_eval import RuleBasedDetector, run
from anomaly_eval.generated import GENERATOR_DIR, _find, generate, load_limits, load_sessions

KINDS = {"ramp", "spike", "stuck", "dropout", "contextual"}


class TestGeneratedSessions(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = generate(Path(cls.tmp.name) / "a", sessions=3, seed=11)
        cls.sessions = load_sessions(cls.dir)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_one_object_per_session_with_subjects_rotating(self):
        self.assertEqual([s.subject for s in self.sessions], ["A1", "A2", "A3"])

    def test_every_csv_reading_is_loaded(self):
        with open(self.dir / "readings.csv", newline="") as f:
            n_csv = sum(1 for _ in csv.DictReader(f))
        self.assertEqual(sum(len(s.build()[0]) for s in self.sessions), n_csv)

    def test_every_label_is_loaded(self):
        with open(self.dir / "labels.csv", newline="") as f:
            n_csv = sum(1 for _ in csv.DictReader(f))
        self.assertEqual(sum(len(s.build()[1]) for s in self.sessions), n_csv)

    def test_readings_are_time_ordered_and_inside_the_session(self):
        for s in self.sessions:
            readings, _ = s.build()
            times = [r.t for r in readings]
            self.assertEqual(times, sorted(times))
            self.assertGreaterEqual(times[0], 0)
            self.assertLess(times[-1], s.duration_s)

    def test_phase_and_activity_attached(self):
        for s in self.sessions:
            readings, _ = s.build()
            self.assertEqual(readings[0].phase, "rest")
            self.assertIn("eva_task", {r.phase for r in readings})
            self.assertTrue(all(0.0 <= r.activity <= 1.0 for r in readings))

    def test_events_are_well_formed(self):
        for s in self.sessions:
            _, events = s.build()
            for e in events:
                self.assertIn(e.kind, KINDS)
                self.assertTrue(0 <= e.start < e.end <= s.duration_s, e)
                if e.critical_at is not None:
                    self.assertTrue(e.start <= e.critical_at < e.end, e)

    def test_limits_come_from_the_config(self):
        limits = load_limits(_find(GENERATOR_DIR, "sensors.json"))
        self.assertIn("co2", limits)
        self.assertEqual(limits["o2"][0], "low")
        self.assertEqual(self.sessions[0].limits, limits)

    def test_same_seed_gives_identical_sessions(self):
        with tempfile.TemporaryDirectory() as t:
            again = load_sessions(generate(Path(t) / "b", sessions=3, seed=11))
        self.assertEqual([s.build() for s in again], [s.build() for s in self.sessions])

    def test_different_seed_gives_different_data(self):
        with tempfile.TemporaryDirectory() as t:
            other = load_sessions(generate(Path(t) / "c", sessions=1, seed=12))
        self.assertNotEqual(other[0].build()[0][:50], self.sessions[0].build()[0][:50])

    def test_detector_runs_end_to_end(self):
        result = run(RuleBasedDetector(), self.sessions[0])
        self.assertEqual(len(result.events), len(self.sessions[0].build()[1]))


if __name__ == "__main__":
    unittest.main()