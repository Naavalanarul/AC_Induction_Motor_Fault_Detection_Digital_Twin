"""tests/diagnostics/test_p1_3_eccentricity_brb_calibration.py

Verifies P1-3 audit fixes:
1. Strict monotonicity of BRB sideband magnitude -> severity.
2. Single source of truth for BRB bar count vs severity mapping.
3. Strict monotonicity of eccentricity sideband magnitude -> severity.
4. Monotone airgap depth modulation across static, dynamic, and mixed eccentricity.
5. Monotone electrical residual FD mapping to discrete and continuous severity.
"""

from __future__ import annotations

import numpy as np

from app.diagnostics.calibration import (
    brb_count_to_severity,
    brb_db_to_severity,
    brb_severity_to_count,
    eccentricity_db_to_severity,
    residual_fd_to_severity,
)
from app.diagnostics.fault_classifier import FaultClassifier, FaultSeverity
from app.signal_processing.mcsa_pipeline import MCSAResult, PeakMarker
from app.simulation.faults import (
    FaultState as SimFaultState,
)
from app.simulation.faults import (
    inject_broken_rotor_bar,
    inject_eccentricity,
)


def test_brb_sideband_db_monotonicity():
    """Increasing BRB sideband magnitude produces strictly monotonically increasing severity."""
    db_values = np.linspace(-50.0, -15.0, 36)
    severities = [brb_db_to_severity(float(db)) for db in db_values]

    # Monotonically non-decreasing everywhere
    for i in range(len(severities) - 1):
        assert severities[i] <= severities[i + 1]

    # Strictly increasing in active range (-45 to -20 dBc)
    active_dbs = [db for db in db_values if -45.0 < db < -20.0]
    active_sevs = [brb_db_to_severity(float(db)) for db in active_dbs]
    for i in range(len(active_sevs) - 1):
        assert active_sevs[i] < active_sevs[i + 1]

    assert brb_db_to_severity(-50.0) == 0.0
    assert brb_db_to_severity(-45.0) == 0.0
    assert brb_db_to_severity(-20.0) == 1.0
    assert brb_db_to_severity(-15.0) == 1.0


def test_brb_bar_count_single_source_of_truth():
    """Bar count mapping to severity and physical resistance delta is strictly monotonic."""
    bar_counts = list(range(1, 9))
    sevs = [brb_count_to_severity(c) for c in bar_counts]

    # Strictly increasing
    for i in range(len(sevs) - 1):
        assert sevs[i] < sevs[i + 1]

    # Exactly maps 8 bars -> 1.0, 4 bars -> 0.5 (derate)
    assert sevs[3] == 0.5
    assert sevs[-1] == 1.0

    # Invertibility check
    for c in bar_counts:
        assert brb_severity_to_count(brb_count_to_severity(c)) == c

    # Physical rotor resistance asymmetry delta strictly increases in simulation FaultState
    deltas = []
    for c in bar_counts:
        st = SimFaultState()
        inject_broken_rotor_bar(st, count=c)
        deltas.append(st.brb_delta)

    for i in range(len(deltas) - 1):
        assert deltas[i] < deltas[i + 1]


def test_eccentricity_sideband_db_monotonicity():
    """Increasing eccentricity sideband power produces strictly monotonically increasing severity."""
    db_values = np.linspace(-50.0, -15.0, 36)
    severities = [eccentricity_db_to_severity(float(db)) for db in db_values]

    for i in range(len(severities) - 1):
        assert severities[i] <= severities[i + 1]

    active_dbs = [db for db in db_values if -45.0 < db < -20.0]
    active_sevs = [eccentricity_db_to_severity(float(db)) for db in active_dbs]
    for i in range(len(active_sevs) - 1):
        assert active_sevs[i] < active_sevs[i + 1]

    assert eccentricity_db_to_severity(-50.0) == 0.0
    assert eccentricity_db_to_severity(-45.0) == 0.0
    assert eccentricity_db_to_severity(-20.0) == 1.0


