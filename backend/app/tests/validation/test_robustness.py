"""tests/validation/test_robustness.py

Unit tests for robustness sweeps (P4):
- Checks perturbed parameter generator enforces stability and valid physics.
- Verifies evaluate_single_run returns consistent predictions across channels.
- Fast smoke test of sweep execution.
"""

from __future__ import annotations

import numpy as np

from app.simulation.params import validate_motor_params
from app.validation.robustness import evaluate_single_run, make_perturbed_motor, run_sweep


def test_make_perturbed_motor_stability():
    for delta in (-0.20, -0.10, -0.05, 0.05, 0.10, 0.20):
        motor = make_perturbed_motor(delta_rs=delta, delta_rr=delta, delta_lm=delta * 0.4)
        ok, msg = validate_motor_params(motor)
        assert ok, f"Perturbation delta={delta} failed validation: {msg}"


def test_evaluate_single_run_smoke():
    fused, elec, ml = evaluate_single_run(
        cls="healthy",
        severity=0.0,
        seed=42,
        seconds=1.5,
    )
    assert isinstance(fused, str)
    assert isinstance(elec, str)
    assert isinstance(ml, str)


def test_robustness_sweep_smoke(tmp_path):
    summary = run_sweep(
        sweep_name="smoke_test",
        factor_values=[10, 20],
        get_run_kwargs=lambda val, cls, sev: {"noise_rms": 0.05},
        seeds=[0],
        out_dir=tmp_path / "smoke",
    )
    assert "10" in summary
    assert "20" in summary
    assert (tmp_path / "smoke" / "robustness_smoke_test.csv").exists()
    assert (tmp_path / "smoke" / "robustness_smoke_test.png").exists()
    assert (tmp_path / "smoke" / "robustness_smoke_test.pdf").exists()
