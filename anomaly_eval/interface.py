"""
The contract every anomaly detector must follow.

A detector is fed readings one at a time, in time order, exactly as they would
arrive live. It never sees future readings or the answer key. Any model you
build later (Kalman filter, gradient boosting, LSTM...) only has to implement
these two methods to be tested by this framework.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol


@dataclass(frozen=True)
class Reading:
    t: float                 # seconds since the session started
    subject: str             # e.g. "A1"
    sensor: str              # e.g. "co2"
    value: float
    phase: str               # scheduled phase, e.g. "rest", "eva_task" (known to mission control)
    activity: float          # scheduled activity level 0..1 (known to mission control)


@dataclass(frozen=True)
class Alert:
    t: float                 # when the detector raised it (must be <= the reading that caused it)
    sensor: str              # which sensor it is about
    kind: str = "anomaly"    # free text, e.g. "threshold", "trend", "stuck", "dropout"
    message: str = ""        # human-readable explanation, shown in reports


class Detector(Protocol):
    def reset(self, subject: str, limits: dict) -> None:
        """Start a new session. `limits` = {sensor: ("high"|"low", threshold)} safety limits."""

    def observe(self, reading: Reading) -> List[Alert]:
        """Called once per reading, in time order. Return any new alerts (often [])."""