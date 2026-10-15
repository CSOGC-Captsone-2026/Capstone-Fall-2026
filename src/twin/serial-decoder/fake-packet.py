#!/usr/bin/env python3
"""
Writes a fake binary capture file in the layout from packet_layout.yaml, with
the problems real LoRa/serial links have: dropped packets, corrupted frames,
garbage bytes, duplicates, and slow sensors that repeat held values.

Use it to test the decoder before hardware exists:
  python packer.py demo.bin
  python decoder.py --file demo.bin

The values are simple random walks around plausible resting numbers. This is
SIMULATED data. For realistic scenarios, drive encode_frame() from generator.py.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

from decoder import DEFAULT_LAYOUT, PacketLayout

# Starting values and per-packet step size for each channel
BASELINES = {
    "heart_rate": (72, 1.5), "respiration_rate": (15, 0.4), "core_temp": (37.0, 0.01),
    "skin_temp": (33.5, 0.03), "perspiration": (4.0, 0.15), "hydration_loss": (0.05, 0.002),
    "spo2": (98, 0.2), "o2": (20.9, 0.01), "co2": (800, 15), "suit_air_temp": (23, 0.05),
    "vent_loop_temp": (20, 0.03), "humidity": (42, 0.3), "pm2_5": (5, 0.3),
}
SLOW_CHANNELS = {"core_temp", "hydration_loss", "pm2_5"}   # updated only every 5th packet


def make_capture(layout: PacketLayout, n_packets: int, seed: int,
                 drop_rate: float, corrupt_rate: float, duplicate_rate: float) -> bytes:
    rng = random.Random(seed)
    state = {c.name: BASELINES.get(c.name, (0.0, 0.0))[0] for c in layout.channels}
    out = bytearray(b"\x13\x37\x00")          # leading garbage, as when opening a port mid-stream

    for seq in range(n_packets):
        for name, (_, step) in BASELINES.items():
            if name in state:
                state[name] += rng.gauss(0, step)

        stale = [n for n in SLOW_CHANNELS if seq % 5 != 0]
        frame = layout.encode_frame(dict(state), seq=seq, header={"bio_status": 1, "env_status": 1},
                                    stale=stale)

        if rng.random() < drop_rate:
            continue                            # lost over the air
        if rng.random() < corrupt_rate:
            i = rng.randrange(len(layout.sync), len(frame))
            frame = frame[:i] + bytes([frame[i] ^ 0xFF]) + frame[i + 1:]   # flipped byte -> bad CRC
        out += frame
        if rng.random() < duplicate_rate:
            out += frame
        if rng.random() < 0.01:
            out += bytes(rng.randrange(256) for _ in range(rng.randint(1, 6)))   # stray noise
    return bytes(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Write a fake binary telemetry capture.")
    ap.add_argument("out", help="output file, e.g. demo.bin")
    ap.add_argument("--layout", default=str(DEFAULT_LAYOUT))
    ap.add_argument("--packets", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--drop", type=float, default=0.05, help="fraction of packets lost")
    ap.add_argument("--corrupt", type=float, default=0.03, help="fraction with a flipped byte")
    ap.add_argument("--duplicate", type=float, default=0.02, help="fraction sent twice")
    args = ap.parse_args()

    layout = PacketLayout.from_yaml(args.layout)
    data = make_capture(layout, args.packets, args.seed, args.drop, args.corrupt, args.duplicate)
    Path(args.out).write_bytes(data)
    print(f"Wrote {len(data):,} bytes ({layout.frame_len}-byte frames) to {args.out}")


if __name__ == "__main__":
    main()