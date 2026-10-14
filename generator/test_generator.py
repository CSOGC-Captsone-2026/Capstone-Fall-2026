#!/usr/bin/env python3
"""
Unit tests for generator.py (standard library only).

Run from the repo root:
    python3 -m unittest discover -s generator -v
or from inside the generator/ folder:
    python3 -m unittest -v
"""

import csv
import io
import json
import math
import os
import random
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generator as g  # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parent / "sensors.json"

PHASES = [
    {"name": "rest",     "minutes": 10, "activity": 0.0},
    {"name": "eva_task", "minutes": 30, "activity": 1.0},
    {"name": "rest",     "minutes": 5,  "activity": 0.0},
    {"name": "eva_task", "minutes": 25, "activity": 0.8},
    {"name": "cooldown", "minutes": 10, "activity": 0.2},
]


def simple_sensor(**overrides):
    """A minimal, noise-free sensor so values can be checked exactly."""
    s = {
        "unit": "u", "rate_hz": 1,
        "normal": [100, 100], "limits": [0, 1000],
        "critical": {"high": 200},
        "activity_effect": 1.5, "noise": 0.0, "drift_per_min": 0.0,
        "spike_delta": 50,
        "anomalies": ["ramp", "spike", "stuck", "dropout", "contextual"],
    }
    s.update(overrides)
    return s


def flat_curves(total_s, level):
    """Activity curve held at one level, plus its running total."""
    curve = [level] * total_s
    return curve, g.cumulative_minutes(curve)


# ---------------------------------------------------------------------------
# build_timeline
# ---------------------------------------------------------------------------

class TestBuildTimeline(unittest.TestCase):

    def setUp(self):
        self.windows, self.targets = g.build_timeline(PHASES)

    def test_total_length(self):
        self.assertEqual(len(self.targets), 80 * 60)
        self.assertEqual(self.windows[-1]["end"], 80 * 60)

    def test_windows_are_contiguous(self):
        self.assertEqual(self.windows[0]["start"], 0)
        for prev, nxt in zip(self.windows, self.windows[1:]):
            self.assertEqual(prev["end"], nxt["start"])

    def test_targets_match_phases(self):
        for w in self.windows:
            segment = self.targets[w["start"]:w["end"]]
            self.assertTrue(all(v == w["activity"] for v in segment), w["name"])

    def test_phase_boundary_is_start_inclusive(self):
        # second 599 is still rest, second 600 is the first EVA second
        self.assertEqual(self.targets[599], 0.0)
        self.assertEqual(self.targets[600], 1.0)


# ---------------------------------------------------------------------------
# smooth
# ---------------------------------------------------------------------------

class TestSmooth(unittest.TestCase):

    def test_zero_response_follows_targets_exactly(self):
        targets = [0, 0, 1, 1, 0]
        self.assertEqual(g.smooth(targets, 0), targets)

    def test_reaches_63_percent_after_tau(self):
        tau = 45
        curve = g.smooth([0.0] + [1.0] * 200, tau)
        # curve[n] is the level after n steps toward 1
        self.assertAlmostEqual(curve[tau], 1 - math.exp(-1), places=9)
        self.assertAlmostEqual(curve[3 * tau], 1 - math.exp(-3), places=9)

    def test_starts_settled_at_first_target(self):
        curve = g.smooth([0.4] * 10, 30)
        self.assertTrue(all(abs(v - 0.4) < 1e-12 for v in curve))

    def test_never_overshoots(self):
        for tau in (0.3, 1, 45, 900):
            curve = g.smooth([0.0] * 5 + [1.0] * 100 + [0.0] * 100, tau)
            self.assertTrue(all(0.0 <= v <= 1.0 for v in curve), f"tau={tau}")

    def test_rises_monotonically_toward_higher_target(self):
        curve = g.smooth([0.0] + [1.0] * 300, 60)
        self.assertTrue(all(b >= a for a, b in zip(curve, curve[1:])))

    def test_slower_sensor_lags_more(self):
        targets = [0.0] + [1.0] * 600
        fast, slow = g.smooth(targets, 45), g.smooth(targets, 900)
        self.assertGreater(fast[300], slow[300])


# ---------------------------------------------------------------------------
# cumulative_minutes
# ---------------------------------------------------------------------------

class TestCumulativeMinutes(unittest.TestCase):

    def test_one_minute_of_full_effort_is_one(self):
        self.assertAlmostEqual(g.cumulative_minutes([1.0] * 60)[-1], 1.0)

    def test_half_effort_counts_half(self):
        self.assertAlmostEqual(g.cumulative_minutes([0.5] * 120)[-1], 1.0)

    def test_never_decreases(self):
        out = g.cumulative_minutes([0, 1, 1, 0, 0, 0.5, 0])
        self.assertTrue(all(b >= a for a, b in zip(out, out[1:])))

    def test_same_length_as_input(self):
        self.assertEqual(len(g.cumulative_minutes([0.2] * 37)), 37)


