"""Unit tests for the validation package: loaders, label mapping, grouped splits, metrics."""

from __future__ import annotations

import numpy as np
import pytest

from app.tests.validation import stand_in
from app.validation import labels as L
from app.validation import metrics as M
from app.validation import splits as S
from app.validation.loaders import DatasetUnavailable, LoaderOptions, get_loader
from app.validation.loaders.bruinsma import parse_measurement_name
from app.validation.loaders.estogu import parse_name
from app.validation.loaders.liman_c import parse_path
from app.validation.preprocessing import PreprocessingError, estimate_supply_freq, handle_nans, resample


# ---------------------------------------------------------------- label mapping
@pytest.mark.parametrize("table,raw,expected", [
    (L.LIMAN_C, "rotor_bar", "broken_rotor_bar"), (L.LIMAN_C, "Bearing", "bearing"),
    (L.LIMAN_C, "inter-turn", "interturn_short"), (L.ESTOGU, "RB5", "broken_rotor_bar"),
    (L.ESTOGU, "BB", "bearing_ball"), (L.ESTOGU, "BR", "bearing"), (L.ESTOGU, "SW", "interturn_short"),
    (L.BRUINSMA, "loose foot", "out_of_scope"), (L.BRUINSMA, "cavitation", "out_of_scope"),
    (L.BRUINSMA, "Impeller damage", "out_of_scope"), (L.BRUINSMA, "misalignment", "misalignment"),
    (L.USP_BRB, "r3b", "broken_rotor_bar"), (L.USP_BRB, "rs", "healthy"),
])
def test_label_mapping(table, raw, expected):
    assert L.map_label(table, raw, "x") == expected


def test_unknown_label_is_never_guessed():
    with pytest.raises(KeyError, match="never guessed"):
        L.map_label(L.LIMAN_C, "mystery", "liman_c")


def test_coarse_collapses_bearing_labels():
    assert {L.coarse(x) for x in ("bearing_inner", "bearing_outer", "bearing_ball")} == {"bearing"}
    assert L.coarse("broken_rotor_bar") == "broken_rotor_bar"


# ---------------------------------------------------------------- name parsing
def test_bruinsma_name_parsing():
    m = parse_measurement_name("VIB_M4_1500_bearing_S2")
    assert (m.method, m.motor, m.speed_rpm, m.severity) == ("vibration", "motor4", 1500.0, 2.0)
    with pytest.raises(ValueError):
        parse_measurement_name("something_unparseable")


def test_liman_and_estogu_parsing():
    from pathlib import Path

    assert parse_path(Path("rotor_bar/load_60/rec3_b.csv")) == ("rotorbar", 60.0, "b", "rotor_bar/load_60/rec3")
    assert parse_name("RB3100455") == ("RB3", 100.0, 45.5)
    assert parse_name("N_050_50") == ("N", 50.0, 50.0)


# ---------------------------------------------------------------- loaders on stand-in files
def test_liman_loader_keeps_nan_and_groups_by_motor(tmp_path):
    stand_in.write_liman_c(tmp_path, per_class=2)
    recs = get_loader("liman_c", tmp_path).load()
    assert len(recs) == 4 and {r.label for r in recs} == {"healthy", "broken_rotor_bar"}
    assert all(set(r.signals) == {"ia", "ib", "ic"} for r in recs)
    # one empty cell per class in the stand-in: kept as NaN, row count unchanged
    assert sum(int(np.isnan(r.signals["ia"]).sum()) for r in recs) == 2
    assert all(len(r.signals["ia"]) == 16_384 for r in recs)
    assert {r.motor_group for r in recs} == {"liman_healthy", "liman_rotorbar"}
    assert all(abs(r.fs - 4096.0) < 1 for r in recs)


def test_bruinsma_loader_pairs_vibration_and_current(tmp_path):
    stand_in.write_bruinsma(tmp_path, {"healthy": 1, "brb": 1}, seconds=2.0)
    recs = get_loader("bruinsma", tmp_path).load()
    assert len(recs) == 2
    r = next(x for x in recs if x.label == "broken_rotor_bar")
    assert {"ia", "va", "vib_y"} <= set(r.signals) and r.fs == 20_000.0 and r.motor_group == "motor2"
    assert r.meta["synchronous"] is False


def test_bruinsma_unparseable_names_require_manifest(tmp_path):
    d = tmp_path / "weird folder"
    d.mkdir()
    (d / "x_1.csv").write_text("1\n2\n")
    with pytest.raises(DatasetUnavailable, match="--manifest"):
        get_loader("bruinsma", tmp_path).load()


def test_estogu_loader_reads_columns_and_frequency(tmp_path):
    stand_in.write_estogu(tmp_path)
    recs = get_loader("estogu", tmp_path).load()
    assert {r.label for r in recs} == {"healthy", "broken_rotor_bar", "interturn_short"}
    assert all(r.supply_freq_hz == 45.5 and abs(r.fs - 5000.0) < 1 for r in recs)
    assert next(r for r in recs if r.raw_label == "RB3").severity == 3.0


def test_estogu_missing_columns_is_reported(tmp_path):
    d = tmp_path / "With_Driver" / "N"
    d.mkdir(parents=True)
    (d / "N100500.csv").write_text("a,b\n1,2\n3,4\n")
    with pytest.raises(DatasetUnavailable, match="column-map"):
        get_loader("estogu", tmp_path).load()


