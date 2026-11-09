
export const sensors = {
    o2: {
        name: "Oxygen",
        source: "environmental",
        value: 20.8,
        unit: "%",
        normal: [20.6, 20.95],
        critical: { low: 19.5 },
        rate_hz: 1,
        enabled: true
    },
    co2: {
        name: "Carbon Dioxide",
        source: "environmental",
        value: 0.04,
        unit: "%",
        normal: [0.03, 0.06],
        critical: { high: 0.5 },
        rate_hz: 1,
        enabled: true
    },
    temperature: {
        name: "Ambient Temperature",
        source: "environmental",
        value: 22,
        unit: "°C",
        normal: [18, 27],
        critical: { high: 35 },
        rate_hz: 1,
        enabled: true
    },
    humidity: {
        name: "Humidity",
        source: "environmental",
        value: 45,
        unit: "%",
        normal: [30, 60],
        critical: { high: 80 },
        rate_hz: 1,
        enabled: true
    },
    airflow: {
        name: "Airflow",
        source: "environmental",
        value: 4,
        unit: "L/min",
        normal: [2, 6],
        critical: { low: 1 },
        rate_hz: 1,
        enabled: true
    },
    pressure: {
        name: "Suit Pressure",
        source: "environmental",
        value: 4.3,
        unit: "psi",
        normal: [4.25, 4.35],
        critical: { low: 3.8 },
        rate_hz: 1,
        enabled: false
    },
    heart_rate: {
        name: "Heart Rate",
        source: "biometric",
        value: 72,
        unit: "bpm",
        normal: [60, 85],
        critical: { high: 170 },
        rate_hz: 1,
        enabled: true
    },
    respiration_rate: {
        name: "Respiration Rate",
        source: "biometric",
        value: 15,
        unit: "breaths/min",
        normal: [12, 18],
        critical: { high: 35 },
        rate_hz: 0.5,
        enabled: true
    },
    core_temp: {
        name: "Core Temperature",
        source: "biometric",
        value: 37,
        unit: "°C",
        normal: [36.8, 37.2],
        critical: { high: 38.5 },
        rate_hz: 0.1,
        enabled: true
    },
    skin_temp: {
        name: "Skin Temperature",
        source: "biometric",
        value: 33.4,
        unit: "°C",
        normal: [32.5, 34],
        critical: { high: 37 },
        rate_hz: 0.2,
        enabled: true
    },
    perspiration: {
        name: "Perspiration",
        source: "biometric",
        value: 4.5,
        unit: "µS",
        normal: [2, 8],
        critical: { high: 30 },
        rate_hz: 1,
        enabled: true
    },
    hydration_loss: {
        name: "Hydration Loss",
        source: "biometric",
        value: 0.05,
        unit: "% body mass",
        normal: [0, 0.1],
        critical: { high: 2 },
        rate_hz: 0.0167,
        enabled: true
    },
    spo2: {
        name: "Blood Oxygen (SpO2)",
        source: "biometric",
        value: 98,
        unit: "%",
        normal: [96, 99],
        critical: { low: 92 },
        rate_hz: 1,
        enabled: true
    }
};