# ---------------------------------------------------------------------------
# critical_side / is_critical
# ---------------------------------------------------------------------------

class TestCritical(unittest.TestCase):

    def test_critical_side(self):
        self.assertEqual(g.critical_side({"critical": {"high": 5000}}), ("high", 5000))
        self.assertEqual(g.critical_side({"critical": {"low": 19.5}}), ("low", 19.5))
        self.assertEqual(g.critical_side({}), (None, None))
        self.assertEqual(g.critical_side({"critical": None}), (None, None))

    def test_is_critical_high_is_inclusive(self):
        self.assertFalse(g.is_critical("high", 5000, 4999.9))
        self.assertTrue(g.is_critical("high", 5000, 5000))
        self.assertTrue(g.is_critical("high", 5000, 6000))

    def test_is_critical_low_is_inclusive(self):
        self.assertFalse(g.is_critical("low", 19.5, 19.6))
        self.assertTrue(g.is_critical("low", 19.5, 19.5))
        self.assertTrue(g.is_critical("low", 19.5, 18.0))

    def test_no_side_is_never_critical(self):
        self.assertFalse(g.is_critical(None, None, 1e9))


# ---------------------------------------------------------------------------
# plan_anomalies
# ---------------------------------------------------------------------------

class TestPlanAnomalies(unittest.TestCase):

    def setUp(self):
        with open(CONFIG_PATH) as f:
            self.cfg = json.load(f)
        self.sensors = {k: s for k, s in self.cfg["sensors"].items() if s.get("enabled", True)}
        self.windows, _ = g.build_timeline(PHASES)
        self.total_s = self.windows[-1]["end"]
        # Plan many sessions so rare cases (e.g. contextual) show up.
        rng = random.Random(123)
        self.plans = [g.plan_anomalies(rng, self.sensors, self.cfg["anomalies"],
                                       self.windows, self.total_s)
                      for _ in range(300)]

    def all_anomalies(self):
        return [a for plan in self.plans for a in plan]

    def test_at_most_per_session(self):
        for plan in self.plans:
            self.assertLessEqual(len(plan), self.cfg["anomalies"]["per_session"])

    def test_type_is_allowed_for_sensor(self):
        for a in self.all_anomalies():
            self.assertIn(a["type"], self.sensors[a["sensor_id"]]["anomalies"])

    def test_only_enabled_sensors(self):
        for a in self.all_anomalies():
            self.assertIn(a["sensor_id"], self.sensors)

    def test_duration_within_configured_range(self):
        for a in self.all_anomalies():
            lo, hi = self.cfg["anomalies"]["duration_min"][a["type"]]
            dur = a["end"] - a["start"]
            self.assertGreaterEqual(dur, int(lo * 60) - 1)
            self.assertLessEqual(dur, int(hi * 60))

    def test_non_contextual_respect_session_margins(self):
        for a in self.all_anomalies():
            if a["type"] != "contextual":
                self.assertGreaterEqual(a["start"], 300)
                self.assertLessEqual(a["end"], self.total_s - 120)

    def test_contextual_inside_quiet_phase_with_margins(self):
        contextual = [a for a in self.all_anomalies() if a["type"] == "contextual"]
        self.assertTrue(contextual, "expected at least one contextual anomaly in 300 sessions")
        for a in contextual:
            homes = [w for w in self.windows
                     if w["start"] + 60 <= a["start"] and a["end"] <= w["end"] - 60]
            self.assertEqual(len(homes), 1, a)
            self.assertLessEqual(homes[0]["activity"], 0.2)

    def test_no_same_sensor_overlap_within_buffer(self):
        for plan in self.plans:
            for i, a in enumerate(plan):
                for b in plan[i + 1:]:
                    if a["sensor_id"] == b["sensor_id"]:
                        gap = max(a["start"], b["start"]) - min(a["end"], b["end"])
                        self.assertGreaterEqual(gap, 60, (a, b))

    def test_all_types_appear(self):
        seen = {a["type"] for a in self.all_anomalies()}
        self.assertEqual(seen, set(g.ANOMALY_TYPES))

    def test_same_seed_same_plan(self):
        args = (self.sensors, self.cfg["anomalies"], self.windows, self.total_s)
        p1 = g.plan_anomalies(random.Random(7), *args)
        p2 = g.plan_anomalies(random.Random(7), *args)
        self.assertEqual(p1, p2)


# ---------------------------------------------------------------------------
# generate_sensor
# ---------------------------------------------------------------------------

