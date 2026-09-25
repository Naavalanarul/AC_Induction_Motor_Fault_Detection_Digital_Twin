"""diagnostics/ml/dataset.py

Simulated training data for the vibration/acoustic classifier.

Every *run* is one simulation with one fault class, a random severity, load and
noise level. Samples are sequences of consecutive window-feature vectors. The run
id is kept as the group label so train/val/test can be split by run, never by
frame (frames from one run are strongly correlated and would leak).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.diagnostics.features import HOP_S, WINDOW_S, window_features
from app.simulation import faults as F
from app.simulation.twin_state import MotorSimulator

CLASSES = ["healthy", "bearing_inner", "bearing_outer", "bearing_ball", "unbalance", "misalignment"]
SEQ_LEN = 5


@dataclass
class Dataset:
    X: np.ndarray        # (N, SEQ_LEN, F)
    y: np.ndarray        # (N,)
    groups: np.ndarray   # (N,) run id
    severity: np.ndarray # (N,)


def simulate_run(cls: str, severity: float, load: float, noise: float, seed: int, seconds: float = 3.0,
                 background_unbalance: float = 0.0) -> np.ndarray:
    """Return (n_windows, F) window features for one run."""
    sim = MotorSimulator(seed=seed, base_load_nm=load)
    sim.vib.noise_rms = noise
    sim.plant.warm_start(load, seconds=0.8)
    if background_unbalance > 0:
        F.inject_unbalance(sim.faults, background_unbalance)
    if cls != "healthy":
        F.inject(sim.faults, cls, severity)
    vs, acs, ws = [], [], []
    for _ in range(int(seconds / sim.chunk_s)):
        st = sim.step()
        vs.append(st.vibration)
        acs.append(st.acoustic)
        ws.append(st.electrical.omega_m)
    v, a = np.hstack(vs), np.hstack(acs)
    w = np.concatenate(ws)
    fs = st.vib_fs
    nwin, nhop = int(WINDOW_S * fs), int(HOP_S * fs)
    feats = []
    for start in range(0, v.shape[1] - nwin + 1, nhop):
        frac = (start + nwin / 2) / v.shape[1]
        shaft_hz = float(w[min(len(w) - 1, int(frac * len(w)))]) / (2 * np.pi)
        feats.append(window_features(v[:, start:start + nwin], a[start:start + nwin], fs, st.acoustic_fs, shaft_hz))
    return np.array(feats)


def to_sequences(feats: np.ndarray, seq_len: int = SEQ_LEN) -> np.ndarray:
    return np.stack([feats[i:i + seq_len] for i in range(len(feats) - seq_len + 1)])


def build_dataset(runs_per_class: int, seed: int = 0, seconds: float = 3.0) -> Dataset:
    rng = np.random.default_rng(seed)
    X, y, g, s = [], [], [], []
    run_id = 0
    for ci, cls in enumerate(CLASSES):
        for _ in range(runs_per_class):
            sev = float(rng.uniform(0.15, 1.0)) if cls != "healthy" else 0.0
            seqs = to_sequences(simulate_run(
                cls, sev, load=float(rng.uniform(0.0, 12.0)), noise=float(rng.uniform(0.03, 0.12)),
                seed=int(rng.integers(1 << 30)), seconds=seconds,
                background_unbalance=float(rng.uniform(0.0, 0.08)) if cls != "unbalance" else 0.0,
            ))
            X.append(seqs)
            y += [ci] * len(seqs)
            g += [seed * 100000 + run_id] * len(seqs)
            s += [sev] * len(seqs)
            run_id += 1
    return Dataset(np.concatenate(X).astype(np.float32), np.array(y), np.array(g), np.array(s, dtype=np.float32))


def group_split(groups: np.ndarray, fractions=(0.6, 0.2, 0.2), seed: int = 0):
    """Split sample indices by group (run), returning (train, val, test) index arrays."""
    rng = np.random.default_rng(seed)
    uniq = rng.permutation(np.unique(groups))
    n_tr = int(round(fractions[0] * len(uniq)))
    n_va = int(round(fractions[1] * len(uniq)))
    parts = [set(uniq[:n_tr]), set(uniq[n_tr:n_tr + n_va]), set(uniq[n_tr + n_va:])]
    return tuple(np.array([i for i, gg in enumerate(groups) if gg in p]) for p in parts)
