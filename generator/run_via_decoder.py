#!/usr/bin/env python3
"""
Run the synthetic data generator, then send its readings through the serial
packet format: encode into binary frames with decoder.py's encode_frame(),
optionally damage the link (drops, corruption, duplicates), and decode the byte
stream with StreamDecoder, the same path real hardware data will take.

generator.py and decoder.py are used as-is; this script only connects them.

Output (in --out):
  raw/                 the generator's original output, for comparison
  readings.csv         readings after the encode -> link -> decode round trip
  labels.csv           anomaly labels (copied from the generator)
  activity.csv         phase schedule (copied from the generator)
  capture.bin          the raw bytes on the "wire"; replay with decoder.py --file
  link_events.csv      every frame the simulated link dropped, corrupted or duplicated
  link_stats.json      decoder statistics and round-trip summary

Usage (from the repo root):
  python3 generator/run_via_decoder.py --out data/via_decoder
  python3 generator/run_via_decoder.py --out data/lossy --drop 0.05 --corrupt 0.02
  python3 generator/run_via_decoder.py --out data/run1 --sessions 20 --seed 7
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import random
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_GENERATOR = HERE / "generator.py"
DEFAULT_DECODER = REPO / "src" / "twin" / "serial-decoder" / "decoder.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_module(name: str, path: Path):
    """Import a .py file by path (no sys.path changes, no name clashes)."""
    if not path.exists():
        raise SystemExit(f"{path.name} not found at {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module          # register before running so dataclasses work
    spec.loader.exec_module(module)
    return module


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def find_config(generator_dir: Path) -> Path | None:
    """Find sensors.json regardless of capitalization (e.g. sensors.JSON)."""
    for p in generator_dir.iterdir():
        if p.name.lower() == "sensors.json":
            return p
    return None


# ---------------------------------------------------------------------------
# Step 1: run the generator
# ---------------------------------------------------------------------------

def run_generator(args, raw_dir: Path) -> None:
    config = Path(args.config) if args.config else find_config(Path(args.generator).parent)
    cmd = [sys.executable, str(args.generator), "--out", str(raw_dir),
           "--sessions", str(args.sessions), "--subjects", str(args.subjects),
           "--seed", str(args.seed)]
    if config:
        cmd += ["--config", str(config)]
    print("Running generator:", " ".join(cmd[1:]))
    subprocess.run(cmd, check=True)


def load_sessions(raw_dir: Path):
    """Group generator readings by session, with times relative to session start."""
    starts = {}
    for r in csv.DictReader(open(raw_dir / "activity.csv", newline="")):
        t = parse_ts(r["start"])
        if r["session_id"] not in starts or t < starts[r["session_id"]]:
            starts[r["session_id"]] = t

    sessions = defaultdict(list)      # session_id -> [(t_seconds, sensor_id, value, unit)]
    subject = {}
    for r in csv.DictReader(open(raw_dir / "readings.csv", newline="")):
        sid = r["session_id"]
        t = (parse_ts(r["timestamp"]) - starts[sid]).total_seconds()
        sessions[sid].append((t, r["sensor_id"], float(r["value"]), r["unit"]))
        subject[sid] = r["subject_id"]
    return sessions, starts, subject


# ---------------------------------------------------------------------------
# Step 2: encode one session into frames
# ---------------------------------------------------------------------------

def encode_session(layout, readings, frame_interval: float, seq0: int):
    """
    Frame k covers [k*frame_interval, (k+1)*frame_interval) and carries the latest
    value of every channel. Channels with no new reading in that window are sent
    with their held value and marked stale (valid_mask bit cleared).

    Returns [(seq, k, frame_bytes)].
    """
    fresh_by_frame = defaultdict(dict)
    for t, sensor, value, _unit in readings:
        fresh_by_frame[int(t // frame_interval)][sensor] = value   # latest wins
    n_frames = max(fresh_by_frame) + 1 if fresh_by_frame else 0
    if n_frames >= 0x8000:
        raise SystemExit("too many frames per session for a 16-bit seq; raise --frame-interval")

    last, frames = {}, []
    for k in range(n_frames):
        fresh = fresh_by_frame.get(k, {})
        last.update(fresh)
        values, stale = {}, []
        for c in layout.channels:
            if c.name in last:
                values[c.name] = last[c.name]
            elif c.invalid_raw is not None:
                values[c.name] = None            # no data yet: sends the fault sentinel
            else:
                values[c.name] = 0               # no data yet, no sentinel: placeholder
            if c.name not in fresh:
                stale.append(c.name)
        seq = (seq0 + k) & 0xFFFF
        frames.append((seq, k, layout.encode_frame(values, seq=seq, stale=stale)))
    return frames


# ---------------------------------------------------------------------------
# Step 3: the "radio link"
# ---------------------------------------------------------------------------

def transmit(frames, rng, drop: float, corrupt: float, duplicate: float, sync_len: int):
    """Apply link faults. Returns (bytes on the wire, [(seq, k, event)])."""
    wire, events = bytearray(), []
    for seq, k, frame in frames:
        if rng.random() < drop:
            events.append((seq, k, "dropped"))
            continue
        if rng.random() < corrupt:
            i = rng.randrange(sync_len, len(frame))
            frame = frame[:i] + bytes([frame[i] ^ 0xFF]) + frame[i + 1:]
            events.append((seq, k, "corrupted"))
        wire += frame
        if rng.random() < duplicate:
            wire += frame
            events.append((seq, k, "duplicated"))
    return bytes(wire), events


# ---------------------------------------------------------------------------
# Step 4: decode
# ---------------------------------------------------------------------------

def decode_session(decoder_mod, layout, wire: bytes, seq0: int, chunk: int = 256):
    dec = decoder_mod.StreamDecoder(layout)
    packets = []
    for i in range(0, len(wire), chunk):            # arrives in chunks, like a serial port
        packets += dec.feed(wire[i:i + chunk])
    return packets, dec.stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def check_observability(raw_dir, decoded_path, output_path):
    # Load the original readings
    original = defaultdict(list)
    with open(raw_dir / "readings.csv", newline="") as f:
        for row in csv.DictReader(f):
            key = (row["session_id"], row["sensor_id"])
            original[key].append(parse_ts(row["timestamp"]))

    # Load readings that survived transmission
    decoded = defaultdict(list)
    with open(decoded_path, newline="") as f:
        for row in csv.DictReader(f):
            key = (row["session_id"], row["sensor_id"])
            decoded[key].append(parse_ts(row["timestamp"]))

    # Check how many readings survived during each anomaly
    with open(raw_dir / "labels.csv", newline="") as f:
        labels = list(csv.DictReader(f))

    for label in labels:
        key = (label["session_id"], label["sensor_id"])
        start = parse_ts(label["start"])
        end = parse_ts(label["end"])

        expected = sum(start <= t < end for t in original[key])
        received = sum(start <= t < end for t in decoded[key])

        coverage = received / expected if expected else 0.0

        label["expected_samples"] = expected
        label["received_samples"] = received
        label["coverage"] = round(min(coverage, 1.0), 3)
        label["observable"] = int(received > 0)

        # Check if any readings survived after the critical threshold was crossed
        critical_at = label["critical_at"]
        if critical_at:
            critical_time = parse_ts(critical_at)
            label["post_critical_evidence"] = int(
                any(critical_time <= t < end for t in decoded[key])
            )
        else:
            label["post_critical_evidence"] = 0

    fields = [
        "session_id", "subject_id", "sensor_id",
        "type", "start", "end", "critical_at",
        "expected_samples", "received_samples",
        "coverage", "observable", "post_critical_evidence"
    ]

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(labels)

def main() -> None:
    ap = argparse.ArgumentParser(description="Run the generator through the serial encoder/decoder.")
    ap.add_argument("--out", default="data/via_decoder")
    ap.add_argument("--sessions", type=int, default=6)
    ap.add_argument("--subjects", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--config", default=None, help="sensor config (default: sensors.json next to generator.py)")
    ap.add_argument("--generator", default=str(DEFAULT_GENERATOR))
    ap.add_argument("--decoder", default=str(DEFAULT_DECODER))
    ap.add_argument("--layout", default=None, help="packet layout YAML (default: the decoder's own)")
    ap.add_argument("--frame-interval", type=float, default=1.0, help="seconds per frame")
    ap.add_argument("--drop", type=float, default=0.0, help="fraction of frames lost on the link")
    ap.add_argument("--corrupt", type=float, default=0.0, help="fraction of frames with a flipped byte")
    ap.add_argument("--duplicate", type=float, default=0.0, help="fraction of frames sent twice")
    ap.add_argument("--link-seed", type=int, default=None, help="seed for link faults (default: --seed)")
    args = ap.parse_args()

    out = Path(args.out)
    raw_dir = out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # 1. generate
    run_generator(args, raw_dir)
    sessions, starts, subject = load_sessions(raw_dir)

    # 2. load decoder + layout, check the sensors match the packet layout
    decoder_mod = load_module("decoder", Path(args.decoder))
    layout = decoder_mod.PacketLayout.from_yaml(args.layout or decoder_mod.DEFAULT_LAYOUT)
    if layout.provisional:
        print("WARNING: packet layout is PROVISIONAL (placeholder struct).", file=sys.stderr)
    channels = {c.name: c for c in layout.channels}
    sensors = {s for rows in sessions.values() for _t, s, _v, _u in rows}
    missing = sorted(sensors - set(channels))
    if missing:
        raise SystemExit(f"Sensors not in packet_layout.yaml (would be lost): {missing}")
    units = {s: u for rows in sessions.values() for _t, s, _v, u in rows}
    for s in sorted(sensors):
        if channels[s].unit != units[s]:
            print(f"WARNING: unit mismatch for {s}: generator '{units[s]}' vs layout '{channels[s].unit}'",
                  file=sys.stderr)

    link_rng = random.Random(args.seed if args.link_seed is None else args.link_seed)
    order = {c.name: i for i, c in enumerate(layout.channels)}
    seq = 0
    totals = defaultdict(int)
    max_err = defaultdict(float)

    with open(out / "readings.csv", "w", newline="") as rf, \
         open(out / "link_events.csv", "w", newline="") as ef, \
         open(out / "capture.bin", "wb") as capture:
        rw, ew = csv.writer(rf), csv.writer(ef)
        rw.writerow(["timestamp", "session_id", "subject_id", "sensor_id", "value", "unit"])
        ew.writerow(["session_id", "seq", "frame_time", "event"])

        for sid in sorted(sessions):
            t0 = starts[sid]
            readings = sessions[sid]

            frames = encode_session(layout, readings, args.frame_interval, seq)
            wire, events = transmit(frames, link_rng, args.drop, args.corrupt, args.duplicate,
                                    len(layout.sync))
            capture.write(wire)
            for s_, k, ev in events:
                ew.writerow([sid, s_, iso(t0 + timedelta(seconds=k * args.frame_interval)), ev])

            packets, stats = decode_session(decoder_mod, layout, wire, seq)

            # back to rows: keep fresh readings, timestamped at the start of their frame
            raw_by_frame = {(int(t // args.frame_interval), s): v for t, s, v, _u in readings}
            out_rows = []
            for p in packets:
                k = (p.seq - seq) & 0xFFFF
                for name, r in p.readings.items():
                    if name in sensors and r.quality in ("ok", "suspect") and r.value is not None:
                        out_rows.append((k * args.frame_interval, order[name], name, r.value))
                        orig = raw_by_frame.get((k, name))
                        if orig is not None:
                            max_err[name] = max(max_err[name], abs(orig - r.value))
            out_rows.sort()
            for t, _o, name, v in out_rows:
                rw.writerow([iso(t0 + timedelta(seconds=t)), sid, subject[sid], name, v, units[name]])

            totals["readings_in"] += len(readings)
            totals["readings_out"] += len(out_rows)
            totals["frames_sent"] += len(frames)
            totals["bytes"] += len(wire)
            for field in ("frames_ok", "crc_errors", "packets_lost", "duplicates",
                          "out_of_order", "bytes_skipped"):
                totals[field] += getattr(stats, field)
            seq = (seq + len(frames)) & 0xFFFF

    for name in ("labels.csv", "activity.csv"):
        shutil.copy(raw_dir / name, out / name)

    #Observability code
    check_observability(
        raw_dir,
        out / "readings.csv",
        out / "labels_observability.csv"
    )

    summary = {
        "layout_version": layout.version,
        "layout_provisional": layout.provisional,
        "frame_len_bytes": layout.frame_len,
        "frame_interval_s": args.frame_interval,
        "link": {"drop": args.drop, "corrupt": args.corrupt, "duplicate": args.duplicate},
        **totals,
        "max_quantization_error": {k: round(v, 6) for k, v in sorted(max_err.items())},
    }
    (out / "link_stats.json").write_text(json.dumps(summary, indent=2))

    kept = totals["readings_out"] / totals["readings_in"] if totals["readings_in"] else 0
    print(f"\nFrames: {totals['frames_sent']:,} sent, {totals['frames_ok']:,} decoded "
          f"({layout.frame_len} bytes each, {totals['bytes']:,} bytes total)")
    print(f"Decoder: {totals['crc_errors']} CRC errors, {totals['packets_lost']} lost, "
          f"{totals['duplicates']} duplicates dropped, {totals['out_of_order']} out of order")
    print(f"Readings: {totals['readings_in']:,} in -> {totals['readings_out']:,} out ({kept:.1%} kept)")
    print(f"Wrote {out}/readings.csv, capture.bin, link_events.csv, link_stats.json")


if __name__ == "__main__":
    main()
