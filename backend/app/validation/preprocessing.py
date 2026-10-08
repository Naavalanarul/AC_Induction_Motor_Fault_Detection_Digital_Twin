"""Pre-processing shared by real and simulated records.

* NaN cells (LIMAN-C keeps empty cells) are handled by an explicit policy and counted -- never
  silently zero-filled.
* Signals are resampled to the twin's own rates: electrical channels to the plant/sensor rate
  (5 kHz, `MotorSimulator` default) and vibration to the accelerometer rate (12.8 kHz, VIB_FS).
* The supply frequency is estimated from the current spectrum (handles 50 Hz, 60 Hz and VFD
  operation such as ESTOGU's 45-50 Hz or Bruinsma's speed-controlled pumps).
* Slip is estimated from the broken-bar sideband pair f(1 +/- 2s) when no speed signal exists.
  This locates the sideband peaks (which is what the current features need) but is only an
  approximation of the mechanical slip (on simulated broken-bar runs it is within ~20 % of the
  encoder value; speed oscillation shifts the peaks). It is flagged wherever it is used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

import numpy as np
from scipy.signal import resample_poly

from app.simulation.mechanical_signals import VIB_FS
from app.validation.records import CURRENT, VIBRATION, VOLTAGE, Record

ELEC_FS = 5000.0  # twin electrical sample rate (MotorSimulator / current & voltage sensors)
TWIN_VIB_FS = VIB_FS


class PreprocessingError(ValueError):
    pass


def handle_nans(x: np.ndarray, policy: str = "interpolate", max_fraction: float = 0.01) -> tuple[np.ndarray, int]:
    """Return (clean signal, number of NaN samples). Policies: interpolate | drop | error.

    `drop` and `error` refuse records with any NaN; `interpolate` fills gaps linearly but refuses
    records with more than `max_fraction` NaNs (a mostly-empty file is not a recording).
    """
    x = np.asarray(x, dtype=np.float64)
    bad = ~np.isfinite(x)
    n_bad = int(bad.sum())
    if n_bad == 0:
        return x, 0
    if policy in ("drop", "error") or n_bad > max_fraction * len(x):
        raise PreprocessingError(f"{n_bad} NaN samples ({100 * n_bad / len(x):.2f} %) under policy {policy!r}")
    idx = np.arange(len(x))
    y = x.copy()
    y[bad] = np.interp(idx[bad], idx[~bad], x[~bad])
    return y, n_bad


def resample(x: np.ndarray, fs_in: float, fs_out: float) -> np.ndarray:
    if abs(fs_in - fs_out) < 1e-6:
        return np.asarray(x, dtype=np.float64)
    frac = Fraction(fs_out / fs_in).limit_denominator(1000)
    return resample_poly(np.asarray(x, dtype=np.float64), frac.numerator, frac.denominator)


def estimate_supply_freq(i: np.ndarray, fs: float, lo: float = 20.0, hi: float = 70.0) -> float:
    """Fundamental of the current spectrum in [lo, hi] Hz with parabolic peak interpolation."""
    x = np.asarray(i, dtype=np.float64) - np.mean(i)
    n = len(x)
    spec = np.abs(np.fft.rfft(x * np.hanning(n)))
    f = np.fft.rfftfreq(n, 1.0 / fs)
    m = (f >= lo) & (f <= hi)
    k = int(np.where(m)[0][np.argmax(spec[m])])
    if 0 < k < len(spec) - 1:
        a, b, c = np.log(spec[k - 1] + 1e-20), np.log(spec[k] + 1e-20), np.log(spec[k + 1] + 1e-20)
        denom = a - 2 * b + c
        delta = 0.5 * (a - c) / denom if denom != 0 else 0.0
        return float(f[k] + delta * (f[1] - f[0]))
    return float(f[k])


def estimate_slip(i: np.ndarray, fs: float, f_s: float, s_range=(0.003, 0.08)) -> tuple[float | None, float]:
    """Slip from the strongest symmetric sideband pair f(1 +/- 2s). Returns (slip or None, prominence dB).

    Healthy motors have only faint sidebands, so a low prominence (< 12 dB above the local floor;
    searching many candidate pairs makes 6 dB noise maxima common)
    returns None and callers fall back to a load-based slip, recording that they did so.
    """
    x = np.asarray(i, dtype=np.float64) - np.mean(i)
    n = len(x)
    nfft = 4 * n  # zero-padding: finer frequency grid for locating the sideband pair
    # Blackman-Harris (~-92 dB sidelobes): with a Hann window the fundamental's leakage skirt sits
    # far above the noise floor 1-2 Hz away and is mistaken for a sideband pair on healthy motors.
    from scipy.signal.windows import blackmanharris

    spec = 20 * np.log10(np.abs(np.fft.rfft(x * blackmanharris(n), nfft)) + 1e-12)
    f = np.fft.rfftfreq(nfft, 1.0 / fs)
    df = f[1] - f[0]
    best_s, best = None, -np.inf
    for s in np.arange(s_range[0], s_range[1], max(df / (4 * f_s), 2e-4)):
        lo, hi = f_s * (1 - 2 * s), f_s * (1 + 2 * s)
        if abs(hi - f_s) < max(16 * df, 1.0):  # stay out of the fundamental's (wider) main lobe
            continue
        v = spec[int(round(lo / df))] + spec[int(round(hi / df))]
        if v > best:
            best, best_s = v, float(s)
    if best_s is None:
        return None, 0.0
    band = (f > f_s * (1 - 2 * s_range[1])) & (f < f_s * (1 + 2 * s_range[1])) & (np.abs(f - f_s) > 1.0)
    floor = float(np.median(spec[band])) if np.any(band) else float(np.median(spec))
    prominence = best / 2 - floor
    return (best_s if prominence >= 12.0 else None), float(prominence)


@dataclass
class Prepared:
    """A record resampled to the twin's rates plus derived operating-point estimates."""

    record: Record
    elec: dict[str, np.ndarray] = field(default_factory=dict)  # at ELEC_FS
    vib: dict[str, np.ndarray] = field(default_factory=dict)   # at TWIN_VIB_FS
    supply_freq_hz: float = 50.0
    slip: float | None = None
    slip_source: str = "none"
    nan_samples: int = 0

    @property
    def shaft_hz(self) -> float:
        rpm = self.record.meta.get("speed_rpm")
        if rpm:
            return float(rpm) / 60.0
        pp = int(self.record.meta.get("pole_pairs", 2))
        s = self.slip if self.slip is not None else 0.03
        return self.supply_freq_hz * (1 - s) / pp


