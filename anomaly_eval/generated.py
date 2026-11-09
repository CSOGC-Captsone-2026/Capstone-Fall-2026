"""
Run detectors on the data generator's output instead of the hand-written scenarios.

The generator writes three CSVs (readings, labels, activity). This module turns each
generated session into an object that works exactly like a Scenario, so the same
run()/score() code, the same detectors and the same metrics apply. It only depends on
the CSV format, so it also reads the output of run_via_decoder.py.

Library use:
    sessions = load_sessions("data/test", config="generator/sensors.json")
    results  = [run(RuleBasedDetector(), s) for s in sessions]

Command line (generates fresh data, or reads an existing folder):
    python3 -m anomaly_eval.generated --sessions 20 --seed 5
    python3 -m anomaly_eval.generated --data data/via_decoder
    python3 -m anomaly_eval.generated --sessions 20 --seed 5 --detector rules --detector models.kalman:KalmanDetector
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import statistics
import subprocess
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .interface import Reading
from .scenarios import Event

REPO = Path(__file__).resolve().parent.parent
GENERATOR_DIR = REPO / "generator"


# ---------------------------------------------------------------------------
# Finding the generator and its config (tolerates Generator.py / sensors.JSON)
# ---------------------------------------------------------------------------

def _find(folder: Path, name: str) -> Path:
    for p in folder.iterdir():
        if p.name.lower() == name.lower():
            return p
    raise FileNotFoundError(f"{name} not found in {folder}")


def load_limits(config: Path | str) -> Dict[str, Tuple[str, float]]:
    """Safety limits of the enabled sensors, from sensors.json."""
    with open(config) as f:
        sensors = json.load(f)["sensors"]
    limits = {}
    for name, s in sensors.items():
        crit = s.get("critical") or {}
        if not s.get("enabled", True):
            continue
        if "high" in crit:
            limits[name] = ("high", crit["high"])
        elif "low" in crit:
            limits[name] = ("low", crit["low"])
    return limits


def generate(out_dir: Path | str, sessions: int, seed: int, subjects: int = 3,
             generator: Path | None = None, config: Path | None = None) -> Path:
    """Run generator.py with a fixed seed. Same arguments -> identical files."""
    generator = generator or _find(GENERATOR_DIR, "generator.py")
    config = config or _find(GENERATOR_DIR, "sensors.json")
    cmd = [sys.executable, str(generator), "--out", str(out_dir), "--config", str(config),
           "--sessions", str(sessions), "--subjects", str(subjects), "--seed", str(seed)]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
    return Path(out_dir)


# ---------------------------------------------------------------------------
# One generated session, shaped like a Scenario
# ---------------------------------------------------------------------------

def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@dataclass
class GeneratedSession:
    """Duck-types Scenario: has name, subject, limits, duration_s and build()."""
    name: str
    subject: str
    limits: Dict[str, Tuple[str, float]]
    duration_s: float
    _readings: List[Reading] = field(repr=False)
    _events: List[Event] = field(repr=False)

    def build(self) -> Tuple[List[Reading], List[Event]]:
        return list(self._readings), list(self._events)


def load_sessions(data_dir: Path | str, config: Path | str | None = None) -> List[GeneratedSession]:
    """Read readings.csv, labels.csv and activity.csv from a generator output folder."""
    data_dir = Path(data_dir)
    limits = load_limits(config or _find(GENERATOR_DIR, "sensors.json"))

    # phases: session -> sorted [(start_s, end_s, phase, activity)], times relative to session start
    raw_phases = defaultdict(list)
    subject = {}
    with open(data_dir / "activity.csv", newline="") as f:
        for r in csv.DictReader(f):
            raw_phases[r["session_id"]].append((_ts(r["start"]), _ts(r["end"]), r["phase"], float(r["activity"])))
            subject[r["session_id"]] = r["subject_id"]
    t0, phases = {}, {}
    for sid, ps in raw_phases.items():
        ps.sort()
        t0[sid] = ps[0][0]
        phases[sid] = [((a - t0[sid]).total_seconds(), (b - t0[sid]).total_seconds(), name, act)
                       for a, b, name, act in ps]
    starts = {sid: [p[0] for p in ps] for sid, ps in phases.items()}

    readings = defaultdict(list)
    with open(data_dir / "readings.csv", newline="") as f:
        for r in csv.DictReader(f):
            sid = r["session_id"]
            t = (_ts(r["timestamp"]) - t0[sid]).total_seconds()
            ps = phases[sid]
            i = max(0, bisect.bisect_right(starts[sid], t) - 1)
            _, _, phase, activity = ps[i]
            readings[sid].append(Reading(t, r["subject_id"], r["sensor_id"], float(r["value"]), phase, activity))

    events = defaultdict(list)
    with open(data_dir / "labels.csv", newline="") as f:
        for r in csv.DictReader(f):
            sid = r["session_id"]
            rel = lambda s: (_ts(s) - t0[sid]).total_seconds()
            events[sid].append(Event(r["sensor_id"], r["type"], rel(r["start"]), rel(r["end"]),
                                     rel(r["critical_at"]) if r["critical_at"] else None))

    sessions = []
    for sid in sorted(phases):
        rs = sorted(readings[sid], key=lambda x: (x.t, x.sensor))
        sessions.append(GeneratedSession(f"{sid} ({subject[sid]})", subject[sid], limits,
                                         phases[sid][-1][1], rs, events[sid]))
    return sessions


# ---------------------------------------------------------------------------
# Aggregate statistics
# ---------------------------------------------------------------------------

def _pct(values: List[float], q: float) -> Optional[float]:
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def aggregate(results, hours: float) -> dict:
    """Per anomaly type: detected, median/90th-percentile delay, median lead; plus false alarms/hour."""
    by_kind = defaultdict(list)
    for res in results:
        for er in res.events:
            by_kind[er.event.kind].append(er)
    rows = {}
    for kind, ers in sorted(by_kind.items()):
        found = [e for e in ers if e.detected]
        delays = [e.delay_s for e in found]
        leads = [e.lead_s for e in found if e.lead_s is not None]
        rows[kind] = {
            "detected": f"{len(found)}/{len(ers)}",
            "median delay": _pct(delays, 0.5),
            "p90 delay": _pct(delays, 0.9),
            "median lead": _pct(leads, 0.5),
        }
    fa = sum(len(r.false_alarms) for r in results)
    return {"by_kind": rows, "false_alarms": fa, "per_hour": fa / hours if hours else 0.0}


def _s(x: Optional[float]) -> str:
    return "-" if x is None else f"{x:.0f}s"


def main() -> None:
    from .detectors import load_detector
    from .scoring import run

    ap = argparse.ArgumentParser(description="Score detectors on data-generator sessions.")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--data", help="existing generator output folder (readings/labels/activity.csv)")
    src.add_argument("--sessions", type=int, default=20, help="generate this many sessions (default 20)")
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--subjects", type=int, default=3)
    ap.add_argument("--config", default=None, help="sensors.json (default: the generator's)")
    ap.add_argument("--detector", action="append", help="'rules' or 'module:Class'; repeat to compare")
    ap.add_argument("--show-false-alarms", type=int, default=5, help="list up to N false alarms per detector")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        if args.data:
            data = Path(args.data)
            source = f"{data}"
        else:
            data = generate(Path(tmp) / "gen", args.sessions, args.seed, args.subjects,
                            config=Path(args.config) if args.config else None)
            source = f"generator, {args.sessions} sessions, seed {args.seed}"
        sessions = load_sessions(data, args.config)

    hours = sum(s.duration_s for s in sessions) / 3600
    specs = args.detector or [None]
    print(f"Data: {source} ({len(sessions)} sessions, {hours:.1f} h)\n")

    for spec in specs:
        results = [run(load_detector(spec), s) for s in sessions]
        agg = aggregate(results, hours)
        print(f"Detector: {spec or 'default'}")
        print(f"  {'anomaly':12}{'detected':>10}{'median delay':>15}{'p90 delay':>12}{'median lead':>14}")
        for kind, row in agg["by_kind"].items():
            print(f"  {kind:12}{row['detected']:>10}{_s(row['median delay']):>15}"
                  f"{_s(row['p90 delay']):>12}{_s(row['median lead']):>14}")
        print(f"  false alarms: {agg['false_alarms']} ({agg['per_hour']:.2f}/hour)")
        shown = 0
        for res in results:
            for g in res.false_alarms:
                if shown < args.show_false_alarms:
                    a = g[0]
                    print(f"    {res.scenario}: {a.sensor} at t={a.t:.0f}s ({a.kind}) {a.message}")
                    shown += 1
        print()


if __name__ == "__main__":
    main()