
import { sensors } from "../config/sensors.js";

export default function installTelemetryProvider(openmct) {
    openmct.telemetry.addProvider({
        supportsRequest(domainObject) {
            return domainObject.type === "cosgc.sensor";
        },

        request(domainObject, options) {
            const sensor = sensors[domainObject.identifier.key];

            if (!sensor || !sensor.enabled) {
                return Promise.resolve([]);
            }

            const start = options.start ?? Date.now() - 900000;
            const end = options.end ?? Date.now();

            const interval = Math.max(
                1000,
                1000 / sensor.rate_hz
            );

            const step = Math.max(
                interval,
                (end - start) / 300
            );

            const points = [];

            for (let t = start; t <= end; t += step) {
                points.push({
                    timestamp: t,
                    value: sensor.value
                });
            }

            return Promise.resolve(points);
        },

        supportsSubscribe(domainObject) {
            return domainObject.type === "cosgc.sensor";
        },

        subscribe(domainObject, callback) {
            const sensor = sensors[domainObject.identifier.key];

            if (!sensor || !sensor.enabled) {
                return () => {};
            }

            const interval = Math.max(
                1000,
                1000 / sensor.rate_hz
            );

            const timer = setInterval(() => {
                callback({
                    timestamp: Date.now(),
                    value: sensor.value
                });
            }, interval);

            // Open MCT calls this when it unsubscribes
            return () => clearInterval(timer);
        }
    });
}
