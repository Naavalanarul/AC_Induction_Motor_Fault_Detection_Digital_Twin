"""Feature views computed identically on simulated and real records.

* "current"   -- current-spectrum (MCSA) features of the phase currents on 2 s windows with a 1 s hop
                 (the twin's electrical diagnostic uses 2 s windows; 0.5 s cannot resolve the
                 f(1 +/- 2s) sidebands). Amplitudes are in dB relative to the fundamental and the
                 rest are ratios, so the view is scale-free across motor ratings.
* "vibration" -- the twin's own vibration feature extractor (app.diagnostics.features,
                 0.5 s windows / 0.2 s hop at 12.8 kHz), restricted to the accelerometer axes that
                 the dataset provides. No dataset has the twin's acoustic channel, so the deployed
                 Conv-BiLSTM (4 channels incl. acoustic) cannot be applied unchanged; the
                 validation classifiers are trained on this common feature subset instead.
"""

from __future__ import annotations

import math

import numpy as np

from app.diagnostics.features import FEATURE_NAMES, HOP_S, WINDOW_S, extract_features
from app.validation.preprocessing import ELEC_FS, TWIN_VIB_FS, Prepared, windows

CURRENT_WIN_S = 2.0
CURRENT_HOP_S = 1.0
BANDS = [(0, 40), (60, 200), (200, 500), (500, 1000), (1000, 2400)]
CURRENT_FEATURES = (
    ["brb_lsb_db", "brb_usb_db", "brb2_lsb_db", "brb2_usb_db", "ecc_lsb_db", "ecc_usb_db",
     "h3_db", "h5_db", "h7_db", "neg_seq_ratio", "rms_unbalance", "flatness_0_500"]
    + [f"band_{a}_{b}" for a, b in BANDS]
)
VIB_AXES = ("vib_x", "vib_y", "vib_z")


def _db_at(freqs, spec_db, f0, tol, exclude: float | None = None, lobe: float = 1.0):
    """Peak level within +/- tol of f0. Bins within `lobe` Hz of `exclude` (the fundamental) are
    ignored, so a near-zero slip cannot turn the fundamental itself into a 'sideband' at 0 dBc."""
    m = np.abs(freqs - f0) <= tol
    if exclude is not None:
        m &= np.abs(freqs - exclude) > lobe
    return float(np.max(spec_db[m])) if np.any(m) else -120.0


def current_window_features(ia, ib, ic, f_s: float, slip: float, pole_pairs: int = 2) -> np.ndarray:
    n = len(ia)
    win = np.hanning(n)
    spec = np.abs(np.fft.rfft((ia - ia.mean()) * win)) / (win.sum() / 2)
    freqs = np.fft.rfftfreq(n, 1 / ELEC_FS)
    df = freqs[1] - freqs[0]
    fund = _db_at(freqs, 20 * np.log10(spec + 1e-12), f_s, 1.5)
    db = 20 * np.log10(spec + 1e-12) - fund
    tol = max(df, 0.4)
    fr = f_s * (1 - slip) / pole_pairs
    lobe = 2.5 * df  # Hann main lobe half-width is 2 bins
    feats = [
        _db_at(freqs, db, f_s * (1 - 2 * slip), tol, f_s, lobe), _db_at(freqs, db, f_s * (1 + 2 * slip), tol, f_s, lobe),
        _db_at(freqs, db, f_s * (1 - 4 * slip), tol, f_s, lobe), _db_at(freqs, db, f_s * (1 + 4 * slip), tol, f_s, lobe),
        _db_at(freqs, db, f_s - fr, tol), _db_at(freqs, db, f_s + fr, tol),
        _db_at(freqs, db, 3 * f_s, 1.5), _db_at(freqs, db, 5 * f_s, 1.5), _db_at(freqs, db, 7 * f_s, 1.5),
    ]
    if ib is not None and ic is not None:
        t = np.arange(n) / ELEC_FS
        e = np.exp(-2j * math.pi * f_s * t)
        ph = [2 * np.dot(x - x.mean(), e) / n for x in (ia, ib, ic)]
        a = np.exp(2j * math.pi / 3)
        pos = abs(ph[0] + a * ph[1] + a * a * ph[2]) / 3
        neg = abs(ph[0] + a * a * ph[1] + a * ph[2]) / 3
        rms = [float(np.sqrt(np.mean((x - x.mean()) ** 2))) for x in (ia, ib, ic)]
        feats += [float(neg / max(float(pos), 1e-12)), (max(rms) - min(rms)) / max(float(np.mean(rms)), 1e-12)]
    else:
        feats += [0.0, 0.0]
    pw = spec**2
    m500 = (freqs > 1) & (freqs < 500)
    feats.append(float(np.exp(np.mean(np.log(pw[m500] + 1e-20))) / (np.mean(pw[m500]) + 1e-20)))
    # band energies relative to all energy except the fundamental (which would swamp them)
    off_fund = np.abs(freqs - f_s) > 3.0
    total = float(np.sum(pw[off_fund])) + 1e-20
    feats += [float(np.sum(pw[(freqs >= a) & (freqs < b) & off_fund])) / total for a, b in BANDS]
    return np.array(feats, dtype=np.float64)


def current_features(p: Prepared, pole_pairs: int = 2) -> np.ndarray:
    """(n_windows, len(CURRENT_FEATURES)) or an empty array when the record has no current."""
    if "ia" not in p.elec:
        return np.zeros((0, len(CURRENT_FEATURES)))
    ia = p.elec["ia"]
    ib, ic = p.elec.get("ib"), p.elec.get("ic")
    slip = p.slip if p.slip is not None else 0.03
    rows = [current_window_features(ia[w], None if ib is None else ib[w], None if ic is None else ic[w],
                                    p.supply_freq_hz, slip, pole_pairs)
            for w in windows(len(ia), ELEC_FS, CURRENT_WIN_S, CURRENT_HOP_S)]
    return np.array(rows) if rows else np.zeros((0, len(CURRENT_FEATURES)))


def vibration_feature_names(axes: tuple[str, ...]) -> list[str]:
    return [f"{a}.{n}" for a in axes for n in FEATURE_NAMES]


def vibration_features(p: Prepared, axes: tuple[str, ...]) -> np.ndarray:
    if not axes or not all(a in p.vib for a in axes):
        return np.zeros((0, len(axes) * len(FEATURE_NAMES)))
    n = min(len(p.vib[a]) for a in axes)
    rows = []
    for w in windows(n, TWIN_VIB_FS, WINDOW_S, HOP_S):
        rows.append(np.concatenate([extract_features(p.vib[a][w], TWIN_VIB_FS, p.shaft_hz) for a in axes]))
    return np.array(rows, dtype=np.float64) if rows else np.zeros((0, len(axes) * len(FEATURE_NAMES)))


def feature_names(view: str, axes: tuple[str, ...] = VIB_AXES) -> list[str]:
    return list(CURRENT_FEATURES) if view == "current" else vibration_feature_names(axes)


def compute(p: Prepared, view: str, axes: tuple[str, ...] = VIB_AXES) -> np.ndarray:
    pp = int(p.record.meta.get("pole_pairs", 2))
    return current_features(p, pp) if view == "current" else vibration_features(p, axes)
