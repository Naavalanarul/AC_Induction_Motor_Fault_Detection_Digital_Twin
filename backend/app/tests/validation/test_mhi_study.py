"""tests/validation/test_mhi_study.py — Unit tests for Phase P6 MHI and prognosis evaluation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.validation.mhi_study import (
    evaluate_mhi_sensitivity,
    evaluate_mhi_sweeps,
    evaluate_prognosis,
    generate_degradation_profile,
    run_mhi_and_prognosis_study,
)


def test_mhi_monotonicity_and_step_drops():
    res = evaluate_mhi_sweeps()
    assert "curves" in res
    assert "transition_drops" in res

    drops = res["transition_drops"]
    # WATCH state adds 10 point penalty on top of severity penalty
    assert drops["normal_to_watch_at_0_20"] >= 9.0
    # DERATE state adds 15 point penalty (25 - 10) on top of severity penalty
    assert drops["watch_to_derate_at_0_50"] >= 14.0
    # TRIP state adds 35 point penalty (60 - 25)
    assert drops["derate_to_trip_at_0_80"] >= 20.0


def test_mhi_sensitivity():
    sens = evaluate_mhi_sensitivity()
    assert "sev_plus_20pct" in sens
    assert "state_plus_20pct" in sens
    assert "chan_plus_20pct" in sens

    # Under +/- 20% weight changes, condition zones should retain high stability (> 75%)
    for pert, metrics in sens.items():
        assert metrics["zone_stability_pct"] >= 75.0, f"Zone stability too low for {pert}: {metrics['zone_stability_pct']}"
        assert metrics["mean_abs_mhi_diff"] < 15.0


def test_generate_degradation_profile():
    for prof in ["linear", "exponential", "step_noisy"]:
        times, sevs, t_derate, t_trip = generate_degradation_profile(prof, duration_s=180, dt=1.0, seed=42)
        assert len(times) == 181
        assert len(sevs) == 181
        assert t_derate > 0
        assert t_trip > t_derate


def test_prognosis_evaluation():
    res = evaluate_prognosis(seeds=[0])
    detailed = res["detailed_rows"]
    agg = res["aggregated_table"]

    assert len(detailed) > 0
    assert len(agg) > 0

    # In linear profile, linear regression should extrapolate with minimal error (< 2s)
    linear_60 = [r for r in detailed if r["profile"] == "linear" and r["horizon_samples"] == 60][0]
    assert linear_60["err_derate_abs_s"] is not None
    assert linear_60["err_derate_abs_s"] < 2.0
    assert linear_60["err_trip_abs_s"] is not None
    assert linear_60["err_trip_abs_s"] < 2.0


def test_run_mhi_and_prognosis_smoke(tmp_path: Path):
    run_mhi_and_prognosis_study(out_dir=tmp_path, seeds=[0])

    expected_files = [
        "metrics_mhi.csv",
        "metrics_prognosis.csv",
        "table_mhi.tex",
        "table_prognosis.tex",
        "mhi_curves.png",
        "mhi_curves.pdf",
        "prognosis_error.png",
        "prognosis_error.pdf",
        "summary.json",
        "meta.json",
    ]

    for fname in expected_files:
        p = tmp_path / fname
        assert p.exists(), f"Expected file {fname} not found in {tmp_path}"
        assert p.stat().st_size > 0, f"File {fname} is empty"

    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["mhi_study"]["monotonicity_verified"] is True
    assert "disclaimer" in summary["prognosis_study"]