def test_usp_loader_walks_mat_structs(tmp_path):
    stand_in.write_usp(tmp_path)
    recs = get_loader("usp_brb", tmp_path).load()
    assert len(recs) == 4
    assert {r.severity for r in recs} == {0.0, 2.0}
    r = recs[0]
    assert r.load_pct == 50.0 and r.fs == 50_000.0 and r.fs_of("vib_y") == 7_600.0


def test_missing_dataset_raises(tmp_path):
    for name in ("bruinsma", "liman_c", "estogu", "usp_brb"):
        with pytest.raises(DatasetUnavailable):
            get_loader(name, tmp_path / "absent").load()


def test_max_records_caps(tmp_path):
    stand_in.write_liman_c(tmp_path, per_class=2, with_nan=False)
    assert len(get_loader("liman_c", tmp_path, LoaderOptions(max_records=3)).load()) == 3


# ---------------------------------------------------------------- pre-processing
def test_supply_frequency_and_resampling():
    fs = 5000.0
    t = np.arange(int(4 * fs)) / fs
    for f0 in (45.5, 50.0, 60.0):
        assert estimate_supply_freq(np.sin(2 * np.pi * f0 * t), fs) == pytest.approx(f0, abs=0.05)
    assert len(resample(np.zeros(20_000), 20_000, 5000)) == 5000


def test_nan_policies():
    x = np.arange(100.0)
    x[5] = np.nan
    y, n = handle_nans(x, "interpolate")
    assert n == 1 and y[5] == 5.0
    with pytest.raises(PreprocessingError):
        handle_nans(x, "drop")
    x[:50] = np.nan
    with pytest.raises(PreprocessingError):
        handle_nans(x, "interpolate")


# ---------------------------------------------------------------- grouped splitting
def test_group_holdout_has_no_group_in_two_splits():
    groups = np.repeat([f"g{i}" for i in range(30)], 5)
    labels = np.repeat(["a", "b", "c"] * 10, 5)
    for seed in range(5):
        tr, va, te = S.group_holdout(groups, labels, 0.3, seed, val_fraction=0.2)
        sets = [set(groups[i]) for i in (tr, va, te)]
        assert not (sets[0] & sets[1] or sets[0] & sets[2] or sets[1] & sets[2])
        assert set(labels[te]) == {"a", "b", "c"}


def test_kfold_and_logo_are_disjoint():
    groups = np.repeat([f"g{i}" for i in range(12)], 3)
    labels = np.repeat(["a", "b"] * 6, 3)
    for tr, te in S.grouped_kfold(groups, labels, 4, 0):
        assert not set(groups[tr]) & set(groups[te])
    for tr, te, held in S.leave_one_group_out(groups):
        assert set(groups[te]) == {held} and held not in set(groups[tr])


def test_assert_disjoint_detects_leakage():
    groups = np.array(["a", "a", "b"])
    with pytest.raises(S.LeakageError):
        S.assert_disjoint(groups, np.array([0]), np.array([1, 2]))


# ---------------------------------------------------------------- metrics
def test_gap_metric_sign_convention():
    sim = {"accuracy": 0.95, "macro_f1": 0.9, "auroc_healthy_vs_fault": 1.0, "ece": 0.02, "brier": 0.1}
    real = {"accuracy": 0.55, "macro_f1": 0.4, "auroc_healthy_vs_fault": 0.7, "ece": 0.3, "brier": 0.8}
    g = M.gap(sim, real)
    assert g["accuracy"] == pytest.approx(0.40) and g["macro_f1"] == pytest.approx(0.5)
    assert g["ece"] == pytest.approx(-0.28)  # lower-is-better metrics go negative when real is worse


def test_calibration_and_classification_metrics():
    classes = ["healthy", "bearing"]
    y = np.array(["healthy", "bearing", "bearing", "healthy"], dtype=object)
    proba = np.array([[0.9, 0.1], [0.2, 0.8], [0.6, 0.4], [1.0, 0.0]])
    pred = np.array(classes, dtype=object)[proba.argmax(1)]
    m = M.classification(y, pred, proba, classes)
    assert m["accuracy"] == 0.75 and m["per_class_recall"]["bearing"] == 0.5
    assert m["auroc_healthy_vs_fault"] == 1.0
    assert M.brier(y, proba, classes) == pytest.approx(np.mean([0.02, 0.08, 0.72, 0.0]))
    assert M.ece(np.array(["healthy"]), np.array([[0.8, 0.2]]), classes) == pytest.approx(0.2)


def test_spearman_monotonic_and_shift_metrics():
    r = M.spearman_monotonic([0.1, 0.2, 0.25, 0.5, 0.6], [0, 1, 1, 2, 3])
    assert r["spearman_rho"] > 0.9 and r["monotonic"] is True
    assert M.spearman_monotonic([0.5, 0.1], [0, 1])["monotonic"] is False
    rng = np.random.default_rng(0)
    a, b = rng.normal(size=(200, 4)), rng.normal(size=(200, 4))
    c = rng.normal(3.0, 1.0, size=(200, 4))
    assert M.mmd_rbf(a, b) < 0.02 < M.mmd_rbf(a, c)
    ga, gb = np.repeat(np.arange(20), 10), np.repeat(np.arange(20, 40), 10)
    assert M.c2st_auc(a, b, ga, gb) < 0.7 and M.c2st_auc(a, c, ga, gb) > 0.95
    w = M.wasserstein_per_feature(a, c)
    assert w.shape == (4,) and np.all(w > 0.5)
