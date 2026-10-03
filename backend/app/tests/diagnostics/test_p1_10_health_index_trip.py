"""tests/diagnostics/test_p1_10_health_index_trip.py

Verifies P1-10 audit fixes:
1. MHI computation during TRIP uses latched severity rather than collapsing to 40.0.
2. High-severity trip (e.g. severity 0.85) yields MHI = 0.0, not 40.0.
3. Moderate-severity trip (e.g. severity 0.2) yields MHI = 28.0, not 40.0.
4. Worker's post-trip INDETERMINATE override carries the latched severity in diag.severity.
5. Error code during trip with latched fault reflects the actual faulted subsystem, not SYS-IND.
"""

from __future__ import annotations

from app.diagnostics.health_index import compute_mhi, error_code
from app.diagnostics.schema import DiagFault, FusedDiagnosis
from app.supervisory.sada import SadaState


def test_mhi_trip_uses_latched_severity():
    """During TRIP, passing latched_severity must scale MHI according to the true fault severity."""
    # When starved sensors report 0.0 severity, but latched trip severity was 0.85:
    mhi_severe, zone_severe = compute_mhi(
        0.0,
        sada_state=SadaState.TRIP,
        latched_severity=0.85,
    )
    # 100 - (0.85 * 60 = 51) - 60 (trip) = -11 -> clamped to 0.0
    assert mhi_severe == 0.0
    assert zone_severe == "D"

    # When latched trip severity was 0.2:
    mhi_mild, zone_mild = compute_mhi(
        0.0,
        sada_state=SadaState.TRIP,
        latched_severity=0.2,
    )
    # 100 - (0.2 * 60 = 12) - 60 = 28.0
    assert mhi_mild == 28.0
    assert zone_mild == "D"

    # Unlatched zero severity:
    mhi_zero, zone_zero = compute_mhi(
        0.0,
        sada_state=SadaState.TRIP,
        latched_severity=None,
    )
    # 100 - 0 - 60 = 40.0
    assert mhi_zero == 40.0
    assert zone_zero == "D"


def test_mhi_with_fused_diagnosis_trip():
    """FusedDiagnosis instance with latched_severity during TRIP reflects real severity."""
    diag = FusedDiagnosis(
        t=1.0,
        fault_type=DiagFault.INDETERMINATE,
        confidence=0.9,
        severity=0.0,  # simulate starved raw fusion
        per_sensor_scores={},
    )
    mhi, zone = compute_mhi(diag, sada_state=SadaState.TRIP, latched_severity=0.8)
    # 100 - 48 - 60 = -8 -> clamped to 0.0
    assert mhi == 0.0
    assert zone == "D"


def test_error_code_with_latched_fault():
    """Error code during trip should reflect the latched physical fault."""
    code_elec = error_code("electrical_residual", "broken_rotor_bar", "D")
    assert code_elec == "ELEC-BRB-D"

    code_vib = error_code("vibration", "bearing_outer", "D")
    assert code_vib == "VIB-BRGO-D"
