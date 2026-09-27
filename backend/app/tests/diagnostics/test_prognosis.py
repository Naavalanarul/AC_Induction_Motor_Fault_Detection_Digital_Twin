"""tests/diagnostics/test_prognosis.py — Tests for threshold time projection and recommendations."""

from __future__ import annotations

from app.diagnostics.prognosis import estimate_time_to_threshold
from app.diagnostics.recommendations import get_recommendation


def test_estimate_time_to_threshold_empty():
    res = estimate_time_to_threshold([])
    assert res["current_severity"] == 0.0
    assert res["slope_per_s"] == 0.0
    assert res["time_to_derate_s"] is None
    assert res["time_to_trip_s"] is None
    assert res["trend"] == "stable"


def test_estimate_time_to_threshold_insufficient_samples():
    history = [(1.0, 0.1), (2.0, 0.12), (3.0, 0.14)]
    res = estimate_time_to_threshold(history)
    assert res["current_severity"] == 0.14
    assert res["time_to_derate_s"] is None


def test_estimate_time_to_threshold_linear_projection():
    # Linear ramp: severity rises by 0.01 per second
    # at t=0, sev=0.1
    # at t=10, sev=0.2
    # derate threshold (0.5) is at 0.5 - 0.2 = 0.3 delta / 0.01 = 30 seconds
    # trip threshold (0.8) is at 0.8 - 0.2 = 0.6 delta / 0.01 = 60 seconds
    history = [(float(t), 0.1 + 0.01 * t) for t in range(11)]
    res = estimate_time_to_threshold(history, derate_thresh=0.5, trip_thresh=0.8)
    assert res["trend"] == "increasing"
    assert abs(res["slope_per_s"] - 0.01) < 1e-4
    assert res["time_to_derate_s"] is not None
    assert abs(res["time_to_derate_s"] - 30.0) < 0.2
    assert res["time_to_trip_s"] is not None
    assert abs(res["time_to_trip_s"] - 60.0) < 0.2


def test_estimate_time_to_threshold_decreasing():
    # Decreasing severity
    history = [(float(t), 0.5 - 0.01 * t) for t in range(11)]
    res = estimate_time_to_threshold(history)
    assert res["trend"] == "decreasing"
    assert res["time_to_derate_s"] is None
    assert res["time_to_trip_s"] is None


def test_recommendations_catalog():
    # Zone A
    rec_a = get_recommendation(1, "healthy", "A", 98.0)
    assert rec_a["urgency"] == "routine"
    assert rec_a["zone"] == "A"

    # Zone B
    rec_b = get_recommendation(1, "bearing_outer", "B", 78.0)
    assert rec_b["urgency"] == "planned"
    assert rec_b["zone"] == "B"

    # Zone C
    rec_c = get_recommendation(1, "broken_rotor_bar", "C", 58.0)
    assert rec_c["urgency"] == "prompt"
    assert "Rotor" in rec_c["title"]
    assert len(rec_c["checklist"]) > 0

    # Zone D
    rec_d = get_recommendation(1, "interturn_short", "D", 32.0)
    assert rec_d["urgency"] == "immediate"
    assert "EMERGENCY" in rec_d["action"]
