"""signal_processing/feature_extraction.py

Feature Extraction for Condition Monitoring.

Extracts statistical and spectral features from vibration, current,
and acoustic signals for fault classification and trending.

Features:
- Time domain: RMS, Kurtosis, Skewness, Crest Factor, Peak-to-Peak, Variance,
              Mean Absolute, Shape Factor, Impulse Factor, Clearance Factor
- Frequency domain: Spectral Centroid, Spread, Entropy, Flatness,
                    Band Energy Fractions, THD
- Wavelet: DWT (db4, 4 levels) relative detail-band energies
- Order tracking: 1×, 2× shaft amplitude
- Envelope: BPFO, BPFI, 2×BSF amplitudes
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pywt
from scipy.signal import butter, hilbert, sosfiltfilt, welch
from scipy.stats import kurtosis, skew


@dataclass
class SignalFeatures:
    """Container for extracted signal features."""

    # Time domain (9 features)
    rms: float
    kurtosis: float
    skewness: float
    crest_factor: float
    peak_to_peak: float
    variance: float
    mean_abs: float
    shape_factor: float
    impulse_factor: float
    clearance_factor: float = 0.0  # Peak / (mean(sqrt(|x|)))²

    # Frequency band energies (6 features)
    band_0_200: float = 0.0
    band_200_500: float = 0.0
    band_500_1000: float = 0.0
    band_1000_2000: float = 0.0
    band_2000_4000: float = 0.0
    band_4000_6400: float = 0.0

    # Spectral shape (4 features)
    spectral_centroid: float = 0.0
    spectral_spread: float = 0.0
    spectral_entropy: float = 0.0
    spectral_flatness: float = 0.0

    # Wavelet DWT (4 features) - db4, 4 levels
    dwt_d1: float = 0.0
    dwt_d2: float = 0.0
    dwt_d3: float = 0.0
    dwt_d4: float = 0.0

    # Order tracking (5 features)
    order_1x: float = 0.0
    order_2x: float = 0.0
    env_bpfo: float = 0.0
    env_bpfi: float = 0.0
    env_2bsf: float = 0.0

    # Additional electrical features
    thd_percent: float = 0.0
    zero_crossing_rate: float = 0.0
    fundamental_freq_hz: float = 0.0
    fundamental_mag: float = 0.0

    def to_array(self) -> np.ndarray:
        """Convert to flat feature array for ML."""
        return np.array([
            self.rms, self.kurtosis, self.skewness, self.crest_factor,
            self.peak_to_peak, self.variance, self.mean_abs, self.shape_factor,
            self.impulse_factor, self.clearance_factor,
            self.band_0_200, self.band_200_500, self.band_500_1000,
            self.band_1000_2000, self.band_2000_4000, self.band_4000_6400,
            self.spectral_centroid, self.spectral_spread, self.spectral_entropy,
            self.spectral_flatness,
            self.dwt_d1, self.dwt_d2, self.dwt_d3, self.dwt_d4,
            self.order_1x, self.order_2x, self.env_bpfo, self.env_bpfi, self.env_2bsf,
            self.thd_percent, self.zero_crossing_rate,
        ], dtype=np.float32)

    @property
    def feature_names(self) -> list[str]:
        return [
            "rms", "kurtosis", "skewness", "crest_factor", "peak_to_peak",
            "variance", "mean_abs", "shape_factor", "impulse_factor", "clearance_factor",
            "band_0_200", "band_200_500", "band_500_1000", "band_1000_2000",
            "band_2000_4000", "band_4000_6400",
            "spectral_centroid", "spectral_spread", "spectral_entropy", "spectral_flatness",
            "dwt_d1", "dwt_d2", "dwt_d3", "dwt_d4",
            "order_1x", "order_2x", "env_bpfo", "env_bpfi", "env_2bsf",
            "thd_percent", "zero_crossing_rate",
        ]


class FeatureExtractor:
    """Extracts comprehensive features from time-series signals."""

    # Frequency bands for band energy fractions
    BANDS = [(0, 200), (200, 500), (500, 1000), (1000, 2000), (2000, 4000), (4000, 6400)]
    # Envelope bandpass for bearing analysis
    ENVELOPE_BAND = (2000.0, 5000.0)
    # Bearing defect orders (for 6205 bearing)
    BPFO_ORDER = 3.5848
    BPFI_ORDER = 5.4152
    BSF_ORDER = 2.3357 * 2  # 2×BSF is commonly used

    _sos_cache: dict[tuple[float, float], np.ndarray] = {}

    def __init__(self, fs: float = 12800.0, signal_type: Literal["vibration", "current", "acoustic"] = "vibration"):
        """Initialize feature extractor.

        Args:
            fs: Sampling frequency [Hz]
            signal_type: Type of signal ('vibration', 'current', 'acoustic')
        """
        self.fs = fs
        self.signal_type = signal_type

    def _get_envelope_sos(self) -> np.ndarray:
        """Get cached SOS filter for envelope bandpass."""
        key = self.ENVELOPE_BAND
        if key not in self._sos_cache:
            self._sos_cache[key] = butter(
                4,
                [self.ENVELOPE_BAND[0] / (self.fs / 2), min(self.ENVELOPE_BAND[1], self.fs / 2 * 0.99) / (self.fs / 2)],
                btype="band",
                output="sos",
            )
        return self._sos_cache[key]

    def extract_features(
        self,
        x: np.ndarray,
        fs: float | None = None,
        shaft_freq_hz: float = 25.0,
        bearing_geometry=None,
    ) -> SignalFeatures:
        """Extract all features from a single signal channel.

        Args:
            x: Input signal
            fs: Sampling frequency (overrides instance fs if provided)
            shaft_freq_hz: Shaft rotation frequency [Hz]
            bearing_geometry: Bearing geometry for defect frequencies

        Returns:
            SignalFeatures with all extracted features
        """
        if fs is not None:
            self.fs = fs

        x = np.asarray(x, dtype=np.float64)
        x = x - np.mean(x)

        # Use provided bearing geometry or default
        if bearing_geometry is None:
            from app.core_physics.fault_models import BearingGeometry
            bearing_geometry = BearingGeometry()

        # Bearing defect frequencies
        defects = bearing_geometry.defect_frequencies(shaft_freq_hz)
        bpfo_hz = defects["BPFO"]
        bpfi_hz = defects["BPFI"]
        bsf_hz = defects["BSF"] * 2  # 2×BSF

        # --- Time Domain Features ---
        rms = math.sqrt(float(np.mean(x**2))) + 1e-12
        mean_abs = float(np.mean(np.abs(x))) + 1e-12
        peak = float(np.max(np.abs(x)))
        peak_to_peak = float(np.ptp(x))
        var = float(np.var(x))

        crest = peak / rms
        shape = rms / mean_abs
        impulse = peak / mean_abs
        clearance = peak / (float(np.mean(np.sqrt(np.abs(x) + 1e-12))) ** 2) if len(x) > 0 else 0.0

        kurt = float(kurtosis(x, fisher=False))  # Pearson kurtosis
        skewness = float(skew(x))

        # Zero crossing rate
        zero_crossings = np.sum(np.diff(np.signbit(x)))
        zcr = zero_crossings / len(x) * self.fs

        # --- Frequency Domain (Welch PSD) ---
        nperseg = min(1024, len(x))
        f, pxx = welch(x, fs=self.fs, nperseg=nperseg, scaling="density")
        total_power = float(np.sum(pxx)) + 1e-20

        # Band energy fractions
        band_energies = []
        for lo, hi in self.BANDS:
            mask = (f >= lo) & (f < hi)
            band_e = float(np.sum(pxx[mask])) / total_power
            band_energies.append(band_e)

        # Spectral shape features
        p_norm = pxx / total_power
        centroid = float(np.sum(f * p_norm))
        spread = math.sqrt(float(np.sum(((f - centroid) ** 2) * p_norm)))
        entropy = float(-np.sum(p_norm * np.log(p_norm + 1e-20)) / math.log(len(p_norm)))
        flatness = float(np.exp(np.mean(np.log(pxx + 1e-20))) / (np.mean(pxx) + 1e-20))

        # THD calculation (find fundamental)
        # For vibration, fundamental is typically shaft frequency or line frequency
        fund_mask = (f >= shaft_freq_hz - 2.0) & (f <= shaft_freq_hz + 2.0)
        if np.any(fund_mask):
            fund_idx = np.where(fund_mask)[0][np.argmax(pxx[fund_mask])]
            fund_freq = float(f[fund_idx])
            fund_mag = float(np.sqrt(pxx[fund_idx]))
            # THD = sqrt(sum(harmonics^2)) / fundamental
            harm_power = 0.0
            for k in range(2, 20):
                f_harm = k * fund_freq
                if f_harm >= self.fs / 2:
                    break
                mask = (f >= f_harm - 1.0) & (f <= f_harm + 1.0)
                if np.any(mask):
                    harm_power += float(np.max(pxx[mask]))
            thd = math.sqrt(harm_power) / fund_mag * 100.0 if fund_mag > 0 else 0.0
        else:
            fund_freq = shaft_freq_hz
            fund_mag = 0.0
            thd = 0.0

        # --- Wavelet DWT (db4, 4 levels) ---
        try:
            coeffs = pywt.wavedec(x, "db4", level=4)
            # coeffs = [cA4, cD4, cD3, cD2, cD1]
            detail_energies = np.array([np.sum(c**2) for c in coeffs[1:]])  # d4, d3, d2, d1
            total_detail = np.sum(detail_energies) + 1e-20
            dwt_energies = (detail_energies / total_detail)[::-1]  # d1, d2, d3, d4
        except Exception:
            dwt_energies = np.zeros(4)

        # --- Envelope Analysis ---
        sos = self._get_envelope_sos()
        filtered = sosfiltfilt(sos, x)
        analytic = hilbert(filtered)
        envelope = np.abs(analytic)
        envelope = envelope - np.mean(envelope)

        # Envelope spectrum
        n = len(envelope)
        win = np.hanning(n)
        env_spec = np.abs(np.fft.rfft(envelope * win)) / (np.sum(win) / 2)
        env_freqs = np.fft.rfftfreq(n, 1 / self.fs)
        tol = max(2.5, 0.03 * shaft_freq_hz)

        def amp_at(freqs: np.ndarray, spec: np.ndarray, f_target: float, tol_hz: float) -> float:
            mask = np.abs(freqs - f_target) <= tol_hz
            return float(np.max(spec[mask])) if np.any(mask) else 0.0

        env_bpfo = amp_at(env_freqs, env_spec, bpfo_hz, tol)
        env_bpfi = amp_at(env_freqs, env_spec, bpfi_hz, tol)
        env_2bsf = amp_at(env_freqs, env_spec, bsf_hz, tol)

        # --- Order tracking (raw spectrum at 1× and 2× shaft) ---
        spec = np.abs(np.fft.rfft(x * win)) / (np.sum(win) / 2)
        freqs = np.fft.rfftfreq(n, 1 / self.fs)
        order_1x = amp_at(freqs, spec, shaft_freq_hz, tol)
        order_2x = amp_at(freqs, spec, 2.0 * shaft_freq_hz, tol)

        # Normalize envelope amplitudes by signal RMS
        norm = rms

        return SignalFeatures(
            rms=rms,
            kurtosis=kurt,
            skewness=skewness,
            crest_factor=crest,
            peak_to_peak=peak_to_peak,
            variance=var,
            mean_abs=mean_abs,
            shape_factor=shape,
            impulse_factor=impulse,
            clearance_factor=clearance,
            band_0_200=band_energies[0],
            band_200_500=band_energies[1],
            band_500_1000=band_energies[2],
            band_1000_2000=band_energies[3],
            band_2000_4000=band_energies[4],
            band_4000_6400=band_energies[5],
            spectral_centroid=centroid / (self.fs / 2),
            spectral_spread=spread / (self.fs / 2),
            spectral_entropy=entropy,
            spectral_flatness=flatness,
            dwt_d1=dwt_energies[0],
            dwt_d2=dwt_energies[1],
            dwt_d3=dwt_energies[2],
            dwt_d4=dwt_energies[3],
            order_1x=order_1x / norm,
            order_2x=order_2x / norm,
            env_bpfo=env_bpfo / norm,
            env_bpfi=env_bpfi / norm,
            env_2bsf=env_2bsf / norm,
            thd_percent=thd,
            zero_crossing_rate=zcr,
            fundamental_freq_hz=fund_freq,
            fundamental_mag=fund_mag,
        )

    def window_features(
        self,
        vib_x: np.ndarray,
        vib_y: np.ndarray,
        vib_z: np.ndarray,
        acoustic: np.ndarray,
        vib_fs: float,
        ac_fs: float,
        shaft_freq_hz: float,
    ) -> np.ndarray:
        """Extract feature vector for one 0.5s window: shape (4 channels * N_FEATURES,)."""
        feats_x = self.extract_features(vib_x, vib_fs, shaft_freq_hz).to_array()
        feats_y = self.extract_features(vib_y, vib_fs, shaft_freq_hz).to_array()
        feats_z = self.extract_features(vib_z, vib_fs, shaft_freq_hz).to_array()
        feats_ac = self.extract_features(acoustic, ac_fs, shaft_freq_hz).to_array()
        return np.concatenate([feats_x, feats_y, feats_z, feats_ac])


def extract_current_features(
    i_abc: np.ndarray,
    fs: float = 5000.0,
    nominal_freq: float = 50.0,
) -> dict:
    """Extract features from 3-phase current signals.

    Args:
        i_abc: Shape (3, n) phase currents [A]
        fs: Sampling frequency [Hz]
        nominal_freq: Nominal supply frequency [Hz]

    Returns:
        Dictionary of features per phase and aggregate
    """
    features = {}
    for phase_idx, phase_name in enumerate(["a", "b", "c"]):
        x = i_abc[phase_idx]
        x = x - np.mean(x)

        # Basic stats
        rms = float(np.sqrt(np.mean(x**2)))
        peak = float(np.max(np.abs(x)))
        crest = peak / rms if rms > 0 else 0.0

        # FFT
        n = len(x)
        win = np.hanning(n)
        spec = np.abs(np.fft.rfft(x * win)) / (np.sum(win) / 2)
        freqs = np.fft.rfftfreq(n, 1 / fs)

        # Fundamental
        fund_mask = (freqs >= nominal_freq - 1.0) & (freqs <= nominal_freq + 1.0)
        if np.any(fund_mask):
            fund_idx = np.where(fund_mask)[0][np.argmax(spec[fund_mask])]
            fund_freq = float(freqs[fund_idx])
            fund_mag = float(spec[fund_idx])
        else:
            fund_freq = nominal_freq
            fund_mag = 0.0

        # THD
        harm_power = 0.0
        for k in range(2, 20):
            f_harm = k * fund_freq
            if f_harm >= fs / 2:
                break
            mask = (freqs >= f_harm - 0.5) & (freqs <= f_harm + 0.5)
            if np.any(mask):
                harm_power += float(np.max(spec[mask])**2)
        thd = math.sqrt(harm_power) / fund_mag * 100.0 if fund_mag > 0 else 0.0

        # Negative sequence (approximate from phase imbalance)
        features[phase_name] = {
            "rms": rms,
            "peak": peak,
            "crest_factor": crest,
            "fundamental_freq": fund_freq,
            "fundamental_mag": fund_mag,
            "thd_percent": thd,
        }

    # Aggregate features
    rms_vals = [features[p]["rms"] for p in ["a", "b", "c"]]
    features["aggregate"] = {
        "rms_mean": float(np.mean(rms_vals)),
        "rms_std": float(np.std(rms_vals)),
        "rms_imbalance": float(np.std(rms_vals) / (np.mean(rms_vals) + 1e-12)),
        "max_thd": max(features[p]["thd_percent"] for p in ["a", "b", "c"]),
    }

    return features
