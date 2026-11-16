
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

### Plot detail and missing readings

Sensor plots reduce display detail without changing the simulation or its
stored history. Historical plot requests use Open MCT's min/max strategy and
point limit; both historical and live plots display the mean of readings in
each five-second timestamp interval. This smooths sensor noise and reduces
visual clutter without modifying raw readings on the simulation server. Short
spikes can be softened by averaging; the demo's configured anomalies last
minutes. At `--speed 10`, a sensor configured for 1 Hz can produce ten
simulated readings per real second.

Open MCT connects numeric readings with straight lines by default. It does not
create new telemetry samples, but a line between two readings is a visual
interpolation. A simulated `dropout` skips readings; the plot may connect the
readings on either side, so that line alone does not distinguish a dropout
from a gradual change.

The dashboard's live stream sends JSON readings directly; this path does not
simulate packet encoding or packet loss. If the browser disconnects, missed
live events are not replayed, though available server history can be requested
when the graph loads. A slow stream client can also overflow its 1,000-reading
queue; the current server drops readings in that case without marking the gap.
The separate `generator/run_via_decoder.py` tool simulates packet encoding,
decoding, and link loss.

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
