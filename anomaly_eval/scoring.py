"""
Run a detector on a scenario and score its alerts against the ground truth.

Scoring is event-based, which is how operators experience alerts:
  - an event counts as DETECTED if any alert on its sensor falls in
    [start, end + grace_s]
  - delay   = first matching alert - event start          (smaller is better)
  - lead    = critical_at - first matching alert          (larger is better; only for
              events that actually crossed a safety limit)
  - alerts that match no event are grouped (same sensor, within merge_s of each other);
    each group is ONE false alarm, so a detector that fires every second for a minute
    is charged one false alarm, not sixty
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .interface import Alert, Detector
from .scenarios import Event, Scenario


@dataclass
class EventResult:
    event: Event
    first_alert: Optional[Alert]

    @property
    def detected(self) -> bool:
        return self.first_alert is not None

    @property
    def delay_s(self) -> Optional[float]:
        return None if self.first_alert is None else self.first_alert.t - self.event.start

    @property
    def lead_s(self) -> Optional[float]:
        if self.first_alert is None or self.event.critical_at is None:
            return None
        return self.event.critical_at - self.first_alert.t


@dataclass
class Result:
    scenario: str
    events: List[EventResult]
    false_alarms: List[List[Alert]]          # each inner list = one grouped false alarm
    alerts: List[Alert] = field(repr=False, default_factory=list)

    def event(self, sensor: str, kind: str) -> EventResult:
        for r in self.events:
            if r.event.sensor == sensor and r.event.kind == kind:
                return r
        raise KeyError(f"{self.scenario}: no {kind} event on {sensor}")

    @property
    def recall(self) -> float:
        return sum(r.detected for r in self.events) / len(self.events) if self.events else 1.0


class CausalityError(AssertionError):
    """The detector returned an alert time later than the reading it was given."""


def run(detector: Detector, scenario: Scenario, grace_s: float = 60.0, merge_s: float = 60.0) -> Result:
    readings, events = scenario.build()
    detector.reset(scenario.subject, scenario.limits)

    alerts: List[Alert] = []
    for reading in readings:
        for alert in detector.observe(reading) or []:
            if alert.t > reading.t:
                raise CausalityError(f"alert at t={alert.t} returned while observing t={reading.t}")
            alerts.append(alert)

    return score(scenario.name, events, alerts, grace_s, merge_s)


def score(name: str, events: List[Event], alerts: List[Alert],
          grace_s: float = 60.0, merge_s: float = 60.0) -> Result:
    alerts = sorted(alerts, key=lambda a: (a.t, a.sensor))
    matched = set()
    results = []
    for ev in events:
        hits = [i for i, a in enumerate(alerts)
                if a.sensor == ev.sensor and ev.start <= a.t <= ev.end + grace_s]
        matched.update(hits)
        results.append(EventResult(ev, alerts[hits[0]] if hits else None))

    groups: List[List[Alert]] = []
    last_by_sensor = {}
    for i, a in enumerate(alerts):
        if i in matched:
            continue
        g = last_by_sensor.get(a.sensor)
        if g is not None and a.t - g[-1].t <= merge_s:
            g.append(a)
        else:
            g = [a]
            groups.append(g)
            last_by_sensor[a.sensor] = g
    return Result(name, results, groups, alerts)