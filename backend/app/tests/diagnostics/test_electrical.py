"""Phase 4: residual FD/FL indices cross thresholds on injected faults, stay below when healthy."""

import pytest

from app.diagnostics.electrical import FD_THRESHOLD, FL_THRESHOLD
from app.diagnostics.schema import DiagFault, DiagSource


def elec(diag):
    return diag.per_sensor_scores[DiagSource.ELECTRICAL_RESIDUAL.value]


def test_healthy_residual_below_threshold(pipeline):
    diag, *_ = pipeline()
    e = elec(diag)
    assert e["fault_type"] == "healthy"
    assert e["details"]["FD"] < FD_THRESHOLD


@pytest.mark.parametrize("fault,sev,params,expected", [
    ("broken_rotor_bar", 0.375, {"count": 3}, DiagFault.BROKEN_ROTOR_BAR),
    ("interturn_short", 0.3, {"phase": "b"}, DiagFault.INTERTURN_SHORT),
    ("eccentricity", 0.5, {"type": "dynamic"}, DiagFault.ECCENTRICITY),
])
def test_electrical_faults_detected_and_classified(pipeline, fault, sev, params, expected):
    diag, *_ = pipeline(fault, sev, params)
    e = elec(diag)
    assert e["details"]["FD"] > FD_THRESHOLD
    assert e["fault_type"] == expected.value


def test_interturn_short_is_localized_to_faulted_phase(pipeline):
    diag, *_ = pipeline("interturn_short", 0.4, {"phase": "c"})
    d = elec(diag)["details"]
    assert d["FL_phase"] == "c"
    assert max(d["FL"]) > FL_THRESHOLD


def test_supply_anomaly_does_not_trigger_electrical_residual(pipeline):
    diag, *_ = pipeline("voltage_anomaly", 0.8, {"type": "imbalance"})
    assert elec(diag)["fault_type"] == "healthy"
    assert diag.fault_type == DiagFault.SUPPLY_ANOMALY
