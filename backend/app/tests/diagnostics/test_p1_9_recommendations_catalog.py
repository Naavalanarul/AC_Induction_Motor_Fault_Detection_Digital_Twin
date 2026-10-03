"""tests/diagnostics/test_p1_9_recommendations_catalog.py

Verifies P1-9 audit fixes:
1. Complete recommendation catalog coverage for all physical faults x zones.
2. Zone A with active fault produces early detection alert, not 'Normal Operation'.
3. Zone A with healthy produces 'Normal Operation'.
4. Zone B with active fault identifies fault; Zone B with non-fault never says '(Healthy)'.
5. Zone C/D fallback never produces 'CRITICAL: Healthy' or 'Warning: Healthy'.
6. Zone case insensitivity ('a', 'b', 'c', 'd').
"""

from __future__ import annotations

import pytest

from app.diagnostics.recommendations import (
    RECOMMENDATIONS_CATALOG,
    get_recommendation,
)
from app.diagnostics.schema import DiagFault

PHYSICAL_FAULTS = [
    DiagFault.BROKEN_ROTOR_BAR,
    DiagFault.INTERTURN_SHORT,
    DiagFault.ECCENTRICITY,
    DiagFault.BEARING_INNER,
    DiagFault.BEARING_OUTER,
    DiagFault.BEARING_BALL,
    DiagFault.UNBALANCE,
    DiagFault.MISALIGNMENT,
    DiagFault.OVERHEATING,
    DiagFault.SUPPLY_ANOMALY,
    DiagFault.VOLTAGE_SAG,
    DiagFault.OVERLOAD,
    DiagFault.OVERCURRENT,
    DiagFault.STALL,
    DiagFault.PHASE_LOSS,
]


@pytest.mark.parametrize("fault", PHYSICAL_FAULTS)
def test_all_physical_faults_have_catalog_entries(fault: DiagFault):
    """Every physical fault must have explicit C and D zone entries in RECOMMENDATIONS_CATALOG."""
    assert fault.value in RECOMMENDATIONS_CATALOG, f"Missing catalog entry for {fault.value}"
    cat = RECOMMENDATIONS_CATALOG[fault.value]
    for z in ("C", "D"):
        assert z in cat, f"Missing zone {z} for {fault.value}"
        entry = cat[z]
        assert entry["title"], f"Missing title for {fault.value} zone {z}"
        assert entry["action"], f"Missing action for {fault.value} zone {z}"
        assert len(entry["checklist"]) >= 2, f"Checklist too short for {fault.value} zone {z}"
        assert entry["urgency"] in ("prompt", "immediate")


def test_zone_a_with_active_fault_shows_early_detection():
    """When an active fault is detected at low severity (MHI in Zone A), recommendation must flag it."""
    rec = get_recommendation(1, DiagFault.BROKEN_ROTOR_BAR, "A", 91.5)
    assert "Broken Rotor Bar" in rec["title"]
    assert "Early Detection" in rec["title"]
    assert "Normal Operation" not in rec["title"]
    assert "broken rotor bar" in rec["action"].lower()


def test_zone_a_healthy_shows_normal_operation():
    """Zone A with healthy motor returns standard Normal Operation."""
    rec = get_recommendation(1, DiagFault.HEALTHY, "A", 98.0)
    assert rec["title"] == "Normal Operation"
    assert rec["urgency"] == "routine"


def test_zone_b_healthy_or_indeterminate_no_misleading_title():
    """Zone B without real fault never formats title as 'Minor Degradation (Healthy)'."""
    rec_healthy = get_recommendation(1, DiagFault.HEALTHY, "B", 78.0)
    assert "Healthy" not in rec_healthy["title"]
    assert rec_healthy["title"] == "Minor Degradation Detected"

    rec_ind = get_recommendation(1, DiagFault.INDETERMINATE, "B", 72.0)
    assert "Indeterminate" not in rec_ind["title"]
    assert rec_ind["title"] == "Minor Degradation Detected"


def test_zone_b_with_active_fault_names_fault():
    """Zone B with active fault identifies the fault clearly."""
    rec = get_recommendation(1, DiagFault.MISALIGNMENT, "B", 75.0)
    assert "Misalignment" in rec["title"]
    assert "misalignment" in rec["action"].lower()


def test_fallback_never_produces_critical_healthy():
    """Zone C or D without real fault never formats title as 'CRITICAL: Healthy'."""
    rec_d = get_recommendation(1, DiagFault.HEALTHY, "D", 35.0)
    assert "Healthy" not in rec_d["title"]
    assert rec_d["title"] == "CRITICAL: Motor Condition Degraded"
    assert "healthy" not in rec_d["action"].lower()

    rec_c = get_recommendation(1, DiagFault.UNKNOWN, "C", 55.0)
    assert "Unknown" not in rec_c["title"]
    assert rec_c["title"] == "Warning: Motor Condition Degraded"


def test_case_insensitive_zone():
    """Lowercase zone letters are normalized properly."""
    rec_lower_a = get_recommendation(1, DiagFault.HEALTHY, "a", 95.0)
    assert rec_lower_a["zone"] == "A"
    assert rec_lower_a["title"] == "Normal Operation"

    rec_lower_d = get_recommendation(1, DiagFault.OVERHEATING, "d", 30.0)
    assert rec_lower_d["zone"] == "D"
    assert "Thermal Runaway" in rec_lower_d["title"]