class TestGenerateSensor(unittest.TestCase):
    TOTAL = 1200  # 20-minute toy session

    def run_sensor(self, sensor, level=0.0, anomalies=(), base=100, total=None):
        total = total or self.TOTAL
        curve, cum = flat_curves(total, level)
        return g.generate_sensor(random.Random(0), sensor, base, curve, cum,
                                 total, list(anomalies), 1.15)

    def test_rest_value_equals_base_without_noise(self):
        samples, _ = self.run_sensor(simple_sensor(), level=0.0)
        self.assertTrue(all(v == 100 for _, v in samples))

    def test_full_effort_scales_by_activity_effect(self):
        samples, _ = self.run_sensor(simple_sensor(activity_effect=1.6), level=1.0)
        self.assertTrue(all(abs(v - 160) < 1e-9 for _, v in samples))

    def test_drift_adds_linearly(self):
        samples, _ = self.run_sensor(simple_sensor(drift_per_min=2.0))
        t, v = samples[-1]
        self.assertAlmostEqual(v, 100 + 2.0 * t / 60, places=3)

    def test_accumulation_builds_with_effort(self):
        s = simple_sensor(activity_effect=1.0, accumulate_per_min=0.5)
        samples, _ = self.run_sensor(s, level=1.0, base=0)
        t, v = samples[-1]
        self.assertAlmostEqual(v, 0.5 * (t + 1) / 60, places=3)

    def test_sample_count_matches_rate(self):
        for rate in (1, 0.5, 0.2, 0.1):
            samples, _ = self.run_sensor(simple_sensor(rate_hz=rate))
            self.assertEqual(len(samples), math.ceil(self.TOTAL * rate), f"rate={rate}")

    def test_times_are_increasing_and_in_range(self):
        samples, _ = self.run_sensor(simple_sensor(rate_hz=0.2))
        times = [t for t, _ in samples]
        self.assertEqual(times, sorted(times))
        self.assertGreaterEqual(times[0], 0)
        self.assertLess(times[-1], self.TOTAL)

    def test_values_clamped_to_limits(self):
        s = simple_sensor(limits=[0, 120], noise=50.0)
        samples, _ = self.run_sensor(s)
        self.assertTrue(all(0 <= v <= 120 for _, v in samples))

    def test_dropout_leaves_gap(self):
        an = {"type": "dropout", "start": 300, "end": 400}
        samples, _ = self.run_sensor(simple_sensor(), anomalies=[an])
        self.assertFalse([t for t, _ in samples if 300 <= t < 400])
        self.assertEqual(len(samples), self.TOTAL - 100)

    def test_stuck_holds_one_value(self):
        s = simple_sensor(noise=5.0)
        an = {"type": "stuck", "start": 300, "end": 500}
        samples, _ = self.run_sensor(s, anomalies=[an])
        inside = {v for t, v in samples if 300 <= t < 500}
        before = {v for t, v in samples if t < 300}
        self.assertEqual(len(inside), 1)
        self.assertGreater(len(before), 1)  # noise is present outside the anomaly

    def test_spike_moves_toward_danger_high(self):
        an = {"type": "spike", "start": 300, "end": 400}
        samples, _ = self.run_sensor(simple_sensor(spike_delta=50), anomalies=[an])
        inside = [v for t, v in samples if 300 <= t < 400]
        self.assertTrue(all(v == 150 for v in inside))

    def test_spike_moves_toward_danger_low(self):
        s = simple_sensor(critical={"low": 50}, spike_delta=30)
        an = {"type": "spike", "start": 300, "end": 400}
        samples, _ = self.run_sensor(s, anomalies=[an])
        inside = [v for t, v in samples if 300 <= t < 400]
        self.assertTrue(all(v == 70 for v in inside))

    def test_ramp_crosses_critical_inside_window(self):
        an = {"type": "ramp", "start": 300, "end": 900}
        samples, crossings = self.run_sensor(simple_sensor(), anomalies=[an])
        self.assertIn(0, crossings)
        self.assertTrue(300 <= crossings[0] < 900)
        # every value from the crossing to the end of the ramp is critical
        after = [v for t, v in samples if crossings[0] <= t < 900]
        self.assertTrue(all(v >= 200 for v in after))
        # and the value just before the crossing was not
        before = [v for t, v in samples if t < crossings[0]]
        self.assertLess(before[-1], 200)

    def test_low_side_ramp_goes_down(self):
        s = simple_sensor(critical={"low": 50})
        an = {"type": "ramp", "start": 300, "end": 900}
        samples, crossings = self.run_sensor(s, anomalies=[an])
        self.assertIn(0, crossings)
        self.assertLess(min(v for t, v in samples if 300 <= t < 900), 50)

    def test_spike_below_critical_has_no_crossing(self):
        an = {"type": "spike", "start": 300, "end": 400}
        _, crossings = self.run_sensor(simple_sensor(spike_delta=10), anomalies=[an])
        self.assertEqual(crossings, {})

    def test_contextual_looks_like_exertion_during_rest(self):
        an = {"type": "contextual", "start": 300, "end": 400}
        samples, _ = self.run_sensor(simple_sensor(activity_effect=1.5), level=0.0, anomalies=[an])
        inside = {v for t, v in samples if 300 <= t < 400}
        outside = {v for t, v in samples if t < 300 or t >= 400}
        self.assertEqual(inside, {150})
        self.assertEqual(outside, {100})

    def test_values_return_to_normal_after_anomaly(self):
        an = {"type": "spike", "start": 300, "end": 400}
        samples, _ = self.run_sensor(simple_sensor(), anomalies=[an])
        self.assertTrue(all(v == 100 for t, v in samples if t >= 400))


