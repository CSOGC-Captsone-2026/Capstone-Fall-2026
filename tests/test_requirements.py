"""
What we require of ANY anomaly detector, written as plain-language checks.

Runs against the detector named by $ANOMALY_DETECTOR (default: the rule-based baseline):
    python3 -m unittest tests.test_requirements -v
    ANOMALY_DETECTOR=models.kalman:KalmanDetector python3 -m unittest tests.test_requirements -v

Lead-time (early warning) requirements only apply to predictive detectors. A detector
opts out by setting `predictive = False` on its class, as the rule-based baseline does;
anything else is held to them.

The numbers below are placeholders to agree with COSGC: they are the project's success criteria.
"""

import unittest
from dataclasses import dataclass
from typing import Callable, Optional

from anomaly_eval import library, load_detector, run


@dataclass
class Requirement:
    scenario: Callable
    sensor: str
    kind: str
    max_delay_s: Optional[float] = None    # must alert within this long after the anomaly starts
    min_lead_s: Optional[float] = None     # must alert at least this long before the safety limit


REQUIREMENTS = [
    Requirement(library.co2_scrubber_failure, "co2", "ramp", min_lead_s=60),
    Requirement(library.o2_leak, "o2", "ramp", min_lead_s=30),
    Requirement(library.heart_rate_spike, "heart_rate", "spike", max_delay_s=15),
    Requirement(library.co2_sensor_stuck, "co2", "stuck", max_delay_s=120),
    Requirement(library.heart_rate_dropout, "heart_rate", "dropout", max_delay_s=30),
    Requirement(library.heart_rate_high_at_rest, "heart_rate", "contextual", max_delay_s=60),
]

MAX_FALSE_ALARMS_PER_SCENARIO = 0


def _predictive(detector) -> bool:
    return getattr(detector, "predictive", True)


class TestDetectorRequirements(unittest.TestCase):

    def test_detects_every_anomaly(self):
        for req in REQUIREMENTS:
            scenario = req.scenario()
            with self.subTest(scenario=scenario.name):
                ev = run(load_detector(), scenario).event(req.sensor, req.kind)
                self.assertTrue(ev.detected,
                    f"no alert on {req.sensor} during the {req.kind} "
                    f"(t={ev.event.start:.0f}-{ev.event.end:.0f} s)")

    def test_detects_quickly_enough(self):
        for req in [r for r in REQUIREMENTS if r.max_delay_s is not None]:
            scenario = req.scenario()
            with self.subTest(scenario=scenario.name):
                ev = run(load_detector(), scenario).event(req.sensor, req.kind)
                if not ev.detected:
                    self.fail(f"not detected (see test_detects_every_anomaly)")
                self.assertLessEqual(ev.delay_s, req.max_delay_s,
                    f"first alert came {ev.delay_s:.0f} s after the {req.kind} started; "
                    f"required within {req.max_delay_s:.0f} s")

    def test_warns_before_the_limit_is_crossed(self):
        detector = load_detector()
        if not _predictive(detector):
            self.skipTest(f"{type(detector).__name__} is non-predictive; lead-time requirements "
                          f"apply to predictive detectors")
        for req in [r for r in REQUIREMENTS if r.min_lead_s is not None]:
            scenario = req.scenario()
            with self.subTest(scenario=scenario.name):
                ev = run(load_detector(), scenario).event(req.sensor, req.kind)
                self.assertIsNotNone(ev.event.critical_at, "scenario never crossed its limit; fix the scenario")
                if not ev.detected:
                    self.fail("not detected (see test_detects_every_anomaly)")
                self.assertGreaterEqual(ev.lead_s, req.min_lead_s,
                    f"warned {ev.lead_s:.0f} s before the limit was crossed "
                    f"(t={ev.event.critical_at:.0f} s); required at least {req.min_lead_s:.0f} s")

    def test_no_false_alarms(self):
        for make in library.ALL:
            scenario = make()
            with self.subTest(scenario=scenario.name):
                result = run(load_detector(), scenario)
                described = [f"{g[0].sensor} at t={g[0].t:.0f} s ({g[0].kind}: {g[0].message})"
                             for g in result.false_alarms]
                self.assertLessEqual(len(result.false_alarms), MAX_FALSE_ALARMS_PER_SCENARIO,
                    "unexpected alerts: " + "; ".join(described))


if __name__ == "__main__":
    unittest.main()