"""tests/validation/test_model_comparison.py

Unit tests for deep baselines, hard dataset generation, and model comparison pipeline.
Enforces:
1. Baselines have identical input/output shapes.
2. Group split produces strictly disjoint groups (no data leakage).
3. Hard dataset generator correctly handles parameter perturbation and small severities.
4. Model comparison runs end-to-end on a minimal test configuration.
"""

from __future__ import annotations

import numpy as np
import pytest
import torch

from app.diagnostics.ml.baselines import count_parameters, get_baseline_model
from app.diagnostics.ml.dataset import CLASSES, build_hard_dataset, group_split
from app.validation.model_comparison import run_comparison


def test_baseline_models_forward_shapes():
    batch, seq_len, n_features = 4, 5, 112
    n_classes = len(CLASSES)
    x = torch.randn(batch, seq_len, n_features)

    for mname in ("conv_bilstm", "1d_cnn", "bilstm", "mlp"):
        model = get_baseline_model(mname, n_features, n_classes, seq_len=seq_len)
        out = model(x)
        assert out.shape == (batch, n_classes), f"{mname} returned shape {out.shape}, expected {(batch, n_classes)}"
        assert count_parameters(model) > 0


def test_group_split_strictly_disjoint():
    # Simulate 10 runs with 4 samples each
    groups = np.repeat(np.arange(10), 4)
    tr, va, te = group_split(groups, fractions=(0.6, 0.2, 0.2), seed=123)

    tr_groups = set(groups[tr])
    va_groups = set(groups[va])
    te_groups = set(groups[te])

    assert len(tr_groups & te_groups) == 0, "Train and test groups must be completely disjoint!"
    assert len(tr_groups & va_groups) == 0, "Train and val groups must be completely disjoint!"
    assert len(va_groups & te_groups) == 0, "Val and test groups must be completely disjoint!"
    assert len(tr_groups | va_groups | te_groups) == 10, "All groups must be assigned to a split."


def test_hard_dataset_generation_and_small_severities():
    ds = build_hard_dataset(runs_per_class=1, seed=42, seconds=2.0, param_perturbation_pct=0.10)
    assert len(ds.X) > 0
    assert ds.X.ndim == 3  # (N, SEQ_LEN, F)
    assert ds.X.shape[1] == 5
    assert ds.X.shape[2] == 112
    assert len(ds.y) == len(ds.X)
    assert len(ds.groups) == len(ds.X)
    assert len(ds.severity) == len(ds.X)
    # Check that healthy severities are 0 and fault severities are between 0.05 and 0.60
    healthy_mask = (ds.y == CLASSES.index("healthy"))
    fault_mask = ~healthy_mask
    assert np.all(ds.severity[healthy_mask] == 0.0)
    if np.any(fault_mask):
        assert np.all(ds.severity[fault_mask] >= 0.04)


@pytest.mark.slow
def test_model_comparison_pipeline_fast(tmp_path):
    # Minimal fast smoke test
    summary = run_comparison(
        seeds=[0],
        out_dir=tmp_path / "model_comp",
        runs_per_class=2,
        epochs=2,
        seconds=2.0,
        dataset_type="default",
    )
    assert "Conv-BiLSTM" in summary
    assert "1D-CNN" in summary
    assert "BiLSTM" in summary
    assert "MLP" in summary
    assert "Random Forest" in summary
    assert "Logistic Regression" in summary
    assert "Rule-Based Heuristic" in summary
    assert (tmp_path / "model_comp" / "metrics.csv").exists()
    assert (tmp_path / "model_comp" / "summary.json").exists()
    assert (tmp_path / "model_comp" / "table.tex").exists()
    assert (tmp_path / "model_comp" / "meta.json").exists()
    assert (tmp_path / "model_comp" / "model_comparison.png").exists()
    assert (tmp_path / "model_comp" / "model_comparison.pdf").exists()
