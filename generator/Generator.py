#!/usr/bin/env python3
"""
Synthetic suit-sensor data generator (Python standard library only).

Reads a sensor config (sensors.json) and writes fake analog-mission sessions
covering both the Environmental and Biometric suit sensor teams' sensors:

  readings.csv  - what the model sees: timestamp, session, subject, sensor, value, unit
  labels.csv    - the answer key: where each injected anomaly is, and when (if ever)
                  it crossed the sensor's critical limit
  activity.csv  - the mission timeline (rest / EVA phases) for each session

Usage:
  python generator.py                       # 6 sessions, 3 subjects, seed 42
  python generator.py --sessions 20 --subjects 5 --seed 7 --out data/run1
"""

import argparse
import csv
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ANOMALY_TYPES = ("ramp", "spike", "stuck", "dropout", "contextual")


# ---------------------------------------------------------------------------
# Session timeline
# ---------------------------------------------------------------------------

def build_timeline(phases):
    """Return (phase windows, per-second target activity level 0..1)."""
    windows, targets, t = [], [], 0
    for p in phases:
        length = int(p["minutes"] * 60)
        windows.append({"name": p["name"], "start": t, "end": t + length,
                        "activity": p["activity"]})
        targets += [p["activity"]] * length
        t += length
    return windows, targets


def smooth(targets, response_s):
    """
    First-order lag: each sensor follows the activity schedule at its own speed.
    response_s is the time to get ~63% of the way to a new level
    (heart rate ~45 s, core temperature ~15 min).
    """
    alpha = 1 - math.exp(-1 / response_s) if response_s > 0 else 1.0
    level, curve = targets[0], []
    for target in targets:
        level += alpha * (target - level)
        curve.append(level)
    return curve


def cumulative_minutes(curve):
    """Running total of activity, in 'full-exertion minutes', for accumulating sensors."""
    total, out = 0.0, []
    for a in curve:
        total += a / 60
        out.append(total)
    return out


# ---------------------------------------------------------------------------
# Anomaly planning
# ---------------------------------------------------------------------------

def plan_anomalies(rng, sensors, acfg, windows, total_s):
    """Pick non-overlapping anomalies (per sensor) for one session."""
    planned = []

    for _ in range(acfg["per_session"]):
        for _attempt in range(50):
            # Pick the type first so every type shows up about equally often.
            kind = rng.choice(ANOMALY_TYPES)
            candidates = [k for k, s in sensors.items() if kind in s.get("anomalies", [])] #which sensors support this type of anomly
            if not candidates:
                continue #if no sensors support this type of anomaly, skip
            sensor_id = rng.choice(candidates) # choose a random sensor from the candidates
            lo, hi = acfg["duration_min"][kind] #give's a random choice within the allowed duration for this type of anomaly
            dur = int(rng.uniform(lo, hi) * 60) #turn it to whole seconds

            if kind == "contextual":
                # sepcial placement - only in low exertion phases
                quiet = [w for w in windows
                         if w["activity"] <= 0.2 and (w["end"] - w["start"]) >= dur + 120] #only include low activity phases and make sure there is 2 mins after the anomaly ends
                if not quiet:
                    continue #cant place, no low activity phases
                w = rng.choice(quiet)
                start = rng.randint(w["start"] + 60, w["end"] - dur - 60) #randomly choose a start time within the low activity phase, make sure there is 1 min after the start and 1 min before the end
            else:
                start = rng.randint(300, total_s - dur - 120) #needs 5 mins before the start and 2 mins after the end, or else baseline data would be erratic
            end = start + dur

            clash = any(p["sensor_id"] == sensor_id and start < p["end"] + 60 and end > p["start"] - 60 #check if the anomaly overlaps with any other anomalies
                        for p in planned)
            if not clash:
                planned.append({"sensor_id": sensor_id, "type": kind, "start": start, "end": end})
                break
    return planned


# ---------------------------------------------------------------------------
# Signal generation
# ---------------------------------------------------------------------------

def critical_side(sensor):#check if the value is critical, works for both high and low thresholds
    """Return ('high'|'low', threshold) or (None, None)."""
    crit = sensor.get("critical") or {}
    if "high" in crit:
        return "high", crit["high"]
    if "low" in crit:
        return "low", crit["low"]
    return None, None


def is_critical(side, threshold, value): #side is binary, determines the direction of the criticality - then checks if the value is critical
    if side == "high":
        return value >= threshold
    if side == "low":
        return value <= threshold
    return False


