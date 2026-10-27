"""
Hand-written, deterministic test scenarios.

Each scenario reads like a test plan:

    Scenario("CO2 scrubber fails mid-EVA")
        .phase("rest", 10).phase("eva_task", 30).phase("rest", 10)
        .sensor("co2", base=800, effect=1.6, noise=15, critical_high=5000)
        .ramp("co2", at_min=22, minutes=8, to=5750)

and produces the same readings every run: noise comes from a random generator
seeded from the scenario's name, never from the clock or Python's hash().
"""

from __future__ import annotations

import math
import random
import zlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .interface import Reading


@dataclass(frozen=True)
class Event:
    """Ground truth: one injected anomaly."""
    sensor: str
    kind: str                      # ramp | spike | stuck | dropout | contextual
    start: float                   # seconds
    end: float
    critical_at: Optional[float]   # first reading at/over the safety limit, if any


@dataclass
class _Sensor:
    base: float
    effect: float = 1.0            # value at full effort = base * effect
    noise: float = 0.0             # standard deviation
    rate_hz: float = 1.0
    response_s: float = 60.0       # how quickly it follows activity changes
    limit: Optional[Tuple[str, float]] = None   # ("high"|"low", threshold)


@dataclass
class Scenario:
    name: str
    subject: str = "A1"
    seed: Optional[int] = None
    phases: List[Tuple[str, float, float]] = field(default_factory=list)    # (name, minutes, activity)
    sensors: Dict[str, _Sensor] = field(default_factory=dict)
    _anomalies: List[dict] = field(default_factory=list)

    # -- building ---------------------------------------------------------

    def phase(self, name: str, minutes: float, activity: Optional[float] = None) -> "Scenario":
        if activity is None:
            activity = 1.0 if name.startswith("eva") else 0.0
        self.phases.append((name, minutes, activity))
        return self

    def sensor(self, name: str, base: float, *, effect: float = 1.0, noise: float = 0.0,
               rate_hz: float = 1.0, response_s: float = 60.0,
               critical_high: Optional[float] = None, critical_low: Optional[float] = None) -> "Scenario":
        limit = ("high", critical_high) if critical_high is not None else \
                ("low", critical_low) if critical_low is not None else None
        self.sensors[name] = _Sensor(base, effect, noise, rate_hz, response_s, limit)
        return self

    def ramp(self, sensor: str, at_min: float, minutes: float, to: float) -> "Scenario":
        """Value moves steadily from normal to `to` over the window."""
        return self._add(sensor, "ramp", at_min, minutes, to=to)

    def spike(self, sensor: str, at_min: float, minutes: float, delta: float) -> "Scenario":
        """Value jumps by `delta` (negative for downward) for the window."""
        return self._add(sensor, "spike", at_min, minutes, delta=delta)

    def stuck(self, sensor: str, at_min: float, minutes: float) -> "Scenario":
        """Sensor repeats its last value with no noise."""
        return self._add(sensor, "stuck", at_min, minutes)

    def dropout(self, sensor: str, at_min: float, minutes: float) -> "Scenario":
        """Sensor sends nothing."""
        return self._add(sensor, "dropout", at_min, minutes)

    def contextual(self, sensor: str, at_min: float, minutes: float) -> "Scenario":
        """Sensor reads at full-effort level while the schedule says rest."""
        return self._add(sensor, "contextual", at_min, minutes)

    def _add(self, sensor, kind, at_min, minutes, **params) -> "Scenario":
        if sensor not in self.sensors:
            raise ValueError(f"{self.name}: add sensor {sensor!r} before its anomalies")
        self._anomalies.append(dict(sensor=sensor, kind=kind, start=at_min * 60,
                                    end=(at_min + minutes) * 60, **params))
        return self

    # -- generating -------------------------------------------------------

    @property
    def duration_s(self) -> float:
        return sum(m for _, m, _ in self.phases) * 60

    @property
    def limits(self) -> Dict[str, Tuple[str, float]]:
        """Safety limits: operational knowledge a detector is allowed to have."""
        return {k: s.limit for k, s in self.sensors.items() if s.limit}

    def _schedule(self) -> List[Tuple[str, float]]:
        """(phase, activity) for each second of the session."""
        out = []
        for name, minutes, activity in self.phases:
            out += [(name, activity)] * int(round(minutes * 60))
        return out

    def build(self) -> Tuple[List[Reading], List[Event]]:
        """Readings sorted by time, plus the ground-truth events."""
        seed = self.seed if self.seed is not None else zlib.crc32(self.name.encode())
        rng = random.Random(seed)
        schedule = self._schedule()
        readings: List[Reading] = []
        crossings: Dict[int, float] = {}

        for sensor_name in sorted(self.sensors):                 # sorted: fixed order of random draws
            s = self.sensors[sensor_name]
            effort_curve = _lag([a for _, a in schedule], s.response_s)
            mine = [(i, a) for i, a in enumerate(self._anomalies) if a["sensor"] == sensor_name]
            stuck_at: Dict[int, float] = {}
            step = 1.0 / s.rate_hz
            n = 0
            while n * step < self.duration_s:
                t = n * step
                n += 1
                sec = min(int(t), len(schedule) - 1)
                phase, scheduled = schedule[sec]

                active = [(i, a) for i, a in mine if a["start"] <= t < a["end"]]
                if any(a["kind"] == "dropout" for _, a in active):
                    continue
                effort = 1.0 if any(a["kind"] == "contextual" for _, a in active) else effort_curve[sec]

                normal = s.base * (1 + (s.effect - 1) * effort)
                value = normal + rng.gauss(0, s.noise)
                for i, a in active:
                    frac = (t - a["start"]) / (a["end"] - a["start"])
                    if a["kind"] == "ramp":
                        value = (1 - frac) * value + frac * a["to"]
                    elif a["kind"] == "spike":
                        value += a["delta"]
                    elif a["kind"] == "stuck":
                        value = stuck_at.setdefault(i, value)

                for i, a in active:
                    if i not in crossings and s.limit and _over(s.limit, value):
                        crossings[i] = t
                readings.append(Reading(t, self.subject, sensor_name, round(value, 4), phase, scheduled))

        readings.sort(key=lambda r: (r.t, r.sensor))
        events = [Event(a["sensor"], a["kind"], a["start"], a["end"], crossings.get(i))
                  for i, a in enumerate(self._anomalies)]
        return readings, events


def _lag(targets: List[float], response_s: float) -> List[float]:
    """First-order lag: the sensor follows the activity schedule with time constant response_s."""
    alpha = 1 - math.exp(-1 / response_s) if response_s > 0 else 1.0
    level, curve = targets[0], []
    for target in targets:
        level += alpha * (target - level)
        curve.append(level)
    return curve


def _over(limit: Tuple[str, float], value: float) -> bool:
    side, threshold = limit
    return value >= threshold if side == "high" else value <= threshold