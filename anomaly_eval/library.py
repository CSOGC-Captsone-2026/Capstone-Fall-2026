"""
The standard scenario set. Each function returns a fresh Scenario.

Times are in minutes from the start of the session. Every session uses the same
45-minute schedule so results are comparable across scenarios.
"""

from .scenarios import Scenario


def _suit(name: str, subject: str = "A1") -> Scenario:
    """Common schedule and sensors. Values are placeholders like sensors.json."""
    return (Scenario(name, subject=subject)
            .phase("rest", 5).phase("eva_task", 20).phase("rest", 5).phase("eva_task", 10).phase("cooldown", 5, 0.2)
            .sensor("co2", base=800, effect=1.6, noise=15, response_s=120, critical_high=5000)
            .sensor("o2", base=20.8, effect=0.985, noise=0.04, response_s=120, critical_low=19.5)
            .sensor("heart_rate", base=72, effect=1.6, noise=2, response_s=45, critical_high=170)
            .sensor("respiration_rate", base=15, effect=1.9, noise=0.8, rate_hz=0.5, response_s=30, critical_high=35)
            .sensor("core_temp", base=37.0, effect=1.02, noise=0.03, rate_hz=0.1, response_s=900, critical_high=38.5))


def nominal_eva():
    """No anomalies: normal rest -> EVA -> rest. A good detector stays quiet."""
    return _suit("nominal EVA, no anomalies")


def co2_scrubber_failure():
    """CO2 climbs steadily to past 5,000 ppm during the first EVA."""
    return _suit("CO2 scrubber failure (ramp)").ramp("co2", at_min=14, minutes=8, to=5750)


def o2_leak():
    """O2 falls below 19.5% over six minutes."""
    return _suit("O2 leak (downward ramp)").ramp("o2", at_min=12, minutes=6, to=17.0)


def heart_rate_spike():
    """Sudden heart-rate jump during the EVA, above the 170 bpm limit."""
    return _suit("heart-rate spike during EVA").spike("heart_rate", at_min=10, minutes=2, delta=60)


def co2_sensor_stuck():
    """CO2 sensor freezes at one value during the EVA (reading looks normal)."""
    return _suit("CO2 sensor stuck").stuck("co2", at_min=18, minutes=5)


def heart_rate_dropout():
    """Heart-rate sensor stops reporting for three minutes."""
    return _suit("heart-rate sensor dropout").dropout("heart_rate", at_min=20, minutes=3)


def heart_rate_high_at_rest():
    """Heart rate at EVA level while the schedule says rest (contextual)."""
    return _suit("heart rate high at rest (contextual)").contextual("heart_rate", at_min=27, minutes=2.5)


ALL = [nominal_eva, co2_scrubber_failure, o2_leak, heart_rate_spike,
       co2_sensor_stuck, heart_rate_dropout, heart_rate_high_at_rest]