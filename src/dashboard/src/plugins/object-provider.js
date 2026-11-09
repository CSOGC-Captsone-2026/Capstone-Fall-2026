
import { sensors } from "../config/sensors.js";

export default function installObjectProvider(openmct) {
    const namespace = "cosgc";
    const objects = {};
    const children = {};

    function id(key) {
        return { namespace, key };
    }

    function addFolder(key, name, parent = null) {
        objects[key] = {
            identifier: id(key),
            name,
            type: "folder",
            location: parent
                ? `${namespace}:${parent}`
                : "ROOT"
        };

        children[key] = [];

        if (parent) {
            children[parent].push(id(key));
        }
    }

    // Mission hierarchy
    addFolder("mission", "Analog Astronaut Mission");
    addFolder("biometric", "Biometric Sensors", "mission");
    addFolder("environmental", "Environmental Sensors", "mission");
    addFolder("anomalies", "Anomaly Detection", "mission");

    // Main dashboard
    objects.dashboard = {
        identifier: id("dashboard"),
        name: "Mission Dashboard",
        type: "cosgc.dashboard",
        location: `${namespace}:mission`
    };

    children.mission.unshift(id("dashboard"));

    // Individual sensor objects
    for (const [key, sensor] of Object.entries(sensors)) {
        if (!sensor.enabled) continue;

        objects[key] = {
            identifier: id(key),
            name: sensor.name,
            type: "cosgc.sensor",
            location: `${namespace}:${sensor.source}`,
            telemetry: {
                values: [
                    {
                        key: "value",
                        name: sensor.name,
                        unit: sensor.unit,
                        format: "float",
                        min: sensor.normal[0],
                        max: sensor.normal[1],
                        hints: { range: 1 }
                    },
                    {
                        key: "utc",
                        source: "timestamp",
                        name: "Timestamp",
                        format: "utc",
                        hints: { domain: 1 }
                    }
                ]
            }
        };

        children[sensor.source].push(id(key));
    }

    // Anomaly detection placeholder
    objects.anomaly_status = {
        identifier: id("anomaly_status"),
        name: "AI Anomaly Status",
        type: "cosgc.dashboard",
        location: `${namespace}:anomalies`
    };

    children.anomalies.push(id("anomaly_status"));

    // Register object types
    openmct.types.addType("cosgc.sensor", {
        name: "COSGC Sensor",
        description: "Analog astronaut sensor measurement",
        cssClass: "icon-telemetry"
    });

    openmct.types.addType("cosgc.dashboard", {
        name: "COSGC Dashboard",
        description: "COSGC mission dashboard",
        cssClass: "icon-layout"
    });

    // Resolve objects by identifier
    openmct.objects.addProvider(namespace, {
        get(identifier) {
            return Promise.resolve(objects[identifier.key]);
        }
    });

    // Resolve folder contents
    openmct.composition.addProvider({
        appliesTo(domainObject) {
            return domainObject.identifier.namespace === namespace
                && domainObject.type === "folder";
        },

        load(domainObject) {
            return Promise.resolve(
                children[domainObject.identifier.key] || []
            );
        }
    });

    // Add our mission to the Open MCT navigation tree
    openmct.objects.addRoot(id("mission"));
}
