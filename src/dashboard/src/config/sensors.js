// Dashboard metadata mirrors generator/Sensors.JSON, the simulation source of truth.
export const sensors = {
    o2: sensor("Oxygen", "environmental", 20.8, "%", 1,
        [20.6, 20.95], { low: 19.5 }),
    co2: sensor("Carbon Dioxide", "environmental", 900, "ppm", 1,
        [600, 1200], { high: 5000 }),
    suit_air_temp: sensor("Suit Air Temperature", "environmental", 23,
        "C", 0.2, [21, 25], { high: 35 }),
    vent_loop_temp: sensor("Vent Loop Temperature", "environmental", 20,
        "C", 0.2, [18, 22], { high: 30 }),
    humidity: sensor("Humidity", "environmental", 42, "%RH", 0.2,
        [35, 50], { high: 85 }),
    pm2_5: sensor("Particulates (PM2.5)", "environmental", 5, "ug/m3",
        0.5, [2, 8], { high: 35 }),
    suit_pressure: sensor("Suit Pressure", "environmental", 4.3, "psi", 1,
        [4.25, 4.35], { low: 3.8 }, false),
    heart_rate: sensor("Heart Rate", "biometric", 72, "bpm", 1,
        [60, 85], { high: 170 }),
    respiration_rate: sensor("Respiration Rate", "biometric", 15,
        "breaths/min", 0.5, [12, 18], { high: 35 }),
    core_temp: sensor("Core Temperature", "biometric", 37, "C", 0.1,
        [36.8, 37.2], { high: 38.5 }),
    skin_temp: sensor("Skin Temperature", "biometric", 33.4, "C", 0.2,
        [32.5, 34], { high: 37 }),
    perspiration: sensor("Perspiration", "biometric", 4.5, "uS", 1,
        [2, 8], { high: 30 }),
    hydration_loss: sensor("Hydration Loss", "biometric", 0.05,
        "% body mass", 0.0167, [0, 0.1], { high: 2 }),
    spo2: sensor("Blood Oxygen (SpO2)", "biometric", 98, "%", 1,
        [96, 99], { low: 92 })
};

function sensor(name, source, value, unit, rate_hz, normal, critical,
    enabled = true) {
    return {
        name,
        source,
        value,
        unit,
        rate_hz,
        normal,
        critical,
        enabled
    };
}
