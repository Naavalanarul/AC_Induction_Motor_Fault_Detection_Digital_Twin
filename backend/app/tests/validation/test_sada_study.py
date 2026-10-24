"""tests/validation/test_sada_study.py

Unit tests for SADA supervisory evaluation:
- Verifies naive supervisor triggers immediate trip on raw threshold.
- Verifies SADA smoothing and hysteresis prevent state chatter on noisy hover.
- Fast smoke test of scenario generation and metrics calculation.
"""

from __future__ import annotations

import numpy as np

from app.diagnostics.schema import DiagFault, FusedDiagnosis
from app.supervisory.sada import SadaConfig, SadaState, SadaSupervisor
from app.validation.sada_study import (
    NaiveSupervisor,
    generate_scenarios,
    run_sada_study,
)


def test_naive_vs_sada_transient_spike():
    # 1-sample transient spike to 0.90
    naive = NaiveSupervisor()
    sada = SadaSupervisor(SadaConfig(emergency_severity=0.99))

    d_spike = FusedDiagnosis(t=0.0, fault_type=DiagFault.BEARING_OUTER, severity=0.90, confidence=0.70, per_sensor_scores={})

    out_naive = naive.update(d_spike)
    out_sada = sada.update(d_spike, dt=0.1)

    # Naive immediately trips on raw severity 0.90 >= 0.8
    assert out_naive.state == SadaState.TRIP
    # SADA EMA smooths the single sample spike, so it stays in NORMAL or WATCH and does NOT trip
    assert out_sada.state != SadaState.TRIP


def test_sada_noisy_hover_reduces_chatter():
    scens = generate_scenarios(seed=42)
    hover = scens["noisy_hover"]

    naive = NaiveSupervisor()
    sada = SadaSupervisor(SadaConfig())

    chatter_naive = 0
    chatter_sada = 0

    prev_naive = None
    prev_sada = None

    for t, sev, conf, ok in zip(hover.t_vals, hover.true_severity, hover.confidence, hover.critical_sensors_ok, strict=False):
        d = FusedDiagnosis(t=float(t), fault_type=DiagFault.BEARING_OUTER, severity=float(sev), confidence=float(conf), per_sensor_scores={})
        out_n = naive.update(d, dt=0.1, critical_sensors_ok=bool(ok))
        out_s = sada.update(d, dt=0.1, critical_sensors_ok=bool(ok))

        if prev_naive is not None and out_n.state != prev_naive:
            chatter_naive += 1
        if prev_sada is not None and out_s.state != prev_sada:
            chatter_sada += 1

        prev_naive = out_n.state
        prev_sada = out_s.state

    # Full SADA hysteresis and dwell drastically reduce chatter compared to Naive
    assert chatter_sada < chatter_naive


def test_sada_study_smoke(tmp_path):
    summary = run_sada_study(seeds=[0], out_dir=tmp_path / "sada")
    assert "variants" in summary
    assert "Naive" in summary["variants"]
    assert "Full SADA (Default)" in summary["variants"]
    assert (tmp_path / "sada" / "metrics.csv").exists()
    assert (tmp_path / "sada" / "table_sada_variants.tex").exists()
    assert (tmp_path / "sada" / "table_sada_sensitivity.tex").exists()
    assert (tmp_path / "sada" / "sada_timeline_noisy_hover.png").exists()
    assert (tmp_path / "sada" / "sada_timeline_noisy_hover.pdf").exists()
    assert (tmp_path / "sada" / "sada_sensitivity.png").exists()
    assert (tmp_path / "sada" / "sada_sensitivity.pdf").exists()
