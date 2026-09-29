"""signal_processing/__init__.py

Signal Processing Package for AC Induction Motor Fault Detection.

Contains:
- MCSA Pipeline: Stator current FFT, PSD (Welch), Hann/Flat-top windowing
- Vibration Analysis: Bearing defect frequencies, envelope detection
- Feature Extraction: RMS, Kurtosis, Crest Factor, THD, Zero-crossing
"""

from signal_processing.mcsa_pipeline import MCSAAnalyzer, MCSAResult, PeakMarker
from signal_processing.vibration_analysis import VibrationAnalyzer, BearingFrequencies
from signal_processing.feature_extraction import FeatureExtractor, SignalFeatures

__all__ = [
    "MCSAAnalyzer",
    "MCSAResult",
    "PeakMarker",
    "VibrationAnalyzer",
    "BearingFrequencies",
    "FeatureExtractor",
    "SignalFeatures",
]