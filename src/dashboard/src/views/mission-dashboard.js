
import { sensors } from "../config/sensors.js";
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

            function statusFor(sensor) {
                const critical = sensor.critical || {};

                if (
                    (critical.low !== undefined &&
                        sensor.value < critical.low) ||
                    (critical.high !== undefined &&
                        sensor.value > critical.high)
                ) {
                    return { text: "CRITICAL", css: "warning" };
                }

                if (
                    sensor.value < sensor.normal[0] ||
                    sensor.value > sensor.normal[1]
                ) {
                    return {
                        text: "Outside normal",
                        css: "warning"
                    };
                }

                return { text: "Normal", css: "good" };
            }

            function sensorCard(sensor) {
                const status = statusFor(sensor);

                return `
                    <div class="sensor-card">
                        <div class="sensor-name">${sensor.name}</div>
                        <div class="sensor-value">
                            ${sensor.value}
                            <span class="sensor-unit">
                                ${sensor.unit}
                            </span>
                        </div>
                        <div class="sensor-footer">
                            <span>
                                Normal: ${sensor.normal.join("–")}
                            </span>
                            <span class="${status.css}">
                                ${status.text}
                            </span>
                        </div>
                    </div>
                `;
            }

            function section(title, source) {
                const cards = Object.values(sensors)
                    .filter(s => s.enabled && s.source === source)
                    .map(sensorCard)
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
                },

                destroy() {
                    if (container) {
                        container.remove();
                        container = null;
                    }
                }
            };
        }
    });
}
