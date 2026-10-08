"""Classification, calibration, ranking and domain-shift metrics (numpy/scipy/sklearn)."""

from __future__ import annotations

import numpy as np
from scipy.stats import spearmanr, wasserstein_distance
from sklearn.metrics import confusion_matrix, f1_score, roc_auc_score

from app.validation.labels import HEALTHY


def classification(y_true, y_pred, proba, classes: list[str]) -> dict:
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    out = {
        "n": int(len(y_true)),
        "accuracy": float(np.mean(y_true == y_pred)) if len(y_true) else float("nan"),
        "macro_f1": float(f1_score(y_true, y_pred, labels=classes, average="macro", zero_division=0)),
        "per_class_recall": {c: (float(np.mean(y_pred[y_true == c] == c)) if np.any(y_true == c) else float("nan"))
                             for c in classes},
        "confusion": confusion_matrix(y_true, y_pred, labels=classes).tolist(),
        "classes": classes,
    }
    out["auroc_healthy_vs_fault"] = anomaly_auroc(y_true, proba, classes)
    out["ece"] = ece(y_true, proba, classes)
    out["brier"] = brier(y_true, proba, classes)
    return out


def anomaly_auroc(y_true, proba, classes: list[str]) -> float:
    """AUROC of the healthy-vs-faulty decision using 1 - P(healthy) as the anomaly score."""
    y_true = np.asarray(y_true)
    if HEALTHY not in classes:
        return float("nan")
    is_fault = (y_true != HEALTHY).astype(int)
    if is_fault.min() == is_fault.max():
        return float("nan")
    score = 1.0 - np.asarray(proba)[:, classes.index(HEALTHY)]
    return float(roc_auc_score(is_fault, score))


def ece(y_true, proba, classes: list[str], n_bins: int = 15) -> float:
    """Expected calibration error of the top-1 prediction (equal-width confidence bins)."""
    proba = np.asarray(proba)
    if len(proba) == 0:
        return float("nan")
    conf = proba.max(1)
    pred = np.asarray(classes)[proba.argmax(1)]
    correct = (pred == np.asarray(y_true)).astype(float)
    bins = np.linspace(0, 1, n_bins + 1)
    total = 0.0
    for lo, hi in zip(bins[:-1], bins[1:], strict=True):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            total += m.mean() * abs(correct[m].mean() - conf[m].mean())
    return float(total)


def brier(y_true, proba, classes: list[str]) -> float:
    """Multi-class Brier score: mean over samples of sum_k (p_k - 1[y=k])^2 (0 = perfect, 2 = worst)."""
    proba = np.asarray(proba)
    if len(proba) == 0:
        return float("nan")
    onehot = (np.asarray(y_true)[:, None] == np.asarray(classes)[None, :]).astype(float)
    return float(np.mean(np.sum((proba - onehot) ** 2, axis=1)))


GAP_KEYS = ("accuracy", "macro_f1", "auroc_healthy_vs_fault", "ece", "brier")


def gap(sim: dict, real: dict) -> dict:
    """Sim-to-real gap = metric on the simulated test set minus the same metric on the real test set.

    Positive accuracy/F1/AUROC gaps mean the model is worse on real data; for ECE and Brier (lower
    is better) a negative gap means worse on real data.
    """
    return {k: float(sim[k] - real[k]) if (k in sim and k in real) else float("nan") for k in GAP_KEYS}


def spearman_monotonic(scores, levels) -> dict:
    """Spearman rho between a severity score and the true severity level, plus a monotonicity check
    on the per-level mean score (non-decreasing in the level)."""
    scores, levels = np.asarray(scores, float), np.asarray(levels, float)
    if len(set(levels.tolist())) < 2:
        return {"spearman_rho": float("nan"), "p_value": float("nan"), "monotonic": None, "level_means": {}}
    rho, p = spearmanr(scores, levels)
    lv = sorted(set(levels.tolist()))
    means = {float(v): float(np.mean(scores[levels == v])) for v in lv}
    mono = all(means[a] <= means[b] + 1e-12 for a, b in zip(lv[:-1], lv[1:], strict=True))
    return {"spearman_rho": float(rho), "p_value": float(p), "monotonic": bool(mono), "level_means": means}


def _standardise(a, b):
    mu = np.concatenate([a, b]).mean(0)
    sd = np.concatenate([a, b]).std(0)
    sd[sd < 1e-12] = 1.0
    return (a - mu) / sd, (b - mu) / sd


def mmd_rbf(x: np.ndarray, y: np.ndarray, max_n: int = 600, seed: int = 0) -> float:
    """Unbiased squared MMD with an RBF kernel (median-distance bandwidth) on standardised features."""
    rng = np.random.default_rng(seed)
    if len(x) > max_n:
        x = x[rng.choice(len(x), max_n, replace=False)]
    if len(y) > max_n:
        y = y[rng.choice(len(y), max_n, replace=False)]
    if len(x) < 2 or len(y) < 2:
        return float("nan")
    x, y = _standardise(x, y)
    z = np.vstack([x, y])
    d2 = np.sum(z**2, 1)[:, None] + np.sum(z**2, 1)[None, :] - 2 * z @ z.T
    d2 = np.maximum(d2, 0)
    bw = np.median(d2[d2 > 0]) if np.any(d2 > 0) else 1.0
    k = np.exp(-d2 / bw)
    n, m = len(x), len(y)
    kxx, kyy, kxy = k[:n, :n], k[n:, n:], k[:n, n:]
    return float((kxx.sum() - np.trace(kxx)) / (n * (n - 1)) + (kyy.sum() - np.trace(kyy)) / (m * (m - 1))
                 - 2 * kxy.mean())


def wasserstein_per_feature(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """1-D Wasserstein distance per feature, after standardising each feature on the pooled data."""
    xs, ys = _standardise(x, y)
    return np.array([wasserstein_distance(xs[:, j], ys[:, j]) for j in range(x.shape[1])])


def c2st_auc(x: np.ndarray, y: np.ndarray, gx: np.ndarray, gy: np.ndarray, seed: int = 0, k: int = 5) -> float:
    """Classifier two-sample test: grouped-CV AUROC of a logistic regression telling sim from real.
    0.5 = indistinguishable, 1.0 = perfectly separable. Groups keep recordings within one fold."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    from app.validation.splits import grouped_kfold

    z = np.vstack([x, y])
    t = np.r_[np.zeros(len(x)), np.ones(len(y))].astype(int)
    g = np.r_[np.asarray(gx, dtype=object), np.asarray(gy, dtype=object)].astype(str)
    scores = np.full(len(t), np.nan)
    for tr, te in grouped_kfold(g, t.astype(str), k, seed):
        if len(set(t[tr])) < 2:
            continue
        clf = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0))
        clf.fit(z[tr], t[tr])
        scores[te] = clf.predict_proba(z[te])[:, 1]
    m = np.isfinite(scores)
    if m.sum() < 4 or len(set(t[m])) < 2:
        return float("nan")
    return float(roc_auc_score(t[m], scores[m]))
