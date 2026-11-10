
# COSGC Digital Twin Dashboard

Open MCT-based dashboard for visualizing environmental and biometric sensor telemetry.

## Running a Live Simulation

**Prerequisites:** Python 3, Node.js, and npm installed (Node.js 20.19+ or
22.12+ for Vite 8).

Use two terminals from the root of the capstone repository.

In the first terminal, start the telemetry simulation:

```bash
python3 generator/simulation.py --speed 10
```

The simulator reuses the signal model in `generator/Generator.py`, including
sensor-specific sample rates, activity response, noise, drift, and planned
anomalies. It prints the anomalies selected for the session when it starts.

`--speed 10` runs the 80-minute mission in about 8 minutes. The initial
10-minute rest phase lasts about one real minute. For wall-clock playback, use:

```bash
python3 generator/simulation.py --speed 1
```

Use `--seed 7` (or another integer) to select a repeatable mission and anomaly
schedule. The simulation API runs at `http://127.0.0.1:8765` by default.

In the second terminal, start the dashboard:

```bash
cd src/dashboard
npm ci
mkdir -p public/openmct-assets
cp -R node_modules/openmct/dist/. public/openmct-assets/
npm run dev
```

Open the displayed URL, typically **http://localhost:5173/**. The sensor tiles
and Open MCT graphs update as the Python simulation emits readings. Click a
sensor tile to open its live graph.

The dashboard automatically reloads when source files are modified. Restart
the Python process to begin a new simulated mission.

To stop either process, press `Ctrl+C` in its terminal.

### Simulation options

```text
--speed NUMBER   Playback multiplier (default: 10)
--seed INTEGER   Repeatable generated mission (default: 42)
--host ADDRESS   Simulation API bind address (default: 127.0.0.1)
--port PORT      Simulation API port (default: 8765)
--config PATH    Sensor configuration (default: generator/Sensors.JSON)
```

If the simulation runs on another address, set the dashboard URL before
starting Vite:

```bash
VITE_SIMULATION_URL=http://127.0.0.1:9000 npm run dev
```

## Notes

- `npm ci` installs dependencies from `package-lock.json`.
- Open MCT assets must be copied after a fresh installation or dependency update.
- If the simulator is unavailable, graphs show one configured baseline point
  and the browser console reports that the simulation server could not be reached.
- Do not commit `node_modules/`, `dist/`, or generated Open MCT assets.
