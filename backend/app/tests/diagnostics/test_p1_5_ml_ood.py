"""tests/diagnostics/test_p1_5_ml_ood.py

Verifies P1-5 audit fixes:
1. Out-of-distribution (OOD) feature sequences (non-finite or unphysically large values)
   are flagged with ood=True and mapped to unknown fault.
2. Normal rule-based classification proceeds with ood=False.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from app.diagnostics.features import CHANNELS, N_FEATURES
from app.diagnostics.ml.classifier import MechanicalClassifier
from app.diagnostics.ml.dataset import SEQ_LEN
from app.diagnostics.schema import DiagFault


def test_rule_classifier_flags_unphysical_ood():
    """Unphysically extreme RMS features are flagged as OOD."""
    clf = MechanicalClassifier(artifact=Path("/nonexistent.pt"))
    assert clf.backend == "rules"

    # Extreme noise sequence: RMS >> 20
    extreme_seq = np.ones((SEQ_LEN, len(CHANNELS) * N_FEATURES), dtype=np.float64) * 25.0
    verdict = clf.classify(extreme_seq)

    assert verdict.details.get("ood") is True
    assert verdict.fault_type == DiagFault.UNKNOWN


def test_rule_classifier_flags_non_finite_ood():
    """Non-finite features (NaN / Inf) are flagged as OOD."""
    clf = MechanicalClassifier(artifact=Path("/nonexistent.pt"))
    assert clf.backend == "rules"

    nan_seq = np.zeros((SEQ_LEN, len(CHANNELS) * N_FEATURES), dtype=np.float64)
    nan_seq[-1, 0] = np.nan
    verdict = clf.classify(nan_seq)

    assert verdict.details.get("ood") is True
    assert verdict.fault_type == DiagFault.UNKNOWN


def test_normal_healthy_features_are_not_ood():
    """Typical features for normal operation must have ood=False."""
    clf = MechanicalClassifier(artifact=Path("/nonexistent.pt"))
    normal_seq = np.zeros((SEQ_LEN, len(CHANNELS) * N_FEATURES), dtype=np.float64)
    verdict = clf.classify(normal_seq)

    assert verdict.details.get("ood") is False
    assert verdict.fault_type == DiagFault.HEALTHY
