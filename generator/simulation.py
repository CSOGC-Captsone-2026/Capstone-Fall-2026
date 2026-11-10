#!/usr/bin/env python3
"""Replay one generated suit mission as live HTTP telemetry for the dashboard."""

import argparse
import json
import queue
import random
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import Generator as generator


class Simulation:
    def __init__(self, config_path, seed, speed):
        self.config_path = Path(config_path)
        self.speed = speed
        self.lock = threading.Lock()
        self.history = defaultdict(list)
        self.clients = set()
        self.rows, self.duration, self.anomalies = self._build(seed)
        self.started_at_ms = int(time.time() * 1000)
        self.finished = False

    def _build(self, seed):
        cfg = json.loads(self.config_path.read_text())
        sensors = {
            key: value for key, value in cfg["sensors"].items()
            if value.get("enabled", True)
        }
        rng = random.Random(seed)
        windows, targets = generator.build_timeline(cfg["session"]["phases"])
        duration = windows[-1]["end"]
        planned = generator.plan_anomalies(
            rng, sensors, cfg["anomalies"], windows, duration
        )
        rows = []
        for sensor_id, sensor in sensors.items():
            activity = generator.smooth(
                targets, sensor.get("response_s", 60)
            )
            cumulative = generator.cumulative_minutes(activity)
            baseline = rng.uniform(*sensor["normal"])
            mine = [
                anomaly for anomaly in planned
                if anomaly["sensor_id"] == sensor_id
            ]
            samples, _ = generator.generate_sensor(
                rng,
                sensor,
                baseline,
                activity,
                cumulative,
                duration,
                mine,
                cfg["anomalies"].get("ramp_overshoot", 1.15),
            )
            rows.extend((t, sensor_id, value) for t, value in samples)
        rows.sort()
        return rows, duration, planned

    def subscribe(self):
        messages = queue.Queue(maxsize=1000)
        with self.lock:
            self.clients.add(messages)
        return messages

    def unsubscribe(self, messages):
        with self.lock:
            self.clients.discard(messages)

    def publish(self, reading):
        with self.lock:
            self.history[reading["sensor"]].append(reading)
            clients = list(self.clients)
        for messages in clients:
            try:
                messages.put_nowait(reading)
            except queue.Full:
                pass

    def run(self):
        real_start = time.monotonic()
        for simulated_s, sensor, value in self.rows:
            due = real_start + simulated_s / self.speed
            delay = due - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self.publish({
                "sensor": sensor,
                "timestamp": self.started_at_ms + int(simulated_s * 1000 / self.speed),
                "value": value,
                "simulation_seconds": simulated_s,
            })
        self.finished = True


class Handler(BaseHTTPRequestHandler):
    simulation = None

    def _headers(self, status=200, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/history":
            query = parse_qs(parsed.query)
            sensor = query.get("sensor", [""])[0]
            start = int(float(query.get("start", [0])[0]))
            end = int(float(query.get("end", [time.time() * 1000])[0]))
            with self.simulation.lock:
                readings = [
                    reading for reading in self.simulation.history.get(sensor, [])
                    if start <= reading["timestamp"] <= end
                ]
            self._headers()
            self.wfile.write(json.dumps(readings).encode())
            return

        if parsed.path == "/api/status":
            self._headers()
            self.wfile.write(json.dumps({
                "speed": self.simulation.speed,
                "duration_seconds": self.simulation.duration,
                "started_at": self.simulation.started_at_ms,
                "finished": self.simulation.finished,
                "anomalies": self.simulation.anomalies,
            }).encode())
            return

        if parsed.path == "/api/stream":
            self._stream()
            return

        self._headers(404)
        self.wfile.write(b'{"error":"not found"}')

    def _stream(self):
        messages = self.simulation.subscribe()
        self._headers(200, "text/event-stream")
        try:
            while True:
                try:
                    reading = messages.get(timeout=15)
                    payload = json.dumps(reading)
                    self.wfile.write(f"data: {payload}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.simulation.unsubscribe(messages)

    def log_message(self, format_string, *args):
        if self.path != "/api/stream":
            super().log_message(format_string, *args)


def main():
    parser = argparse.ArgumentParser(
        description="Stream generated suit telemetry to the Open MCT dashboard."
    )
    parser.add_argument("--config", default=Path(__file__).with_name("Sensors.JSON"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--speed", type=float, default=10.0)
    args = parser.parse_args()
    if args.speed <= 0:
        parser.error("--speed must be greater than zero")

    simulation = Simulation(args.config, args.seed, args.speed)
    Handler.simulation = simulation
    threading.Thread(target=simulation.run, daemon=True).start()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Simulation API: http://{args.host}:{args.port}")
    print(f"Mission: {simulation.duration / 60:.0f} simulated minutes at {args.speed:g}x")
    print("Planned anomalies:")
    for anomaly in simulation.anomalies:
        print(
            f"  {anomaly['sensor_id']}: {anomaly['type']} "
            f"from {anomaly['start'] / 60:.1f} to {anomaly['end'] / 60:.1f} min"
        )
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nSimulation stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