def test_eccentricity_depth_modulation_static_dynamic_mixed():
    """Static, dynamic, and mixed eccentricity each modulate air-gap depth monotonically with severity."""
    sevs = [0.1, 0.25, 0.5, 0.75, 1.0]

    for kind in ("static", "dynamic", "mixed"):
        eff_depths = []
        for s in sevs:
            st = SimFaultState()
            inject_eccentricity(st, type=kind, severity=s)
            dyn, stat = st.eccentricity
            eff = dyn + stat  # Total air-gap modulation depth
            eff_depths.append(eff)
            if kind == "static":
                assert dyn == 0.0 and stat > 0.0
            elif kind == "dynamic":
                assert dyn > 0.0 and stat == 0.0
            elif kind == "mixed":
                assert dyn > 0.0 and stat > 0.0

        for i in range(len(eff_depths) - 1):
            assert eff_depths[i] < eff_depths[i + 1]


def test_classifier_mcsa_severity_tiers_are_monotonic():
    """FaultClassifier assigns monotonically increasing FaultSeverity tiers for rising MCSA sidebands."""
    classifier = FaultClassifier()
    fft_freqs = np.linspace(0, 500, 1000)
    fft_mag = np.ones_like(fft_freqs) * 1e-5

    # Test BRB across sideband levels: -42 (low), -36 (moderate), -29 (high), -22 (critical)
    test_dbs = [-42.0, -36.0, -29.0, -22.0]
    expected_order = [FaultSeverity.LOW, FaultSeverity.MODERATE, FaultSeverity.HIGH, FaultSeverity.CRITICAL]
    tier_ranks = {FaultSeverity.LOW: 1, FaultSeverity.MODERATE: 2, FaultSeverity.HIGH: 3, FaultSeverity.CRITICAL: 4}

    ranks = []
    severities = []
    for db in test_dbs:
        mcsa = MCSAResult(
            fs=5000.0,
            fundamental_freq=50.0,
            fundamental_mag_db=20.0,
            slip=0.02,
            rotor_freq_hz=25.0,
            window="hann",
            freqs=fft_freqs,
            psd_db=fft_mag,
            fft_freqs=fft_freqs,
            fft_mag_db=fft_mag,
            brb_peaks=[PeakMarker(freq_hz=48.0, magnitude_db=db, label="BRB k=1", sideband_type="lower")],
            worst_brb_sideband_db=db,
            brb_fault_detected=True,
        )
        diags = classifier.classify(mcsa_result=mcsa, vibration_result=None, thermal_state=None, electrical_residual=None)
        brb = next(d for d in diags if d.fault_type.value == "broken_rotor_bar")
        ranks.append(tier_ranks[brb.severity])
        severities.append(brb.severity)

    for i in range(len(ranks) - 1):
        assert ranks[i] <= ranks[i + 1]
    assert ranks == [1, 2, 3, 4]
    assert severities == expected_order


def test_electrical_residual_severity_monotonicity():
    """Residual FD index maps monotonically to continuous severity and discrete diagnosis tier."""
    classifier = FaultClassifier()
    fds = [0.010, 0.025, 0.055, 0.095, 0.140]

    # 1. Check calibration function
    scores = [residual_fd_to_severity(fd) for fd in fds]
    for i in range(len(scores) - 1):
        assert scores[i] <= scores[i + 1]

    # 2. Check classifier output for BRB in electrical residual
    tier_ranks = {FaultSeverity.LOW: 1, FaultSeverity.MODERATE: 2, FaultSeverity.HIGH: 3, FaultSeverity.CRITICAL: 4}
    ranks = []
    for fd in fds[1:]:  # skip fd below detection threshold
        res_dict = {
            "FD": fd,
            "FL": [1.0, 1.0, 1.0],
            "FL_phase": "a",
            "energy_share": {"brb": 0.6, "fund": 0.2, "neg": 0.1, "ecc_dyn": 0.1},
            "slip": 0.02,
        }
        diags = classifier.classify(mcsa_result=None, vibration_result=None, thermal_state=None, electrical_residual=res_dict)
        brb = next(d for d in diags if d.fault_type.value == "broken_rotor_bar")
        ranks.append(tier_ranks[brb.severity])

    for i in range(len(ranks) - 1):
        assert ranks[i] <= ranks[i + 1]
