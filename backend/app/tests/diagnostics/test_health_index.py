"""tests/diagnostics/test_health_index.py — Tests for Motor Health Index and error codes."""

from __future__ import annotations

from app.diagnostics.health_index import (
    compute_mhi,
    error_code,
    zone_from_mhi,
)
from app.diagnostics.schema import DiagFault, DiagSource, FusedDiagnosis
from app.supervisory.sada import SadaState


def test_zone_classification():
    assert zone_from_mhi(100.0) == "A"
    assert zone_from_mhi(85.0) == "A"
    assert zone_from_mhi(84.9) == "B"
    assert zone_from_mhi(70.0) == "B"
    assert zone_from_mhi(69.9) == "C"
    assert zone_from_mhi(50.0) == "C"
    assert zone_from_mhi(49.9) == "D"
    assert zone_from_mhi(0.0) == "D"


def test_compute_mhi_nominal():
    # Healthy motor in NORMAL state
    diag = FusedDiagnosis(
        t=10.0,
        fault_type=DiagFault.HEALTHY,
        confidence=1.0,
        severity=0.0,
        per_sensor_scores={},
    )
    mhi, zone = compute_mhi(diag, SadaState.NORMAL)
    assert mhi == 100.0
    assert zone == "A"


def test_compute_mhi_with_state_penalties():
    # Watch state: -10 penalty + severity penalty
    mhi_watch, zone_watch = compute_mhi(0.2, SadaState.WATCH)
    # 100 - (0.2 * 60) - 10 = 100 - 12 - 10 = 78.0
    assert mhi_watch == 78.0
    assert zone_watch == "B"

    # Derate state: -25 penalty + severity penalty
    mhi_derate, zone_derate = compute_mhi(0.6, SadaState.DERATE)
    # 100 - (0.6 * 60) - 25 = 100 - 36 - 25 = 39.0
    assert mhi_derate == 39.0
    assert zone_derate == "D"


def test_compute_mhi_trip_suppression():
    """Even if sensors read zero during trip, state penalty forces MHI into Zone D."""
    mhi_trip, zone_trip = compute_mhi(0.0, SadaState.TRIP)
    # 100 - 0 - 60 = 40.0
    assert mhi_trip == 40.0
    assert zone_trip == "D"


def test_compute_mhi_clamping():
    # Extreme severity and trip
    mhi, zone = compute_mhi(1.0, SadaState.TRIP)
    # 100 - 60 - 60 = -20 -> clamped to 0.0
    assert mhi == 0.0
    assert zone == "D"


def test_error_code_formatting():
    # Healthy system
    assert error_code("fused", "healthy", "A") == "SYS-OK-A"
    assert error_code(DiagSource.FUSED, DiagFault.HEALTHY, "A") == "SYS-OK-A"

    # Electrical fault: broken rotor bar
    assert error_code("electrical_residual", "broken_rotor_bar", "D") == "ELEC-BRB-D"
    assert error_code(DiagSource.ELECTRICAL_RESIDUAL, DiagFault.BROKEN_ROTOR_BAR, "D") == "ELEC-BRB-D"

    # Vibration fault: bearing outer race
    assert error_code("vibration", "bearing_outer", "C") == "VIB-BRGO-C"
    assert error_code("fused", "bearing_outer", "C") == "VIB-BRGO-C"

    # Thermal fault: overheating
    assert error_code("thermal", "overheating", "C") == "THM-OVH-C"
    assert error_code("fused", "overheating", "D") == "THM-OVH-D"

    # Supply anomaly
    assert error_code("supply", "supply_anomaly", "B") == "SPLY-SPLY-B"
