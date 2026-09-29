"""signal_processing/vibration_analysis.py

Vibration Analysis for Bearing Fault Detection.

Implements:
- Bearing defect frequency calculation (BPFO, BPFI, BSF, FTF)
- Envelope detection via Hilbert transform
- Spectral kurtosis for impulsiveness detection
- Order tracking for shaft-synchronous analysis
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.signal import butter, filtfilt, hilbert, sosfiltfilt, welch
from scipy.stats import kurtosis

from core_physics.fault_models import BearingGeometry


@dataclass
class BearingFrequencies:
    """Calculated bearing defect frequencies."""

    bpfo_hz: float  # Ball Pass Frequency Outer race
    bpfi_hz: float  # Ball Pass Frequency Inner race
    bsf_hz: float  # Ball Spin Frequency
    ftf_hz: float  # Fundamental Train Frequency (cage)
    bpfo_order: float  # BPFO as multiple of shaft frequency
    bpfi_order: float  # BPFI as multiple of shaft frequency
    bsf_order: float  # BSF as multiple of shaft frequency
    ftf_order: float  # FTF as multiple of shaft frequency


@dataclass
class VibrationResult:
    """Results from vibration analysis."""

    # Time domain
    rms: float
    peak: float
    peak_to_peak: float
    crest_factor: float
    kurtosis: float
    skewness: float

    # Frequency domain
    freqs: np.ndarray
    psd: np.ndarray
    psd_db: np.ndarray

    # Envelope analysis
    env_freqs: np.ndarray
    env_psd: np.ndarray
    env_psd_db: np.ndarray

    # Bearing frequencies
    bearing_freqs: BearingFrequencies

    # Fault indicators
    bpfo_amplitude: float
    bpfi_amplitude: float
    bsf_amplitude: float
    ftf_amplitude: float
    spectral_kurtosis: float

    # ISO 10816 severity
    iso_severity_zone: str  # 'A', 'B', 'C', 'D'
    overall_velocity_rms: float  # mm/s RMS (ISO 10816 uses velocity)


class VibrationAnalyzer:
    """Vibration signal analyzer for bearing and mechanical fault detection."""

    def __init__(
        self,
        fs: float = 12800.0,
        shaft_freq_hz: float = 25.0,  # Default 1500 RPM
        bearing_geometry: BearingGeometry | None = None,
        envelope_band: tuple[float, float] = (2000.0, 5000.0),
    ):
        """Initialize vibration analyzer.

        Args:
            fs: Sampling frequency [Hz]
            shaft_freq_hz: Shaft rotation frequency [Hz]
            bearing_geometry: Bearing geometry parameters
            envelope_band: Bandpass filter range for envelope detection [Hz]
        """
        self.fs = fs
        self.shaft_freq_hz = shaft_freq_hz
        self.bearing_geometry = bearing_geometry if bearing_geometry is not None else BearingGeometry()
        self.envelope_band = envelope_band
        self._sos_cache: dict[tuple[float, float, float], np.ndarray] = {}

    def _get_bandpass_sos(self, low: float, high: float, order: int = 4) -> np.ndarray:
        """Get cached SOS filter for bandpass."""
        key = (low, high, order)
        if key not in self._sos_cache:
            nyq = self.fs / 2.0
            self._sos_cache[key] = butter(order, [low / nyq, min(high, nyq * 0.99) / nyq], btype="band", output="sos")
        return self._sos_cache[key]

    def calculate_bearing_frequencies(self, shaft_freq_hz: float | None = None) -> BearingFrequencies:
        """Calculate bearing defect frequencies from geometry and shaft speed."""
        fr = shaft_freq_hz if shaft_freq_hz is not None else self.shaft_freq_hz
        defects = self.bearing_geometry.defect_frequencies(fr)

        return BearingFrequencies(
            bpfo_hz=defects["BPFO"],
            bpfi_hz=defects["BPFI"],
            bsf_hz=defects["BSF"],
            ftf_hz=defects["FTF"],
            bpfo_order=defects["bpfo_mult"],
            bpfi_order=defects["bpfi_mult"],
            bsf_order=defects["bsf_mult"],
            ftf_order=defects["ftf_mult"],
        )

    def analyze(
        self,
        vibration_signal: np.ndarray,
        shaft_freq_hz: float | None = None,
        bearing_geometry: BearingGeometry | None = None,
    ) -> VibrationResult:
        """Complete vibration analysis pipeline.

        Args:
            vibration_signal: Acceleration signal [m/s²] or [g]
            shaft_freq_hz: Current shaft frequency [Hz]
            bearing_geometry: Override bearing geometry

        Returns:
            VibrationResult with all analysis metrics
        """
        x = np.asarray(vibration_signal, dtype=np.float64)
        x = x - np.mean(x)  # Remove DC

        if shaft_freq_hz is not None:
            self.shaft_freq_hz = shaft_freq_hz
        if bearing_geometry is not None:
            self.bearing_geometry = bearing_geometry

        fr = self.shaft_freq_hz
        bearing_freqs = self.calculate_bearing_frequencies(fr)

        # --- Time Domain Features ---
        rms = float(np.sqrt(np.mean(x**2)))
        peak = float(np.max(np.abs(x)))
        peak_to_peak = float(np.ptp(x))
        crest_factor = peak / rms if rms > 0 else 0.0
        kurt = float(kurtosis(x, fisher=False))  # Fisher=False gives Pearson kurtosis (3 for Gaussian)
        skew = float(np.mean(((x - np.mean(x)) / (np.std(x) + 1e-12)) ** 3)) if np.std(x) > 0 else 0.0

        # --- Frequency Domain (PSD) ---
        nperseg = min(4096, len(x))
        freqs, psd = welch(x, fs=self.fs, nperseg=nperseg, scaling="density")
        psd_db = 10.0 * np.log10(np.maximum(psd, 1e-12))

        # --- Envelope Analysis ---
        # Bandpass filter in resonance region (typically 2-5 kHz)
        sos = self._get_bandpass_sos(*self.envelope_band)
        filtered = sosfiltfilt(sos, x)

        # Hilbert transform for envelope
        analytic = hilbert(filtered)
        envelope = np.abs(analytic)
        envelope = envelope - np.mean(envelope)

        # PSD of envelope
        env_freqs, env_psd = welch(envelope, fs=self.fs, nperseg=nperseg, scaling="density")
        env_psd_db = 10.0 * np.log10(np.maximum(env_psd, 1e-12))

        # --- Extract amplitudes at bearing frequencies ---
        def amp_at(freqs: np.ndarray, spec: np.ndarray, f_target: float, tol: float = 2.0) -> float:
            mask = np.abs(freqs - f_target) <= tol
            return float(np.max(spec[mask])) if np.any(mask) else 0.0

        # Tolerance for bearing frequency search
        tol = max(2.0, 0.03 * fr)

        bpfo_amp = amp_at(env_freqs, env_psd, bearing_freqs.bpfo_hz, tol)
        bpfi_amp = amp_at(env_freqs, env_psd, bearing_freqs.bpfi_hz, tol)
        bsf_amp = amp_at(env_freqs, env_psd, bearing_freqs.bsf_hz, tol)
        ftf_amp = amp_at(env_freqs, env_psd, bearing_freqs.ftf_hz, tol)

        # Also check 2×BPFI, 2×BSF (common harmonics)
        bpfi_2x = amp_at(env_freqs, env_psd, 2 * bearing_freqs.bpfi_hz, tol)
        bsf_2x = amp_at(env_freqs, env_psd, 2 * bearing_freqs.bsf_hz, tol)

        # --- Spectral Kurtosis (impulsiveness indicator) ---
        # SK = (M4/M2²) - 2 where M2, M4 are 2nd and 4th spectral moments
        # High SK indicates impulsive components (bearing faults)
        spec_norm = psd / (np.sum(psd) + 1e-12)
        m2 = np.sum((freqs - np.sum(freqs * spec_norm))**2 * spec_norm)
        m4 = np.sum((freqs - np.sum(freqs * spec_norm))**4 * spec_norm)
        spectral_kurtosis = float(m4 / (m2**2 + 1e-12) - 2.0) if m2 > 0 else 0.0

        # --- ISO 10816-3 Severity Zone ---
        # Convert acceleration to velocity RMS (approximate integration)
        # v_rms ≈ a_rms / (2πf_dominant) where f_dominant ~ shaft freq for 1×
        # ISO 10816 uses velocity in mm/s RMS
        overall_vel_rms = self._acc_to_vel_rms(x)
        iso_zone = self._iso10816_zone(overall_vel_rms)

        return VibrationResult(
            rms=rms,
            peak=peak,
            peak_to_peak=peak_to_peak,
            crest_factor=crest_factor,
            kurtosis=kurt,
            skewness=skew,
            freqs=freqs,
            psd=psd,
            psd_db=psd_db,
            env_freqs=env_freqs,
            env_psd=env_psd,
            env_psd_db=env_psd_db,
            bearing_freqs=bearing_freqs,
            bpfo_amplitude=bpfo_amp,
            bpfi_amplitude=max(bpfi_amp, bpfi_2x),
            bsf_amplitude=max(bsf_amp, bsf_2x),
            ftf_amplitude=ftf_amp,
            spectral_kurtosis=spectral_kurtosis,
            iso_severity_zone=iso_zone,
            overall_velocity_rms=overall_vel_rms,
        )

    def _acc_to_vel_rms(self, acc: np.ndarray) -> float:
        """Approximate velocity RMS from acceleration signal.

        For ISO 10816, we need velocity in mm/s.
        Simple integration: v_rms ≈ a_rms / (2π * f_char)
        where f_char is characteristic frequency (~shaft freq for 1× dominant).
        """
        a_rms = float(np.sqrt(np.mean(acc**2)))
        # Assume dominant vibration at 1× shaft frequency
        f_char = max(self.shaft_freq_hz, 10.0)  # Minimum 10 Hz
        v_rms_m_s = a_rms / (2.0 * math.pi * f_char)
        return v_rms_m_s * 1000.0  # Convert to mm/s

    def _iso10816_zone(self, vel_rms_mm_s: float) -> str:
        """Classify severity per ISO 10816-3 for machines 15-75 kW (typical).

        Zone boundaries (velocity RMS in mm/s):
        - Zone A (Good): < 2.3 mm/s
        - Zone B (Acceptable): 2.3 - 4.5 mm/s
        - Zone C (Warning): 4.5 - 7.1 mm/s
        - Zone D (Danger): > 7.1 mm/s
        """
        if vel_rms_mm_s < 2.3:
            return "A"
        elif vel_rms_mm_s < 4.5:
            return "B"
        elif vel_rms_mm_s < 7.1:
            return "C"
        else:
            return "D"

    def order_tracking(
        self,
        signal: np.ndarray,
        tacho_signal: np.ndarray,
        orders: list[float] = [1.0, 2.0, 3.0],
    ) -> dict:
        """Order tracking analysis (resample to angle domain).

        Requires tachometer signal for angle reference.
        Returns amplitude of specified orders.
        """
        # Placeholder for advanced order tracking
        # Would require angle interpolation from tacho pulses
        return {}


def demodulate_envelope(
    signal: np.ndarray,
    fs: float,
    band: tuple[float, float] = (2000.0, 5000.0),
    order: int = 4,
) -> np.ndarray:
    """Standalone envelope demodulation function.

    Args:
        signal: Input vibration signal
        fs: Sampling frequency
        band: Bandpass filter range [Hz]
        order: Filter order

    Returns:
        Envelope signal
    """
    sos = butter(order, [band[0] / (fs / 2), band[1] / (fs / 2)], btype="band", output="sos")
    filtered = sosfiltfilt(sos, signal)
    analytic = hilbert(filtered)
    envelope = np.abs(analytic)
    return envelope - np.mean(envelope)


def spectral_kurtosis(signal: np.ndarray, fs: float, nperseg: int = 256) -> tuple[np.ndarray, np.ndarray]:
    """Compute Spectral Kurtosis (SK) for impulsiveness detection.

    SK(f) = (M4(f)/M2(f)²) - 2
    where M2, M4 are spectral moments in each frequency bin.

    High SK at a frequency indicates impulsive content at that frequency.

    Returns:
        freqs: Frequency bins
        sk: Spectral kurtosis values
    """
    from scipy.signal import spectrogram

    # Short-time Fourier transform
    f, t, Sxx = spectrogram(signal, fs=fs, nperseg=nperseg, noverlap=nperseg // 2)
    # Power spectrum
    P = np.abs(Sxx)**2

    # Spectral moments per frequency bin
    M2 = np.mean(P, axis=1)
    M4 = np.mean(P**2, axis=1)

    sk = M4 / (M2**2 + 1e-12) - 2.0
    return f, sk