def nominal_slip(load_pct: float | None, rated_slip: float = 0.04) -> float:
    """Load-proportional slip guess used when no speed and no clear sidebands exist."""
    return max(0.002, rated_slip * (load_pct if load_pct is not None else 75.0) / 100.0)


def prepare(rec: Record, nan_policy: str = "interpolate") -> Prepared:
    out = Prepared(record=rec)
    for name in CURRENT + VOLTAGE:
        if name in rec.signals:
            x, nb = handle_nans(rec.signals[name], nan_policy)
            out.nan_samples += nb
            out.elec[name] = resample(x, rec.fs_of(name), ELEC_FS)
    for name in VIBRATION:
        if name in rec.signals:
            x, nb = handle_nans(rec.signals[name], nan_policy)
            out.nan_samples += nb
            out.vib[name] = resample(x, rec.fs_of(name), TWIN_VIB_FS)
    if "ia" in out.elec:
        out.supply_freq_hz = rec.supply_freq_hz or estimate_supply_freq(out.elec["ia"], ELEC_FS)
        if rec.meta.get("speed_rpm"):
            pp = int(rec.meta.get("pole_pairs", 2))
            out.slip = max(0.0, 1 - pp * float(rec.meta["speed_rpm"]) / 60.0 / out.supply_freq_hz)
            out.slip_source = "speed (assumed pole pairs)" if "pole_pairs" not in rec.meta else "speed"
        else:
            s, _ = estimate_slip(out.elec["ia"], ELEC_FS, out.supply_freq_hz)
            out.slip, out.slip_source = (s, "current sidebands") if s is not None else (nominal_slip(rec.load_pct), "load-based guess")
    return out


def windows(n: int, fs: float, win_s: float, hop_s: float) -> list[slice]:
    w, h = int(round(win_s * fs)), int(round(hop_s * fs))
    return [slice(a, a + w) for a in range(0, n - w + 1, h)]
