"""
Detectors that ship with the framework, plus a loader for your own.

RuleBasedDetector is the non-ML, non-predictive baseline. It only reacts to the
readings it has already seen; it never forecasts. Four rules, each per sensor:

  1. threshold   reading is past its safety limit
  2. stuck       the last `stuck_s` seconds of readings are all identical
  3. dropout     no reading for `dropout_factor` x the sensor's usual interval
  4. rest band   during rest, reading is well above this subject's own rest level
                 (catches "exertion-level heart rate while resting")

Point the tests at any detector without editing the framework:
    ANOMALY_DETECTOR=rules                           (built-in baseline)
    ANOMALY_DETECTOR=models.kalman:KalmanDetector    (module path : class name)
"""

from __future__ import annotations

import importlib
import os
import statistics
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

from .interface import Alert, Reading


class RuleBasedDetector:
    
    predictive = False 

    def __init__(self, stuck_s: float = 60.0, stuck_min_readings: int = 5,
                 dropout_factor: float = 5.0, dropout_min_s: float = 10.0,
                 learn_s: float = 120.0, band_sigmas: float = 5.0, band_min_frac: float = 0.10,
                 rest_activity: float = 0.05, recovered_s: float = 20.0, confirm_readings: int = 3):
        self.stuck_s = stuck_s
        self.stuck_min_readings = stuck_min_readings
        self.dropout_factor = dropout_factor
        self.dropout_min_s = dropout_min_s
        self.learn_s = learn_s                    # seconds of the first rest used to learn the rest level
        self.band_sigmas = band_sigmas            # rest band = mean + max(band_sigmas*std, band_min_frac*mean)
        self.band_min_frac = band_min_frac
        self.rest_activity = rest_activity        # scheduled activity at or below this counts as rest
        self.recovered_s = recovered_s            # must be back inside the band this long before the check arms
        self.confirm_readings = confirm_readings  # consecutive readings above the band before alerting

    # -- Detector contract ------------------------------------------------

    def reset(self, subject: str, limits: dict) -> None:
        self.limits = limits
        self.active: Dict[Tuple[str, str], bool] = {}          # (sensor, rule) -> currently alerting
        self.recent: Dict[str, Deque[Tuple[float, float]]] = {}  # sensor -> recent (t, value)
        self.last_t: Dict[str, float] = {}
        self.interval: Dict[str, float] = {}
        self.rest_samples: Dict[str, List[float]] = {}
        self.band: Dict[str, float] = {}
        self.inside_since: Dict[str, Optional[float]] = {}
        self.above_count: Dict[str, int] = {}

    def observe(self, r: Reading) -> List[Alert]:
        alerts: List[Alert] = []
        alerts += self._check_dropouts(r.t)               # other sensors gone quiet?
        self._track_timing(r)
        alerts += self._threshold(r)
        alerts += self._stuck(r)
        alerts += self._rest_band(r)
        return alerts

    # -- rules ------------------------------------------------------------

    def _raise(self, key: Tuple[str, str], condition: bool, alert: Alert) -> List[Alert]:
        """Alert once when a condition becomes true; re-arm when it clears."""
        was = self.active.get(key, False)
        self.active[key] = condition
        return [alert] if condition and not was else []

    def _threshold(self, r: Reading) -> List[Alert]:
        limit = self.limits.get(r.sensor)
        if not limit:
            return []
        side, thr = limit
        over = r.value >= thr if side == "high" else r.value <= thr
        return self._raise((r.sensor, "threshold"), over,
                           Alert(r.t, r.sensor, "threshold", f"{r.sensor}={r.value} past {side} limit {thr}"))

    def _stuck(self, r: Reading) -> List[Alert]:
        window = self.recent.setdefault(r.sensor, deque())
        window.append((r.t, r.value))
        while window and r.t - window[0][0] > self.stuck_s:
            window.popleft()
        spans = window[-1][0] - window[0][0] >= self.stuck_s * 0.9
        identical = len({v for _, v in window}) == 1
        stuck = spans and len(window) >= self.stuck_min_readings and identical
        return self._raise((r.sensor, "stuck"), stuck,
                           Alert(r.t, r.sensor, "stuck",
                                 f"{r.sensor} has read exactly {r.value} for {self.stuck_s:.0f} s"))

    def _track_timing(self, r: Reading) -> None:
        prev = self.last_t.get(r.sensor)
        if prev is not None and r.sensor not in self.interval and r.t > prev:
            self.interval[r.sensor] = r.t - prev            # learn the usual interval from the first gap
        self.last_t[r.sensor] = r.t
        self.active[(r.sensor, "dropout")] = False          # a reading arrived: sensor is back

    def _check_dropouts(self, now: float) -> List[Alert]:
        alerts = []
        for sensor, last in self.last_t.items():
            interval = self.interval.get(sensor)
            if interval is None:
                continue
            allowed = max(self.dropout_factor * interval, self.dropout_min_s)
            silent = now - last > allowed
            alerts += self._raise((sensor, "dropout"), silent,
                                  Alert(now, sensor, "dropout",
                                        f"no {sensor} reading for {now - last:.0f} s (expected every {interval:g} s)"))
        return alerts

    def _rest_band(self, r: Reading) -> List[Alert]:
        resting = r.activity <= self.rest_activity
        # 1. learn this subject's rest level from the start of the session
        if r.sensor not in self.band:
            if resting and r.t <= self.learn_s:
                self.rest_samples.setdefault(r.sensor, []).append(r.value)
            elif len(self.rest_samples.get(r.sensor, [])) >= 3:
                vals = self.rest_samples[r.sensor]
                mean, std = statistics.fmean(vals), statistics.pstdev(vals)
                self.band[r.sensor] = mean + max(self.band_sigmas * std, self.band_min_frac * abs(mean))
            return []
        band = self.band[r.sensor]

        # 2. only check during rest, and only once the sensor has recovered into the band
        if not resting:
            self.inside_since[r.sensor] = None
            self.above_count[r.sensor] = 0
            return self._raise((r.sensor, "rest_band"), False, Alert(r.t, r.sensor))
        if r.value <= band:
            if self.inside_since.get(r.sensor) is None:
                self.inside_since[r.sensor] = r.t
            self.above_count[r.sensor] = 0
            return self._raise((r.sensor, "rest_band"), False, Alert(r.t, r.sensor))
        armed_at = self.inside_since.get(r.sensor)
        if armed_at is None or r.t - armed_at < self.recovered_s:
            self.inside_since[r.sensor] = None             # still recovering from the EVA
            return []
        self.above_count[r.sensor] = self.above_count.get(r.sensor, 0) + 1
        high = self.above_count[r.sensor] >= self.confirm_readings
        return self._raise((r.sensor, "rest_band"), high,
                           Alert(r.t, r.sensor, "rest_band",
                                 f"{r.sensor}={r.value} during rest; this subject's rest band tops out at {band:.1f}"))


BUILT_IN = {"rules": RuleBasedDetector}


def load_detector(spec: str | None = None):
    """Return a NEW detector instance from 'rules' or 'package.module:ClassName'."""
    spec = spec or os.environ.get("ANOMALY_DETECTOR", "rules")
    if spec in BUILT_IN:
        return BUILT_IN[spec]()
    module_name, _, class_name = spec.partition(":")
    if not class_name:
        raise ValueError(f"unknown detector {spec!r}; use one of {list(BUILT_IN)} or 'module:Class'")
    return getattr(importlib.import_module(module_name), class_name)()