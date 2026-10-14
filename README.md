# Environmental & Biometric Suit Digital Twin

**CU Boulder | Senior Capstone 2026–2027**

## Overview

This project focuses on developing a digital twin software platform for an environmental and biometric monitoring suit designed to support astronaut safety research during simulated extravehicular activities (EVAs).

The overall project consists of three collaborating teams:

- **Environmental Sensor Team:** Develops hardware for collecting environmental measurements.
- **Biometric Sensor Team:** Develops hardware for collecting physiological measurements.
- **Digital Twin Software Team (Our Team):** Develops the software responsible for integrating, processing, analyzing, and visualizing data from both sensor systems.

Our team is building a centralized platform that will provide real-time telemetry visualization, historical data tracking, and AI-assisted anomaly detection and prediction.

## Project Goals

- Integrate environmental and biometric sensor data into a unified software platform.
- Develop a digital twin that represents the suit's current operating state.
- Provide real-time telemetry visualization through an interactive dashboard.
- Store and analyze historical sensor measurements.
- Develop a machine learning model to detect and predict potentially hazardous anomalies.
- Implement monitoring and alerting capabilities for unsafe operating conditions.

## System Architecture

The proposed software architecture consists of several primary components:

1. **Data Acquisition:** Receives telemetry from the environmental and biometric sensor systems.
2. **Backend & Digital Twin:** Processes incoming measurements, manages system state, and stores historical data.
3. **AI/ML Model:** Analyzes sensor measurements to detect anomalies and predict potentially unsafe conditions.
4. **Visualization Dashboard:** Displays real-time telemetry, historical trends, system status, and alerts.

*The architecture is preliminary and subject to change as hardware interfaces and software requirements are finalized.*

## Technologies

Technologies currently in use or under evaluation include:

- **NASA Open MCT** — Telemetry visualization and dashboard framework
- **Python** — Backend development and machine learning
- **Docker** — Containerized development environment
- **Git / GitHub** — Version control and collaboration

Additional technologies and frameworks will be documented as development progresses.

## Getting Started

### Prerequisites

- Git
- Docker

### Clone the Repository

```bash
git clone https://github.com/CSOGC-Captsone-2026/Capstone-Fall-2026
cd Capstone-Fall-2026
```

### Development Environment

The project uses a Docker-based development environment to provide consistent tooling and dependencies across team members.

```bash
./startDevContainer.sh
```

Further setup and execution instructions will be added as development progresses.

## Development Team

| Developer | Role |
|---|---|
| Kevin Wang | Software Developer |
| Cody Mattox | Software Developer |
| Gavin Petruzzi | Software Developer |
| Joshua Wright | Software Developer |
| Alexqzander Baker | Software Developer |
| Isaac Camacho | Software Developer |

## Project Sponsor

**Colorado Space Grant Consortium (COSGC)**

## Documentation

Additional project documentation, including system architecture, sensor integration, digital twin development, and meeting notes, is maintained in our team's Confluence workspace.

## Project Status

**Current Phase:** Research, Requirements Gathering & Initial Prototyping

The team is currently defining system requirements, evaluating visualization technologies, researching anomaly detection approaches, and developing the initial software architecture.