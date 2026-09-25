"""Phase 5: features, leak-safe split, frozen validation set, graceful degradation."""

from pathlib import Path

import numpy as np
import pytest

from app.diagnostics.features import CHANNELS, N_FEATURES
from app.diagnostics.ml.classifier import ARTIFACT, MechanicalClassifier
from app.diagnostics.ml.dataset import CLASSES, SEQ_LEN, build_dataset, group_split, simulate_run, to_sequences

torch = pytest.importorskip("torch")


def test_feature_vector_shape():
    feats = simulate_run("healthy", 0.0, load=5.0, noise=0.05, seed=1, seconds=1.2)
    assert feats.shape[1] == len(CHANNELS) * N_FEATURES
    assert np.all(np.isfinite(feats))


def test_group_split_has_no_run_leakage():
    groups = np.repeat(np.arange(20), 7)
    tr, va, te = group_split(groups, seed=3)
    sets = [set(groups[x]) for x in (tr, va, te)]
    assert not (sets[0] & sets[1]) and not (sets[0] & sets[2]) and not (sets[1] & sets[2])
    assert len(tr) + len(va) + len(te) == len(groups)


@pytest.mark.slow
def test_frozen_validation_set_accuracy():
    """Regression guard: a fixed-seed held-out set (seed differs from training) must stay >= 90 %."""
    if not ARTIFACT.exists():
        pytest.skip("no trained artifact")
    clf = MechanicalClassifier()
    assert clf.backend == "conv_bilstm", clf.load_error
    data = build_dataset(runs_per_class=2, seed=777, seconds=2.0)
    preds = [CLASSES.index(clf.classify(x).fault_type.value) for x in data.X]
    acc = float(np.mean(np.array(preds) == data.y))
    assert acc >= 0.9, acc


def test_missing_artifact_falls_back_to_rules():
    clf = MechanicalClassifier(artifact=Path("/nonexistent.pt"))
    assert clf.backend == "rules" and clf.load_error
    seq = to_sequences(simulate_run("bearing_outer", 0.7, 5.0, 0.05, seed=2, seconds=1.6))[-1]
    v = clf.classify(seq)
    assert v.fault_type.value == "bearing_outer"
    assert v.details["backend"] == "rules"


def test_inference_error_falls_back_to_rules():
    clf = MechanicalClassifier()
    if clf.model is None:
        pytest.skip("no ML backend")

    def boom(*_):
        raise RuntimeError("boom")

    clf.model.forward = boom
    seq = np.zeros((SEQ_LEN, len(CHANNELS) * N_FEATURES), dtype=np.float32)
    assert clf.classify(seq).details["backend"] == "rules"
