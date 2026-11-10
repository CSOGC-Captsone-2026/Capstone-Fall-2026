
import { sensors } from "../config/sensors.js";
import {
    requestSimulationHistory,
    subscribeToSimulation
} from "./simulation-client.js";

export default function installTelemetryProvider(openmct) {
    openmct.telemetry.addProvider({
        supportsRequest(domainObject) {
            return domainObject.type === "cosgc.sensor";
        },

        async request(domainObject, options) {
            const sensor = sensors[domainObject.identifier.key];

            if (!sensor || !sensor.enabled) {
                return [];
            }

            const start = options.start ?? Date.now() - 900000;
            const end = options.end ?? Date.now();

            try {
                return await requestSimulationHistory(
                    domainObject.identifier.key,
                    start,
                    end
                );
            } catch (error) {
                console.warn(
                    "Simulation server is unavailable; showing the configured baseline.",
                    error
                );
                return [{ timestamp: end, value: sensor.value }];
            }
        },

        supportsSubscribe(domainObject) {
            return domainObject.type === "cosgc.sensor";
        },

        subscribe(domainObject, callback) {
            const sensor = sensors[domainObject.identifier.key];

            if (!sensor || !sensor.enabled) {
                return () => {};
            }

            return subscribeToSimulation(
                domainObject.identifier.key,
                callback
            );
        }
    });
}
