
import { sensors } from "../config/sensors.js";
import { subscribeToSimulation } from "../plugins/simulation-client.js";
import "./mission-dashboard.css";

export default function installMissionDashboard(openmct) {
    openmct.objectViews.addProvider({
        key: "cosgc.mission-view",
        name: "Mission Overview",
        cssClass: "icon-layout",

        canView(domainObject) {
            return domainObject.type === "cosgc.dashboard";
        },

        view(domainObject) {
            let container;
            let handleSensorNavigation;
            const simulationSubscriptions = [];

            function statusFor(sensor, value = sensor.value) {
                const critical = sensor.critical || {};

                if (
                    (critical.low !== undefined &&
                        value < critical.low) ||
                    (critical.high !== undefined &&
                        value > critical.high)
                ) {
                    return { text: "CRITICAL", css: "warning" };
                }

                if (
                    value < sensor.normal[0] ||
                    value > sensor.normal[1]
                ) {
                    return {
                        text: "Outside normal",
                        css: "warning"
                    };
                }

                return { text: "Normal", css: "good" };
            }

            function sensorCard(key, sensor) {
                const status = statusFor(sensor);

                return `
                    <button
                        class="sensor-card sensor-card-link"
                        type="button"
                        data-sensor-key="${key}"
                        aria-label="View ${sensor.name} graph"
                    >
                        <div class="sensor-name">${sensor.name}</div>
                        <div class="sensor-value" data-live-value>
                            ${sensor.value}
                            <span class="sensor-unit">
                                ${sensor.unit}
                            </span>
                        </div>
                        <div class="sensor-footer">
                            <span>
                                Normal: ${sensor.normal.join("–")}
                            </span>
                            <span class="${status.css}" data-live-status>
                                ${status.text}
                            </span>
                        </div>
                        <div class="sensor-card-action">
                            View graph <span aria-hidden="true">→</span>
                        </div>
                    </button>
                `;
            }

            function section(title, source) {
                const cards = Object.entries(sensors)
                    .filter(([, sensor]) =>
                        sensor.enabled && sensor.source === source
                    )
                    .map(([key, sensor]) => sensorCard(key, sensor))
                    .join("");

                return `
                    <section class="mission-section">
                        <h2>${title}</h2>
                        <div class="sensor-grid">${cards}</div>
                    </section>
                `;
            }

            return {
                show(element) {
                    container = document.createElement("div");
                    container.className = "mission-dashboard";

                    const anomalyOnly =
                        domainObject.identifier.key ===
                        "anomaly_status";

                    container.innerHTML = `
                        <div class="mission-header">
                            <div>
                                <h1>
                                    ${anomalyOnly
                        ? "Anomaly Detection"
                        : "Analog Astronaut Mission"}
                                </h1>
                                <div class="muted">
                                    COSGC Digital Twin • Static Prototype
                                </div>
                            </div>
                            <div class="status">DEMO MODE</div>
                        </div>

                        ${anomalyOnly ? "" : `
                            <section class="mission-section">
                                <h2>Mission Overview</h2>
                                <div class="sensor-grid">
                                    <div class="sensor-card">
                                        <div class="sensor-name">
                                            Astronaut
                                        </div>
                                        <div class="sensor-value">
                                            EVA-01
                                        </div>
                                        <div class="muted">
                                            Analog Mission
                                        </div>
                                    </div>

                                    <div class="sensor-card">
                                        <div class="sensor-name">
                                            Mission Status
                                        </div>
                                        <div class="sensor-value good">
                                            NOMINAL
                                        </div>
                                        <div class="muted">
                                            Simulated
                                        </div>
                                    </div>

                                    <div class="sensor-card">
                                        <div class="sensor-name">
                                            Detected Anomalies
                                        </div>
                                        <div class="sensor-value">—</div>
                                        <div class="muted">
                                            Model not connected
                                        </div>
                                    </div>
                                </div>
                            </section>

                            ${section("Biometric Sensors", "biometric")}
                            ${section("Environmental Sensors", "environmental")}
                        `}

                        <section class="mission-section">
                            <h2>AI Anomaly Detection</h2>
                            <div class="placeholder">
                                <strong>Model not connected</strong>
                                <p>
                                    Future anomaly detection results
                                    will appear here.
                                </p>
                                <p>
                                    Planned categories: ramp, spike,
                                    stuck, dropout, and contextual
                                    anomalies.
                                </p>
                            </div>
                        </section>

                        <div class="mission-note">
                            SIMULATED DATA ONLY. Sensor thresholds
                            are placeholders pending hardware and
                            safety validation. Suit pressure is
                            disabled for the unpressurized analog
                            suit configuration.
                        </div>
                    `;

                    element.appendChild(container);

                    handleSensorNavigation = event => {
                        const card = event.target.closest(
                            "[data-sensor-key]"
                        );

                        if (!card || !container.contains(card)) return;

                        const sensorKey = card.dataset.sensorKey;
                        const sensor = sensors[sensorKey];

                        if (!sensor?.enabled) return;

                        openmct.router.navigate(
                            `#/browse/cosgc:mission/` +
                            `cosgc:${sensor.source}/` +
                            `cosgc:${sensorKey}?view=plot-single`
                        );
                    };

                    container.addEventListener(
                        "click",
                        handleSensorNavigation
                    );

                    for (const [key, sensor] of Object.entries(sensors)) {
                        if (!sensor.enabled) continue;

                        simulationSubscriptions.push(
                            subscribeToSimulation(key, reading => {
                                const card = container?.querySelector(
                                    `[data-sensor-key="${key}"]`
                                );
                                if (!card) return;

                                const value = Number(reading.value);
                                const status = statusFor(sensor, value);
                                card.querySelector("[data-live-value]")
                                    .innerHTML = `
                                        ${value.toLocaleString(undefined, {
                                            maximumFractionDigits: 3
                                        })}
                                        <span class="sensor-unit">
                                            ${sensor.unit}
                                        </span>
                                    `;
                                const statusElement = card.querySelector(
                                    "[data-live-status]"
                                );
                                statusElement.className = status.css;
                                statusElement.textContent = status.text;
                            })
                        );
                    }
                },

                destroy() {
                    simulationSubscriptions.splice(0).forEach(
                        unsubscribe => unsubscribe()
                    );
                    if (container) {
                        container.removeEventListener(
                            "click",
                            handleSensorNavigation
                        );
                        container.remove();
                        container = null;
                        handleSensorNavigation = null;
                    }
                }
            };
        }
    });
}
