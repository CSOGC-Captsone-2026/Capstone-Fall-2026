const simulationUrl = (
    import.meta.env.VITE_SIMULATION_URL || "http://127.0.0.1:8765"
).replace(/\/$/, "");

const listeners = new Map();
let eventSource;

function ensureStream() {
    if (eventSource) return;

    eventSource = new EventSource(`${simulationUrl}/api/stream`);
    eventSource.onmessage = event => {
        const reading = JSON.parse(event.data);
        const callbacks = listeners.get(reading.sensor);
        callbacks?.forEach(callback => callback(reading));
    };
}

export async function requestSimulationHistory(sensor, start, end) {
    const query = new URLSearchParams({ sensor, start, end });
    const response = await fetch(
        `${simulationUrl}/api/history?${query}`
    );

    if (!response.ok) {
        throw new Error(`Simulation history request failed: ${response.status}`);
    }

    return response.json();
}

export function subscribeToSimulation(sensor, callback) {
    if (!listeners.has(sensor)) listeners.set(sensor, new Set());
    listeners.get(sensor).add(callback);
    ensureStream();

    return () => {
        const callbacks = listeners.get(sensor);
        callbacks?.delete(callback);
        if (callbacks?.size === 0) listeners.delete(sensor);

        if (listeners.size === 0 && eventSource) {
            eventSource.close();
            eventSource = null;
        }
    };
}
