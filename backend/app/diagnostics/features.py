"""diagnostics/features.py

Vibration/acoustic feature pipeline.

Framing: 0.5 s windows with a 0.2 s hop. Per channel (vib x, y, z, acoustic) a
28-dim feature vector is extracted:

* time domain (9): RMS, kurtosis, skewness, crest factor, peak-to-peak, variance,
  mean |x|, shape factor, impulse factor
* Welch-PSD band energy fractions (6)
* spectral shape (4): centroid, spread, entropy, flatness
* DWT (db4, 4 levels) relative detail-band energies (4)
* speed-normalized order features (5): 1x and 2x shaft amplitude (raw spectrum),
  and envelope-spectrum amplitude at BPFO, BPFI, 2*BSF (Hilbert envelope of the
  2-5 kHz band). The encoder speed normalizes these, as the plan requires.
"""

from __future__ import annotations

import math

import numpy as np
import pywt
from scipy.signal import butter, hilbert, sosfiltfilt, welch
from scipy.stats import kurtosis, skew

from app.simulation.mechanical_signals import BPFI, BPFO, BSF

WINDOW_S = 0.5
HOP_S = 0.2
BANDS = [(0, 200), (200, 500), (500, 1000), (1000, 2000), (2000, 4000), (4000, 6400)]
CHANNELS = ["vib_x", "vib_y", "vib_z", "acoustic"]
FEATURE_NAMES = (
    ["rms", "kurtosis", "skewness", "crest", "p2p", "variance", "mean_abs", "shape", "impulse"]
    + [f"band_{lo}_{hi}" for lo, hi in BANDS]
    + ["spec_centroid", "spec_spread", "spec_entropy", "spec_flatness"]
    + [f"dwt_d{i}" for i in range(1, 5)]
    + ["order_1x", "order_2x", "env_bpfo", "env_bpfi", "env_2bsf"]
)
N_FEATURES = len(FEATURE_NAMES)

_sos_cache: dict[float, np.ndarray] = {}


def _envelope_band(fs: float) -> np.ndarray:
    if fs not in _sos_cache:
        _sos_cache[fs] = butter(4, [2000, min(5000, 0.45 * fs)], btype="band", fs=fs, output="sos")
    return _sos_cache[fs]


def _amp_at(freqs: np.ndarray, spec: np.ndarray, f: float, tol: float) -> float:
    m = np.abs(freqs - f) <= tol
    return float(np.max(spec[m])) if np.any(m) else 0.0


def extract_features(x: np.ndarray, fs: float, shaft_hz: float) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    x = x - np.mean(x)
    rms = math.sqrt(float(np.mean(x**2))) + 1e-12
    mean_abs = float(np.mean(np.abs(x))) + 1e-12
    peak = float(np.max(np.abs(x)))
    feats = [
        rms, float(kurtosis(x, fisher=False)), float(skew(x)), peak / rms, float(np.ptp(x)),
        float(np.var(x)), mean_abs, rms / mean_abs, peak / mean_abs,
    ]
    f, pxx = welch(x, fs=fs, nperseg=min(1024, len(x)))
    total = float(np.sum(pxx)) + 1e-20
    feats += [float(np.sum(pxx[(f >= lo) & (f < hi)])) / total for lo, hi in BANDS]
    p = pxx / total
    centroid = float(np.sum(f * p))
    spread = math.sqrt(float(np.sum(((f - centroid) ** 2) * p)))
    entropy = float(-np.sum(p * np.log(p + 1e-20)) / math.log(len(p)))
    flatness = float(np.exp(np.mean(np.log(pxx + 1e-20))) / (np.mean(pxx) + 1e-20))
    feats += [centroid / (fs / 2), spread / (fs / 2), entropy, flatness]
    coeffs = pywt.wavedec(x, "db4", level=4)
    e = np.array([np.sum(c**2) for c in coeffs[1:]])  # d4..d1
    feats += list((e / (np.sum(e) + 1e-20))[::-1])

    n = len(x)
    win = np.hanning(n)
    spec = np.abs(np.fft.rfft(x * win)) / (np.sum(win) / 2)
    freqs = np.fft.rfftfreq(n, 1 / fs)
    tol = max(2.5, 0.03 * shaft_hz)
    feats += [_amp_at(freqs, spec, shaft_hz, tol), _amp_at(freqs, spec, 2 * shaft_hz, tol)]
    env = np.abs(hilbert(sosfiltfilt(_envelope_band(fs), x)))
    env -= np.mean(env)
    espec = np.abs(np.fft.rfft(env * win)) / (np.sum(win) / 2)
    norm = rms
    feats += [_amp_at(freqs, espec, o * shaft_hz, tol) / norm for o in (BPFO, BPFI, 2 * BSF)]
    return np.array(feats, dtype=np.float32)


def window_features(vib: np.ndarray, acoustic: np.ndarray, vib_fs: float, ac_fs: float, shaft_hz: float) -> np.ndarray:
    """Feature vector for one 0.5 s window: shape (len(CHANNELS) * N_FEATURES,)."""
    parts = [extract_features(vib[i], vib_fs, shaft_hz) for i in range(3)]
    parts.append(extract_features(acoustic, ac_fs, shaft_hz))
    return np.concatenate(parts)


def scalogram(x: np.ndarray, fs: float, n_scales: int = 32, max_points: int = 256) -> dict:
    """Complex-Morlet CWT magnitude for UI display (downsampled in time)."""
    freqs = np.geomspace(50, fs / 2.5, n_scales)
    wavelet = "cmor1.5-1.0"
    scales = pywt.central_frequency(wavelet) * fs / freqs
    coef, _ = pywt.cwt(np.asarray(x, dtype=np.float64), scales, wavelet, sampling_period=1 / fs, method="fft")
    mag = np.abs(coef)
    step = max(1, mag.shape[1] // max_points)
    return {"freqs": freqs.round(1).tolist(), "values": mag[:, ::step].round(4).tolist(), "dt": step / fs}