def generate_sensor(rng, sensor, base, activity, cumulative, total_s, anomalies, overshoot):
    """Return ([(t_seconds, value), ...], {anomaly index: time it went critical})."""
    #assign attributes to the sensor
    rate = sensor["rate_hz"]
    step = 1.0 / rate #time between readings
    eff = sensor.get("activity_effect", 1.0)
    accumulate = sensor.get("accumulate_per_min", 0.0)
    noise = sensor.get("noise", 0.0)
    drift = sensor.get("drift_per_min", 0.0)
    lim_lo, lim_hi = sensor["limits"]
    side, threshold = critical_side(sensor)
    sign = -1 if side == "low" else 1

    if side == "high": #give targets depending on the side of criticality & threshold
        ramp_target = threshold * overshoot
    elif side == "low":
        ramp_target = threshold / overshoot
    else:
        ramp_target = base * 2

    #book keeping for anomalies
    crossings = {}  # anomaly index -> first time value went critical
    stuck_value = {}
    samples = [] #collects all readings, main output

    t = 0.0
    while t < total_s: #t handles any step size, better than for loop
        idx = min(int(t), len(activity) - 1) #track index for activity and cumulative list
        a = activity[idx]
        active = [(i, an) for i, an in enumerate(anomalies) if an["start"] <= t < an["end"]]

        if any(an["type"] == "dropout" for _, an in active):
            t += step
            continue

        if any(an["type"] == "contextual" for _, an in active):
            a = 1.0  # body behaves as if exerting while the timeline says rest

        value = (base * (1 + (eff - 1) * a)        # resting baseline, scaled by current exertion
                 + accumulate * cumulative[idx]      # build-up that doesn't recover (e.g. fluid loss)
                 + drift * (t / 60)                  # slow creep over the session
                 + rng.gauss(0, noise))              # sensor jitter

        for i, an in active:
            frac = (t - an["start"]) / (an["end"] - an["start"])
            if an["type"] == "ramp":
                value += frac * (ramp_target - base)
            elif an["type"] == "spike":
                value += sign * sensor.get("spike_delta", 0.0)
            elif an["type"] == "stuck":
                value = stuck_value.setdefault(i, value)

        value = min(max(value, lim_lo), lim_hi)

        for i, an in active:
            if an["type"] in ("ramp", "spike") and i not in crossings and is_critical(side, threshold, value):
                crossings[i] = t

        samples.append((t, round(value, 3)))
        t += step

    return samples, crossings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def iso(ts):
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def main():
    ap = argparse.ArgumentParser(description="Generate synthetic suit sensor sessions.")
    ap.add_argument("--config", default=str(Path(__file__).with_name("sensors.json")))
    ap.add_argument("--out", default="synthetic_output")
    ap.add_argument("--sessions", type=int, default=6)
    ap.add_argument("--subjects", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--start", default="2026-10-05T14:00:00", help="UTC start of the first session")
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)

    rng = random.Random(args.seed)
    # Sensors with "enabled": false (e.g. suit_pressure for unpressurized suits) are skipped.
    sensors = {k: s for k, s in cfg["sensors"].items() if s.get("enabled", True)}
    scfg = cfg["session"]
    overshoot = cfg["anomalies"].get("ramp_overshoot", 1.15)

    windows, targets = build_timeline(scfg["phases"])
    total_s = windows[-1]["end"]
    gap = timedelta(minutes=scfg.get("gap_between_sessions_min", 60))

    # Each sensor follows the activity schedule at its own response speed.
    curves, cumulatives = {}, {}
    for k, s in sensors.items():
        curves[k] = smooth(targets, s.get("response_s", 60))
        cumulatives[k] = cumulative_minutes(curves[k])

    # Each subject gets a personal resting baseline per sensor.
    subjects = {}
    for n in range(args.subjects):
        sid = f"A{n + 1}"
        subjects[sid] = {k: rng.uniform(*s["normal"]) for k, s in sensors.items()}

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    session_start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)

    n_readings = 0
    with open(out / "readings.csv", "w", newline="") as rf, \
         open(out / "labels.csv", "w", newline="") as lf, \
         open(out / "activity.csv", "w", newline="") as af:
        rw, lw, aw = csv.writer(rf), csv.writer(lf), csv.writer(af)
        rw.writerow(["timestamp", "session_id", "subject_id", "sensor_id", "value", "unit"])
        lw.writerow(["session_id", "subject_id", "sensor_id", "type", "start", "end", "critical_at"])
        aw.writerow(["session_id", "subject_id", "phase", "activity", "start", "end"])

        for s in range(args.sessions):
            session_id = f"S{s + 1:03d}"
            subject_id = list(subjects)[s % len(subjects)]
            t0 = session_start

            for w in windows:
                aw.writerow([session_id, subject_id, w["name"], w["activity"],
                             iso(t0 + timedelta(seconds=w["start"])),
                             iso(t0 + timedelta(seconds=w["end"]))])

            planned = plan_anomalies(rng, sensors, cfg["anomalies"], windows, total_s)
            rows = []
            for order, (sensor_id, sensor) in enumerate(sensors.items()):
                mine = [a for a in planned if a["sensor_id"] == sensor_id]
                samples, crossings = generate_sensor(
                    rng, sensor, subjects[subject_id][sensor_id],
                    curves[sensor_id], cumulatives[sensor_id],
                    total_s, mine, overshoot)
                for t, v in samples:
                    rows.append((t, order, sensor_id, v, sensor["unit"]))
                for i, an in enumerate(mine):
                    crit = crossings.get(i)
                    lw.writerow([session_id, subject_id, sensor_id, an["type"],
                                 iso(t0 + timedelta(seconds=an["start"])),
                                 iso(t0 + timedelta(seconds=an["end"])),
                                 iso(t0 + timedelta(seconds=crit)) if crit is not None else ""])

            rows.sort()
            for t, _order, sensor_id, v, unit in rows:
                rw.writerow([iso(t0 + timedelta(seconds=t)), session_id, subject_id, sensor_id, v, unit])
            n_readings += len(rows)
            session_start = t0 + timedelta(seconds=total_s) + gap

    print(f"Wrote {args.sessions} sessions ({n_readings:,} readings) for "
          f"{args.subjects} subjects to {out}/")


if __name__ == "__main__":
    main()