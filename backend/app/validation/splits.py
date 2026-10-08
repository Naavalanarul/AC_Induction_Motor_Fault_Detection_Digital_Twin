"""Grouped splitting. Windows never leave their recording, and every split asserts disjointness."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np


class LeakageError(AssertionError):
    pass


def assert_disjoint(groups: np.ndarray, *index_sets: np.ndarray) -> None:
    seen: set = set()
    for idx in index_sets:
        g = set(np.asarray(groups)[idx].tolist())
        overlap = seen & g
        if overlap:
            raise LeakageError(f"groups appear in more than one split: {sorted(overlap)[:5]}")
        seen |= g


def group_holdout(groups: np.ndarray, labels: np.ndarray, test_fraction: float, seed: int,
                  val_fraction: float = 0.0) -> tuple[np.ndarray, ...]:
    """Stratified-by-label group holdout: each label's groups are split separately, so every class
    present with >= 2 groups appears in train and test. Returns (train, [val,] test) indices."""
    rng = np.random.default_rng(seed)
    groups = np.asarray(groups)
    labels = np.asarray(labels)
    tr, va, te = [], [], []
    for lab in sorted(set(labels.tolist())):
        g = np.array(sorted(set(groups[labels == lab].tolist())))
        rng.shuffle(g)
        n_te = max(1, int(round(test_fraction * len(g)))) if len(g) > 1 else 0
        n_va = max(1, int(round(val_fraction * len(g)))) if val_fraction > 0 and len(g) - n_te > 1 else 0
        te += g[:n_te].tolist()
        va += g[n_te:n_te + n_va].tolist()
        tr += g[n_te + n_va:].tolist()
    out = [np.where(np.isin(groups, tr))[0]]
    if val_fraction > 0:
        out.append(np.where(np.isin(groups, va))[0])
    out.append(np.where(np.isin(groups, te))[0])
    assert_disjoint(groups, *out)
    return tuple(out)


def leave_one_group_out(groups: np.ndarray) -> Iterator[tuple[np.ndarray, np.ndarray, str]]:
    groups = np.asarray(groups)
    for g in sorted(set(groups.tolist())):
        te = np.where(groups == g)[0]
        tr = np.where(groups != g)[0]
        assert_disjoint(groups, tr, te)
        yield tr, te, str(g)


def grouped_kfold(groups: np.ndarray, labels: np.ndarray, k: int, seed: int) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Label-stratified group k-fold: groups of each label are dealt round-robin into k folds."""
    rng = np.random.default_rng(seed)
    groups, labels = np.asarray(groups), np.asarray(labels)
    fold_of: dict = {}
    for lab in sorted(set(labels.tolist())):
        g = np.array(sorted(set(groups[labels == lab].tolist())))
        rng.shuffle(g)
        for i, gg in enumerate(g):
            fold_of[gg] = i % k
    folds = np.array([fold_of[g] for g in groups])
    for f in range(k):
        te, tr = np.where(folds == f)[0], np.where(folds != f)[0]
        if len(te) and len(tr):
            assert_disjoint(groups, tr, te)
            yield tr, te


def describe_split(groups: np.ndarray, *index_sets: np.ndarray, names=("train", "val", "test")) -> dict:
    return {n: {"windows": int(len(i)), "groups": int(len(set(np.asarray(groups)[i].tolist())))}
            for n, i in zip(names[-len(index_sets):] if len(index_sets) == 2 else names, index_sets, strict=False)}
