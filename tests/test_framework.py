"""
Tests for the framework itself (scenarios, scoring, runner).
These should always pass, whatever detector you are developing.

Run from the repo root:
    python3 -m unittest tests.test_framework -v
"""

import unittest

from anomaly_eval import Alert, CausalityError, Event, Scenario, run, score
from anomaly_eval import library


class _OverLimit:
    """Minimal stand-in detector for these tests: alerts on any reading past its limit."""
    def reset(self, subject, limits):
        self.limits = limits

    def observe(self, r):
        side, thr = self.limits[r.sensor]
        over = r.value >= thr if side == "high" else r.value <= thr
        return [Alert(r.t, r.sensor, "limit")] if over else []


class TestScenarios(unittest.TestCase):

    def test_same_scenario_builds_identical_data(self):
        a = library.co2_scrubber_failure().build()
        b = library.co2_scrubber_failure().build()
        self.assertEqual(a, b)

    def test_different_scenarios_have_different_noise(self):
        a, _ = library.nominal_eva().build()
        b, _ = library.co2_sensor_stuck().build()
        self.assertNotEqual([r.value for r in a[:50]], [r.value for r in b[:50]])

    def test_readings_are_time_ordered(self):
        readings, _ = library.nominal_eva().build()
        self.assertEqual(readings, sorted(readings, key=lambda r: (r.t, r.sensor)))

    def test_nominal_has_no_events_and_never_crosses_limits(self):
        s = library.nominal_eva()
        readings, events = s.build()
        self.assertEqual(events, [])
        for r in readings:
            side, thr = s.limits[r.sensor]
            self.assertTrue(r.value < thr if side == "high" else r.value > thr, r)

    def test_ramp_records_when_it_crosses_the_limit(self):
        _, events = library.co2_scrubber_failure().build()
        (ev,) = events
        self.assertIsNotNone(ev.critical_at)
        self.assertTrue(ev.start < ev.critical_at < ev.end)

    def test_downward_ramp_crosses_a_low_limit(self):
        _, (ev,) = library.o2_leak().build()
        self.assertIsNotNone(ev.critical_at)

    def test_dropout_removes_readings(self):
        readings, (ev,) = library.heart_rate_dropout().build()
        gap = [r for r in readings if r.sensor == "heart_rate" and ev.start <= r.t < ev.end]
        self.assertEqual(gap, [])

    def test_stuck_holds_one_value(self):
        readings, (ev,) = library.co2_sensor_stuck().build()
        values = {r.value for r in readings if r.sensor == "co2" and ev.start <= r.t < ev.end}
        self.assertEqual(len(values), 1)

    def test_contextual_happens_during_rest(self):
        readings, (ev,) = library.heart_rate_high_at_rest().build()
        phases = {r.phase for r in readings if r.sensor == "heart_rate" and ev.start <= r.t < ev.end}
        self.assertEqual(phases, {"rest"})

    def test_anomaly_on_unknown_sensor_is_rejected(self):
        with self.assertRaises(ValueError):
            Scenario("bad").phase("rest", 1).ramp("co2", 0, 1, to=1)


class TestScoring(unittest.TestCase):
    EVENT = Event("co2", "ramp", start=100, end=200, critical_at=180)

    def test_alert_inside_window_detects_with_delay_and_lead(self):
        r = score("x", [self.EVENT], [Alert(130, "co2")])
        ev = r.events[0]
        self.assertTrue(ev.detected)
        self.assertEqual(ev.delay_s, 30)
        self.assertEqual(ev.lead_s, 50)
        self.assertEqual(r.false_alarms, [])

    def test_only_the_first_alert_counts(self):
        r = score("x", [self.EVENT], [Alert(170, "co2"), Alert(130, "co2")])
        self.assertEqual(r.events[0].delay_s, 30)

    def test_alert_before_the_event_is_a_false_alarm(self):
        r = score("x", [self.EVENT], [Alert(90, "co2")])
        self.assertFalse(r.events[0].detected)
        self.assertEqual(len(r.false_alarms), 1)

    def test_alert_on_other_sensor_does_not_count(self):
        r = score("x", [self.EVENT], [Alert(130, "o2")])
        self.assertFalse(r.events[0].detected)
        self.assertEqual(len(r.false_alarms), 1)

    def test_grace_period_after_event_end(self):
        self.assertTrue(score("x", [self.EVENT], [Alert(250, "co2")], grace_s=60).events[0].detected)
        self.assertFalse(score("x", [self.EVENT], [Alert(270, "co2")], grace_s=60).events[0].detected)

    def test_no_lead_time_when_limit_never_crossed(self):
        ev = Event("heart_rate", "stuck", start=100, end=200, critical_at=None)
        self.assertIsNone(score("x", [ev], [Alert(150, "heart_rate")]).events[0].lead_s)

    def test_repeated_alerts_group_into_one_false_alarm(self):
        alerts = [Alert(t, "heart_rate") for t in range(500, 560, 5)]       # every 5 s for a minute
        self.assertEqual(len(score("x", [], alerts, merge_s=60).false_alarms), 1)

    def test_separate_alerts_are_separate_false_alarms(self):
        alerts = [Alert(500, "heart_rate"), Alert(900, "heart_rate"), Alert(500, "co2")]
        self.assertEqual(len(score("x", [], alerts, merge_s=60).false_alarms), 3)

    def test_recall(self):
        evs = [self.EVENT, Event("o2", "ramp", 300, 400, None)]
        self.assertEqual(score("x", evs, [Alert(130, "co2")]).recall, 0.5)


class TestRunner(unittest.TestCase):

    def test_reset_receives_subject_and_limits(self):
        got = {}
        class Recorder:
            def reset(self, subject, limits): got.update(subject=subject, limits=limits)
            def observe(self, r): return []
        s = library.nominal_eva()
        run(Recorder(), s)
        self.assertEqual(got, {"subject": s.subject, "limits": s.limits})

    def test_readings_arrive_one_at_a_time_in_order(self):
        seen = []
        class Recorder:
            def reset(self, subject, limits): pass
            def observe(self, r):
                seen.append(r.t)
                return []
        run(Recorder(), library.nominal_eva())
        self.assertEqual(seen, sorted(seen))

    def test_alert_from_the_future_is_rejected(self):
        class Cheater:
            def reset(self, subject, limits): pass
            def observe(self, r): return [Alert(r.t + 10, r.sensor)]
        with self.assertRaises(CausalityError):
            run(Cheater(), library.nominal_eva())

    def test_detector_returning_none_is_allowed(self):
        class Quiet:
            def reset(self, subject, limits): pass
            def observe(self, r): return None
        self.assertEqual(run(Quiet(), library.nominal_eva()).alerts, [])

    def test_runner_is_deterministic(self):
        a = run(_OverLimit(), library.heart_rate_spike()).alerts
        b = run(_OverLimit(), library.heart_rate_spike()).alerts
        self.assertTrue(a, "expected the spike to trigger at least one alert")
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()