#!/usr/bin/env python3
"""
Serial binary -> Python objects, driven by packet_layout.yaml.

The layout file is the single source of truth for the packet format. When the
hardware teams finalize their struct, edit packet_layout.yaml, not this code.

Pieces:
  PacketLayout   loads the layout, decodes one frame, and encodes one frame (for tests/simulator)
  StreamDecoder  takes raw bytes in arbitrary chunks, finds frame boundaries,
                 checks CRCs, tracks sequence numbers, and yields Packet objects
  Packet         one decoded moment in time: header fields plus a Reading per channel

Usage:
  python decoder.py --file capture.bin
  python decoder.py --port /dev/ttyACM0 --baud 115200      (needs: pip install pyserial)
"""

from __future__ import annotations

import argparse
import binascii
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Optional

import yaml

DEFAULT_LAYOUT = Path(__file__).with_name("packet_layout.yaml")

TYPE_CODES = {
    "uint8": "B", "int8": "b",
    "uint16": "H", "int16": "h",
    "uint32": "I", "int32": "i",
    "float32": "f",
}
INT_RANGES = {
    "uint8": (0, 2**8 - 1), "int8": (-2**7, 2**7 - 1),
    "uint16": (0, 2**16 - 1), "int16": (-2**15, 2**15 - 1),
    "uint32": (0, 2**32 - 1), "int32": (-2**31, 2**31 - 1),
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class LayoutError(Exception):
    """The layout file is invalid."""


class DecodeError(Exception):
    """A frame could not be decoded."""


class CrcError(DecodeError):
    """The frame's CRC did not match its contents."""


# ---------------------------------------------------------------------------
# CRC functions (sender and receiver must use the identical algorithm)
# ---------------------------------------------------------------------------

def crc16_ccitt_false(data: bytes, init: int = 0xFFFF) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF. check("123456789") == 0x29B1."""
    crc = init
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def crc32(data: bytes) -> int:
    return binascii.crc32(data) & 0xFFFFFFFF


# name -> (size in bytes, function)
CRC_ALGORITHMS = {
    "none": (0, None),
    "crc16_ccitt_false": (2, crc16_ccitt_false),
    "crc32": (4, crc32),
}


# ---------------------------------------------------------------------------
# Output objects
# ---------------------------------------------------------------------------

@dataclass
class Reading:
    channel: str
    value: Optional[float] # None when the sensor reported a fault
    unit: str
    quality: str # "ok" | "stale" | "suspect" | "fault"


@dataclass
class Packet:
    received_at: float # seconds since epoch, stamped when the frame was decoded
    header: Dict[str, int]
    readings: Dict[str, Reading]
    gap_before: int = 0 # packets lost between the previous packet and this one

    @property
    def seq(self) -> Optional[int]:
        return self.header.get("seq")

    def values(self) -> Dict[str, Optional[float]]:
        return {name: r.value for name, r in self.readings.items()}

    def to_dict(self) -> dict:
        return {
            "received_at": self.received_at,
            "seq": self.seq,
            "gap_before": self.gap_before,
            "header": self.header,
            "readings": {
                n: {"value": r.value, "unit": r.unit, "quality": r.quality}
                for n, r in self.readings.items()
            },
        }


@dataclass
class Stats:
    frames_ok: int = 0
    crc_errors: int = 0
    bytes_skipped: int = 0 # garbage bytes discarded while hunting for a frame start
    packets_lost: int = 0 # inferred from sequence-number gaps
    duplicates: int = 0
    out_of_order: int = 0


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

@dataclass
class Field:
    name: str
    type: str
    scale: float = 1.0
    offset: float = 0.0
    unit: str = ""
    min: Optional[float] = None
    max: Optional[float] = None
    valid_bit: Optional[int] = None
    invalid_raw: Optional[int] = None


def _make_field(spec: dict) -> Field:
    if spec.get("type") not in TYPE_CODES:
        raise LayoutError(f"field {spec.get('name')!r}: unknown type {spec.get('type')!r}")
    return Field(
        name=spec["name"], type=spec["type"],
        scale=spec.get("scale", 1.0), offset=spec.get("offset", 0.0),
        unit=spec.get("unit", ""), min=spec.get("min"), max=spec.get("max"),
        valid_bit=spec.get("valid_bit"), invalid_raw=spec.get("invalid_raw"),
    )


class PacketLayout:
    def __init__(self, spec: dict):
        self.provisional = bool(spec.get("provisional", False))
        self.version = spec.get("layout_version")

        order = spec.get("byte_order", "little")
        if order not in ("little", "big"):
            raise LayoutError("byte_order must be 'little' or 'big'")
        prefix = "<" if order == "little" else ">"

        self.sync = bytes(spec["sync"])
        if not self.sync:
            raise LayoutError("sync must have at least one byte")

        crc_name = spec.get("crc", "none")
        if crc_name not in CRC_ALGORITHMS:
            raise LayoutError(f"unknown crc {crc_name!r}; options: {list(CRC_ALGORITHMS)}")
        self.crc_size, self._crc_fn = CRC_ALGORITHMS[crc_name]

        self.header: List[Field] = [_make_field(f) for f in spec.get("header", [])]
        self.channels: List[Field] = [_make_field(f) for f in spec["channels"]]

        names = [f.name for f in self.header + self.channels]
        if len(names) != len(set(names)):
            raise LayoutError("field names must be unique")
        bits = [c.valid_bit for c in self.channels if c.valid_bit is not None]
        if len(bits) != len(set(bits)):
            raise LayoutError("valid_bit values must be unique")

        codes = "".join(TYPE_CODES[f.type] for f in self.header + self.channels)
        self._body = struct.Struct(prefix + codes)
        self._crc_struct = (
            struct.Struct(prefix + {2: "H", 4: "I"}[self.crc_size]) if self.crc_size else None
        )
        self.frame_len = len(self.sync) + self._body.size + self.crc_size

    @classmethod
    def from_yaml(cls, path: Path | str = DEFAULT_LAYOUT) -> "PacketLayout":
        with open(path) as f:
            return cls(yaml.safe_load(f))

    # -- decoding -----------------------------------------------------------

    def decode_frame(self, frame: bytes, received_at: Optional[float] = None) -> Packet:
        """Decode exactly one complete frame. Raises DecodeError / CrcError."""
        if len(frame) != self.frame_len:
            raise DecodeError(f"expected {self.frame_len} bytes, got {len(frame)}")
        if not frame.startswith(self.sync):
            raise DecodeError("bad sync bytes")

        body = frame[len(self.sync): len(self.sync) + self._body.size]
        if self._crc_fn is not None:
            (received_crc,) = self._crc_struct.unpack(frame[-self.crc_size:])
            if self._crc_fn(body) != received_crc:
                raise CrcError("CRC mismatch")

        raw = self._body.unpack(body)
        header_raw = raw[: len(self.header)]
        channel_raw = raw[len(self.header):]

        header = {f.name: v for f, v in zip(self.header, header_raw)}
        valid_mask = header.get("valid_mask")

        readings: Dict[str, Reading] = {}
        for f, r in zip(self.channels, channel_raw):
            if f.invalid_raw is not None and r == f.invalid_raw:
                readings[f.name] = Reading(f.name, None, f.unit, "fault")
                continue
            value = round(r * f.scale + f.offset, 6)
            quality = "ok"
            if valid_mask is not None and f.valid_bit is not None \
                    and not (valid_mask >> f.valid_bit) & 1:
                quality = "stale"
            elif (f.min is not None and value < f.min) or (f.max is not None and value > f.max):
                quality = "suspect"
            readings[f.name] = Reading(f.name, value, f.unit, quality)

        return Packet(
            received_at=time.time() if received_at is None else received_at,
            header=header,
            readings=readings,
        )

    # -- encoding (used by tests and the simulator, never by the live pipeline) --

    def encode_frame(
        self,
        values: Dict[str, Optional[float]],
        seq: int = 0,
        header: Optional[Dict[str, int]] = None,
        stale: Iterable[str] = (),
    ) -> bytes:
        """
        Build a valid frame from physical values. Channels listed in `stale` get
        their valid_mask bit cleared. A value of None encodes the invalid_raw sentinel.
        """
        header = header or {}
        stale = set(stale)

        valid_mask = 0
        for c in self.channels:
            if c.valid_bit is not None and c.name not in stale:
                valid_mask |= 1 << c.valid_bit

        raw: List[float] = []
        for f in self.header:
            if f.name == "seq":
                raw.append(seq & 0xFFFF if f.type == "uint16" else seq)
            elif f.name == "valid_mask":
                raw.append(valid_mask)
            else:
                raw.append(header.get(f.name, 0))

        for c in self.channels:
            value = values.get(c.name)
            if value is None:
                if c.invalid_raw is None:
                    raise ValueError(f"{c.name} has no value and no invalid_raw sentinel")
                raw.append(c.invalid_raw)
            elif c.type == "float32":
                raw.append((value - c.offset) / c.scale)
            else:
                lo, hi = INT_RANGES[c.type]
                raw.append(max(lo, min(hi, round((value - c.offset) / c.scale))))

        body = self._body.pack(*raw)
        crc = b""
        if self._crc_fn is not None:
            crc = self._crc_struct.pack(self._crc_fn(body))
        return self.sync + body + crc


# ---------------------------------------------------------------------------
# Stream decoding: bytes in any chunking -> Packet objects
# ---------------------------------------------------------------------------

class StreamDecoder:
    """
    Serial is a byte stream with no packet boundaries, so we buffer bytes, hunt
    for the sync pattern, verify the CRC, and on failure slide forward one byte
    and keep hunting. Garbage and corrupted frames never raise; they are counted.
    """

    def __init__(self, layout: PacketLayout, clock: Callable[[], float] = time.time):
        self.layout = layout
        self.stats = Stats()
        self._clock = clock
        self._buf = bytearray()
        self._last_seq: Optional[int] = None

    def feed(self, data: bytes) -> List[Packet]:
        self._buf.extend(data)
        sync, frame_len = self.layout.sync, self.layout.frame_len
        packets: List[Packet] = []

        while True:
            i = self._buf.find(sync)
            if i == -1:
                # No sync yet, keep a tail in case a sync pattern is split across chunks.
                drop = len(self._buf) - (len(sync) - 1)
                if drop > 0:
                    self.stats.bytes_skipped += drop
                    del self._buf[:drop]
                break
            if i > 0:
                self.stats.bytes_skipped += i
                del self._buf[:i]
            if len(self._buf) < frame_len:
                break  # wait for the rest of the frame

            try:
                packet = self.layout.decode_frame(bytes(self._buf[:frame_len]), self._clock())
            except DecodeError as err:
                if isinstance(err, CrcError):
                    self.stats.crc_errors += 1
                del self._buf[:1] # false sync or corrupted frame: slide one byte and rescan
                continue

            del self._buf[:frame_len]
            packet = self._track_sequence(packet)
            if packet is not None:
                self.stats.frames_ok += 1
                packets.append(packet)
        return packets

    def _track_sequence(self, packet: Packet) -> Optional[Packet]:
        seq = packet.seq
        if seq is None:
            return packet
        if self._last_seq is None:
            self._last_seq = seq
            return packet

        delta = (seq - self._last_seq) & 0xFFFF # handles uint16 wraparound
        if delta == 0:
            self.stats.duplicates += 1
            return None  # drop exact repeats
        if delta >= 0x8000:
            self.stats.out_of_order += 1 # arrived late; keep it, don't move the counter
            return packet

        packet.gap_before = delta - 1
        self.stats.packets_lost += packet.gap_before
        self._last_seq = seq
        return packet


# ---------------------------------------------------------------------------
# Byte sources
# ---------------------------------------------------------------------------

def file_chunks(path: str, chunk_size: int = 4096) -> Iterator[bytes]:
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            yield chunk


def serial_chunks(port: str, baud: int) -> Iterator[bytes]:
    import serial  # pip install pyserial
    with serial.Serial(port, baud, timeout=1) as ser:
        while True:
            data = ser.read(ser.in_waiting or 1)
            if data:
                yield data


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def format_packet(p: Packet) -> str:
    parts = []
    for name, r in p.readings.items():
        mark = "" if r.quality == "ok" else f"[{r.quality}]"
        parts.append(f"{name}={'--' if r.value is None else r.value}{mark}")
    gap = f" LOST={p.gap_before}" if p.gap_before else ""
    return f"seq={p.seq}{gap} " + " ".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description="Decode a binary telemetry stream.")
    ap.add_argument("--layout", default=str(DEFAULT_LAYOUT))
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="raw capture file")
    src.add_argument("--port", help="serial port, e.g. COM3 or /dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=115200)
    args = ap.parse_args()

    layout = PacketLayout.from_yaml(args.layout)
    if layout.provisional:
        print("WARNING: using a PROVISIONAL layout; values are not real.", file=sys.stderr)

    decoder = StreamDecoder(layout)
    chunks = file_chunks(args.file) if args.file else serial_chunks(args.port, args.baud)
    try:
        for chunk in chunks:
            for packet in decoder.feed(chunk):
                print(format_packet(packet))
    except KeyboardInterrupt:
        pass
    print(f"\n{decoder.stats}", file=sys.stderr)


if __name__ == "__main__":
    main()