# ---------------------------------------------------------------------------
# main(): end-to-end on the real config
# ---------------------------------------------------------------------------

class TestMainEndToEnd(unittest.TestCase):

    def run_main(self, out_dir, *extra):
        argv = ["generator.py", "--config", str(CONFIG_PATH), "--out", str(out_dir),
                "--sessions", "2", "--subjects", "2", *extra]
        with mock.patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
            g.main()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "run"
        self.run_main(self.out, "--seed", "42")
        with open(CONFIG_PATH) as f:
            self.cfg = json.load(f)
        self.enabled = {k for k, s in self.cfg["sensors"].items() if s.get("enabled", True)}

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, name):
        with open(self.out / name, newline="") as f:
            return list(csv.DictReader(f))

    def test_output_files_and_headers(self):
        expected = {
            "readings.csv": ["timestamp", "session_id", "subject_id", "sensor_id", "value", "unit"],
            "labels.csv":   ["session_id", "subject_id", "sensor_id", "type", "start", "end", "critical_at"],
            "activity.csv": ["session_id", "subject_id", "phase", "activity", "start", "end"],
        }
        for name, header in expected.items():
            with open(self.out / name, newline="") as f:
                self.assertEqual(next(csv.reader(f)), header, name)

    def test_same_seed_is_reproducible(self):
        other = Path(self.tmp.name) / "again"
        self.run_main(other, "--seed", "42")
        for name in ("readings.csv", "labels.csv", "activity.csv"):
            self.assertEqual((self.out / name).read_bytes(), (other / name).read_bytes(), name)

    def test_different_seed_changes_data(self):
        other = Path(self.tmp.name) / "seed7"
        self.run_main(other, "--seed", "7")
        self.assertNotEqual((self.out / "readings.csv").read_bytes(),
                            (other / "readings.csv").read_bytes())

    def test_only_enabled_sensors_present(self):
        sensors = {r["sensor_id"] for r in self.read("readings.csv")}
        self.assertEqual(sensors, self.enabled)

    def test_units_match_config(self):
        for r in self.read("readings.csv")[:2000]:
            self.assertEqual(r["unit"], self.cfg["sensors"][r["sensor_id"]]["unit"])

    def test_readings_sorted_within_each_session(self):
        last = {}
        for r in self.read("readings.csv"):
            ts = r["timestamp"]
            self.assertGreaterEqual(ts, last.get(r["session_id"], ""))
            last[r["session_id"]] = ts

    def test_values_within_limits(self):
        for r in self.read("readings.csv"):
            lo, hi = self.cfg["sensors"][r["sensor_id"]]["limits"]
            self.assertTrue(lo <= float(r["value"]) <= hi, r)

    def test_timestamps_parse_as_utc(self):
        for r in self.read("readings.csv")[:500]:
            dt = datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00"))
            self.assertEqual(dt.utcoffset().total_seconds(), 0)

    def test_sessions_do_not_overlap_in_time(self):
        by_session = {}
        for r in self.read("activity.csv"):
            s = by_session.setdefault(r["session_id"], [r["start"], r["end"]])
            s[0], s[1] = min(s[0], r["start"]), max(s[1], r["end"])
        spans = sorted(by_session.values())
        for a, b in zip(spans, spans[1:]):
            self.assertLessEqual(a[1], b[0])

    def test_critical_at_lies_inside_its_anomaly(self):
        for r in self.read("labels.csv"):
            if r["critical_at"]:
                self.assertIn(r["type"], ("ramp", "spike"))
                self.assertTrue(r["start"] <= r["critical_at"] < r["end"], r)

    def test_subjects_rotate(self):
        subjects = {}
        for r in self.read("activity.csv"):
            subjects[r["session_id"]] = r["subject_id"]
        self.assertEqual(subjects, {"S001": "A1", "S002": "A2"})


if __name__ == "__main__":
    unittest.main()