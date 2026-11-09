
import installObjectProvider from "./object-provider.js";
import installTelemetryProvider from "./telemetry-provider.js";
import installMissionDashboard from "../views/mission-dashboard.js";

export default function COSGCPlugin() {
    return function install(openmct) {
        installObjectProvider(openmct);
        installTelemetryProvider(openmct);
        installMissionDashboard(openmct);
    };
}
