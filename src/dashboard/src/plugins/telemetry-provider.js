
import { sensors } from "../config/sensors.js";
import {
    requestSimulationHistory,
    subscribeToSimulation
} from "./simulation-client.js";

const DISPLAY_BUCKET_MS = 5000;

function averagePoints(points) {
    if (points.length === 0) return [];

    const averaged = [];
    let bucketStart;
    let sum = 0;
    let count = 0;
    let lastPoint;

    function flushBucket() {
        if (count === 0) return;

        averaged.push({
            ...lastPoint,
            value: sum / count
        });
        sum = 0;
        count = 0;
    }

    for (const point of points) {
        const pointBucketStart =
            Math.floor(point.timestamp / DISPLAY_BUCKET_MS)
            * DISPLAY_BUCKET_MS;

        if (bucketStart !== undefined && pointBucketStart !== bucketStart) {
            flushBucket();
        }

        bucketStart = pointBucketStart;
        sum += point.value;
        count++;
        lastPoint = point;
    }

    flushBucket();
    return averaged;
}

function minMaxPoints(points, maxPoints) {
    if (points.length <= maxPoints) return points;
    if (maxPoints === 1) return [points[points.length - 1]];
    if (maxPoints === 2) return [points[0], points[points.length - 1]];

    const bucketCount = Math.floor((maxPoints - 2) / 2);
    const selected = [points[0]];

    for (let bucket = 0; bucket < bucketCount; bucket++) {
        const start = 1 + Math.floor(
            bucket * (points.length - 2) / bucketCount
        );
        const end = 1 + Math.floor(
            (bucket + 1) * (points.length - 2) / bucketCount
        );
        let min = points[start];
        let max = points[start];

        for (let i = start + 1; i < end; i++) {
            if (points[i].value < min.value) min = points[i];
            if (points[i].value > max.value) max = points[i];
        }

        if (min.timestamp <= max.timestamp) {
            selected.push(min);
            if (max !== min) selected.push(max);
        } else {
            selected.push(max);
            selected.push(min);
        }
    }

    selected.push(points[points.length - 1]);
    return selected;
}

function subscribeToDisplayTelemetry(sensorKey, callback) {
    let bucketStart;
    let bucket = [];
    let flushTimer;

    function flushBucket() {
        clearTimeout(flushTimer);
        flushTimer = undefined;

        if (bucket.length === 0) return;

        const points = averagePoints(bucket);
        bucket = [];
        bucketStart = undefined;
        points.forEach(callback);
    }

    const unsubscribe = subscribeToSimulation(sensorKey, reading => {
        const readingBucketStart =
            Math.floor(reading.timestamp / DISPLAY_BUCKET_MS)
            * DISPLAY_BUCKET_MS;

        if (
            bucketStart !== undefined &&
            readingBucketStart !== bucketStart
        ) {
            flushBucket();
        }

        if (bucketStart === undefined) {
            bucketStart = readingBucketStart;
            flushTimer = setTimeout(
                flushBucket,
                Math.max(
                    0,
                    bucketStart + DISPLAY_BUCKET_MS - Date.now()
                )
            );
        }

        bucket.push(reading);
    });

    return () => {
        flushBucket();
        unsubscribe();
    };
}

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
                const readings = await requestSimulationHistory(
                    domainObject.identifier.key,
                    start,
                    end
                );
                const points = averagePoints(readings);
                const size = options.size;

                if (!Number.isFinite(size) || size <= 0) return points;

                if (options.strategy === "latest" || size === 1) {
                    return points.length ? [points[points.length - 1]] : [];
                }

                if (options.strategy === "minmax") {
                    return minMaxPoints(points, Math.floor(size));
                }

                return points.slice(-Math.floor(size));
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

            return subscribeToDisplayTelemetry(
                domainObject.identifier.key,
                callback
            );
        }
    });
}
