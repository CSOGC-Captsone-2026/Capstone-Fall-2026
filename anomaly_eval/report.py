"""
Readable scorecard for one or more detectors on the standard scenarios.

    python3 -m anomaly_eval.report                                     # rule-based baseline
    python3 -m anomaly_eval.report --detector models.kalman:KalmanDetector
    python3 -m anomaly_eval.report --detector rules --detector models.kalman:KalmanDetector   # side by side

Per event: how long after the anomaly started the first alert came (delay), and
how long before the safety limit was crossed it came (lead, i.e. early warning).
"""

from __future__ import annotations

import argparse
import statistics
from typing import List, Optional

from . import library
from .detectors import load_detector
from .scoring import Result, run


def _s(x: Optional[float]) -> str:
    return "-" if x is None else f"{x:.0f}s"


def _cell(er) -> str:
    if not er.detected:
        return "MISSED"
    lead = "" if er.lead_s is None else f", lead {_s(er.lead_s)}"
    return f"{er.first_alert.kind} +{_s(er.delay_s)}{lead}"


def evaluate(spec: str) -> List[Result]:
    return [run(load_detector(spec), make()) for make in library.ALL]


def summary(results: List[Result]) -> dict:
    events = [e for r in results for e in r.events]
    found = [e for e in events if e.detected]
    leads = [e.lead_s for e in found if e.lead_s is not None]
    hours = sum(make().duration_s for make in library.ALL) / 3600
    fa = sum(len(r.false_alarms) for r in results)
    return {
        "detected": f"{len(found)}/{len(events)}",
        "median delay": _s(statistics.median([e.delay_s for e in found])) if found else "-",
        "median lead (limit-crossing events)": _s(statistics.median(leads)) if leads else "-",
        "false alarms": f"{fa} ({fa / hours:.2f}/hour)",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Score detectors on the standard scenarios.")
    ap.add_argument("--detector", action="append",
                    help="'rules' or 'module:Class'; repeat to compare (default: $ANOMALY_DETECTOR or rules)")
    args = ap.parse_args()
    specs = args.detector or [None]
    names = [s or "default" for s in specs]
    all_results = [evaluate(s) for s in specs]

    w = 30
    print(f"{'Scenario':38}{'Event':24}" + "".join(f"{n[:w]:<{w}}" for n in names))
    print("-" * (62 + w * len(names)))
    for i, make in enumerate(library.ALL):
        first = all_results[0][i]
        rows = first.events or [None]
        for j, _ in enumerate(rows):
            scen = first.scenario if j == 0 else ""
            if first.events:
                ev = first.events[j].event
                label = f"{ev.sensor} {ev.kind}"
                cells = [_cell(res[i].events[j]) for res in all_results]
            else:
                label = "(no anomaly)"
                cells = ["quiet" if not res[i].false_alarms else f"{len(res[i].false_alarms)} false alarm(s)"
                         for res in all_results]
            print(f"{scen[:37]:38}{label:24}" + "".join(f"{c[:w - 1]:<{w}}" for c in cells))
        for k, res in enumerate(all_results):
            for g in res[i].false_alarms if first.events else []:
                a = g[0]
                print(f"{'':38}{'  false alarm':24}{'':{w * k}}{(a.sensor + ' ' + a.kind + ' t=' + _s(a.t))[:w - 1]}")

    print("-" * (62 + w * len(names)))
    sums = [summary(r) for r in all_results]
    for key in sums[0]:
        print(f"{key:62}" + "".join(f"{s[key]:<{w}}" for s in sums))


if __name__ == "__main__":
    main()