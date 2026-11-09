"""Deterministic test framework for anomaly detectors."""

from .interface import Alert, Detector, Reading
from .scenarios import Event, Scenario
from .scoring import CausalityError, EventResult, Result, run, score
from .detectors import RuleBasedDetector, load_detector

__all__ = ["Alert", "Detector", "Reading", "Event", "Scenario",
           "CausalityError", "EventResult", "Result", "run", "score",
           "RuleBasedDetector", "load_detector"]