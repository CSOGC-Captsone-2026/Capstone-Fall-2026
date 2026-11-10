
import installObjectProvider from "./object-provider.js";
import installTelemetryProvider from "./telemetry-provider.js";
import installMissionDashboard from "../views/mission-dashboard.js";

export default function COSGCPlugin() {
    return function install(openmct) {
        installObjectProvider(openmct);
        installTelemetryProvider(openmct);
        installMissionDashboard(openmct);

        let dashboardButton;

        function updateDashboardButton() {
            const currentObject = openmct.router.path?.[0];
            const isSensorGraph =
                currentObject?.identifier?.namespace === "cosgc" &&
                currentObject.type === "cosgc.sensor";

            if (dashboardButton) {
                dashboardButton.hidden = !isSensorGraph;
            }
        }

        function mountDashboardButton() {
            const graphHeader = openmct.element.querySelector(
                ".l-shell__main-view-browse-bar"
            );

            if (!graphHeader) return;

            dashboardButton = document.createElement("button");
            dashboardButton.className = "dashboard-back-button";
            dashboardButton.type = "button";
            dashboardButton.hidden = true;
            dashboardButton.textContent = "← Mission Dashboard";
            dashboardButton.addEventListener("click", () => {
                openmct.router.navigate(
                    "#/browse/cosgc:mission/cosgc:dashboard"
                );
            });

            graphHeader.appendChild(dashboardButton);
            openmct.router.on("afterNavigation", updateDashboardButton);
            updateDashboardButton();
        }

        openmct.once("start", mountDashboardButton);
        openmct.once("destroy", () => {
            openmct.router.off(
                "afterNavigation",
                updateDashboardButton
            );
            dashboardButton?.remove();
            dashboardButton = null;
        });
    };
}
