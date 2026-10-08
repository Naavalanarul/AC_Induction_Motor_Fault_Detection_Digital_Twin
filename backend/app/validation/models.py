"""Window-level classifiers with recording-level aggregation. Normalisation is part of the fitted
pipeline, so it is always learned on the training split only."""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def make_model(kind: str, seed: int):
    if kind == "logreg":
        clf = LogisticRegression(max_iter=3000, C=1.0)
    elif kind == "rf":
        clf = RandomForestClassifier(n_estimators=200, min_samples_leaf=2, random_state=seed, n_jobs=1)
    elif kind == "mlp":
        clf = MLPClassifier(hidden_layer_sizes=(64, 32), alpha=1e-3, max_iter=300, random_state=seed,
                            early_stopping=False, warm_start=True)
    else:
        raise ValueError(f"unknown model {kind}")
    return Pipeline([("scale", StandardScaler()), ("clf", clf)])


@dataclass
class Fitted:
    model: Pipeline
    classes: list[str]

    def window_proba(self, X: np.ndarray) -> np.ndarray:
        """Probabilities over self.classes (classes unseen in training get 0)."""
        p = self.model.predict_proba(np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0))
        out = np.zeros((len(X), len(self.classes)))
        for j, c in enumerate(self.model.classes_):
            out[:, self.classes.index(c)] = p[:, j]
        return out

    def record_proba(self, X: np.ndarray, groups: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Mean window probability per recording. Returns (unique groups, proba)."""
        p = self.window_proba(X)
        ug = np.array(sorted(set(np.asarray(groups).tolist())), dtype=object)
        return ug, np.vstack([p[np.asarray(groups) == g].mean(0) for g in ug])


def fit(kind: str, X: np.ndarray, y: np.ndarray, classes: list[str], seed: int) -> Fitted:
    m = make_model(kind, seed)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        m.fit(np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0), y)
    return Fitted(m, classes)


def fine_tune(base: Fitted, X: np.ndarray, y: np.ndarray, epochs: int = 50) -> Fitted:
    """Continue training a sim-pretrained MLP on a few real recordings (scaler stays sim-fitted)."""
    import copy

    m = copy.deepcopy(base.model)
    scaler, clf = m.named_steps["scale"], m.named_steps["clf"]
    Xs = scaler.transform(np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        for _ in range(epochs):
            clf.partial_fit(Xs, y)
    return Fitted(m, base.classes)
