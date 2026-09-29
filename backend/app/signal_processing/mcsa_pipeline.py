"""signal_processing/mcsa_pipeline.py

Motor Current Signature Analysis (MCSA) Pipeline.

Executes windowed FFT (Hann/Flat-top) and Welch PSD on steady-state
stator current segments. Automatically locates and places markers on:

- BRB sidebands: f_brb = f_s * (1 ± 2k*s) for k = 1, 2, 3
- Eccentricity harmonics: f_ecc = f_s ± k * f_r
- Negative sequence components
- Harmonic distortion (THD)

Uses scipy.signal.find_peaks for automated peak detection.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from scipy.signal import find_peaks, welch
from scipy.signal.windows import flattop

from app.core_physics.fault_models import BearingGeometry


@dataclass
class PeakMarker:
    """Detected spectral peak associated with a diagnostic signature."""

    freq_hz: float
    magnitude_db: float
    label: str
    harmonic_k: int | None = None
    expected_freq_hz: float | None = None
    deviation_hz: float | None = None
    sideband_type: str | None = None  # 'lower', 'upper', 'eccentricity', 'harmonic'


@dataclass
class MCSAResult:
    """Encapsulates spectral PSD analysis and fault marker peak detection."""

    fs: float
    fundamental_freq: float
    fundamental_mag_db: float
    slip: float
    rotor_freq_hz: float
    window: str
    freqs: np.ndarray  # PSD frequencies
    psd_db: np.ndarray  # PSD in dB
    fft_freqs: np.ndarray  # FFT frequencies
    fft_mag_db: np.ndarray  # FFT magnitude in dB
    peaks: list[PeakMarker] = field(default_factory=list)
    brb_peaks: list[PeakMarker] = field(default_factory=list)
    ecc_peaks: list[PeakMarker] = field(default_factory=list)
    harmonic_peaks: list[PeakMarker] = field(default_factory=list)
    worst_brb_sideband_db: float | None = None
    brb_fault_detected: bool = False
    eccentricity_detected: bool = False
    thd_percent: float = 0.0
    negative_seq_mag_db: float | None = None


class MCSAAnalyzer:
    """Motor Current Signature Analysis (MCSA) processor."""

    def __init__(
        self,
        fs: float = 5000.0,
        window: Literal["hann", "flattop", "hamming", "blackman"] = "hann",
        nperseg: int = 4096,
        noverlap: int | None = None,
    ):
        """Initialize MCSA analyzer.

        Args:
            fs: Sampling frequency [Hz]
            window: Window type for FFT ('hann', 'flattop', 'hamming', 'blackman')
            nperseg: Length of each segment for Welch PSD
            noverlap: Number of points to overlap (default: nperseg // 2)
        """
        self.fs = fs
        self.window_type = window
        self.nperseg = nperseg
        self.noverlap = noverlap if noverlap is not None else nperseg // 2

    def _get_window(self, n: int) -> np.ndarray:
        """Get window function of length n."""
        if self.window_type == "flattop":
            return flattop(n)
        elif self.window_type == "hann":
            return np.hanning(n)
        elif self.window_type == "hamming":
            return np.hamming(n)
        elif self.window_type == "blackman":
            return np.blackman(n)
        else:
            return np.hanning(n)

    def analyze(
        self,
        current_waveform: np.ndarray,
        nominal_supply_freq: float = 50.0,
        omega_m: float | None = None,
        pole_pairs: int = 2,
        bearing_geometry: BearingGeometry | None = None,
    ) -> MCSAResult:
        """Runs MCSA pipeline on a single phase current array.

        Args:
            current_waveform: Time-domain current signal [A] (length >= 512)
            nominal_supply_freq: Nominal supply frequency [Hz]
            omega_m: Mechanical rotor speed [rad/s] (if None, estimated)
            pole_pairs: Number of pole pairs
            bearing_geometry: Bearing geometry for defect frequency calculation

        Returns:
            MCSAResult with spectral data and detected fault markers
        """
        x = np.asarray(current_waveform, dtype=np.float64)
        n = len(x)
        if n < 512:
            raise ValueError(f"waveform length too short for MCSA: {n} < 512")

        # 1. Window selection
        win = self._get_window(n)

        # 2. Windowed FFT
        x_win = (x - np.mean(x)) * win
        coherent_gain = np.sum(win) / 2.0
        fft_vals = np.fft.rfft(x_win) / max(coherent_gain, 1e-12)
        fft_freqs = np.fft.rfftfreq(n, 1.0 / self.fs)
        fft_mag = np.abs(fft_vals)
        # Avoid log(0)
        fft_mag_db = 20.0 * np.log10(np.maximum(fft_mag, 1e-12))

        # 3. Welch Power Spectral Density (PSD)
        n_seg = min(self.nperseg, n)
        psd_freqs, psd_vals = welch(
            x - np.mean(x),
            fs=self.fs,
            window=self.window_type,
            nperseg=n_seg,
            noverlap=self.noverlap,
            scaling="density",
        )
        psd_db = 10.0 * np.log10(np.maximum(psd_vals, 1e-12))

        # 4. Find fundamental supply frequency (peak near nominal 50/60 Hz)
        fund_mask = (fft_freqs >= nominal_supply_freq - 5.0) & (fft_freqs <= nominal_supply_freq + 5.0)
        if np.any(fund_mask):
            fund_idx = np.where(fund_mask)[0][np.argmax(fft_mag_db[fund_mask])]
            f_s = float(fft_freqs[fund_idx])
            fund_db = float(fft_mag_db[fund_idx])
        else:
            f_s = nominal_supply_freq
            fund_db = float(np.max(fft_mag_db))

        # 5. Rotor mechanical and electrical frequency, slip calculation
        if omega_m is not None and omega_m > 1.0:
            f_r = float(omega_m / (2.0 * math.pi))
            f_e = pole_pairs * f_r
            slip = max(0.001, (f_s - f_e) / f_s)
        else:
            # Estimate slip from default running point
            f_r = 1474.0 / 60.0
            slip = max(0.001, (f_s - pole_pairs * f_r) / f_s)

        # 6. THD calculation (harmonics up to 50th)
        thd = self._calculate_thd(fft_freqs, fft_mag_db, f_s, fund_idx if np.any(fund_mask) else -1)

        # 7. Negative sequence component (from symmetrical components)
        neg_seq_db = self._calculate_negative_sequence(fft_freqs, fft_mag, f_s)

        # 8. Automated Peak Detection using scipy.signal.find_peaks
        rel_mag = fft_mag_db - fund_db  # Normalized dB relative to carrier (dBc)

        peak_indices, properties = find_peaks(
            rel_mag,
            height=-80.0,  # at least -80 dBc
            prominence=3.0,  # distinct prominence peak
            distance=max(1, int(self.fs / n * 0.5)),
        )

        all_peaks: list[PeakMarker] = []
        brb_peaks: list[PeakMarker] = []
        ecc_peaks: list[PeakMarker] = []
        harmonic_peaks: list[PeakMarker] = []

        # Target BRB frequencies: f_BRB = f_s * (1 ± 2*k*s) for k in {1, 2, 3}
        target_brb_freqs = {}
        for k in (1, 2, 3):
            f_lower = f_s * (1.0 - 2.0 * k * slip)
            f_upper = f_s * (1.0 + 2.0 * k * slip)
            if f_lower > 5.0:
                target_brb_freqs[(k, "lower")] = f_lower
            target_brb_freqs[(k, "upper")] = f_upper

        # Target Eccentricity frequencies: f_ecc = f_s ± k * f_r for k = 1, 2
        target_ecc_freqs = {}
        for k in (1, 2):
            target_ecc_freqs[(k, "lower")] = f_s - k * f_r
            target_ecc_freqs[(k, "upper")] = f_s + k * f_r

        # Target Harmonics: k * f_s for k = 2, 3, 5, 7
        target_harmonic_freqs = {}
        for k in (2, 3, 5, 7):
            target_harmonic_freqs[k] = k * f_s

        tolerance_hz = max(1.2, 2.5 * (fft_freqs[1] - fft_freqs[0]) if len(fft_freqs) > 1 else 1.0)

        for p_idx in peak_indices:
            p_freq = float(fft_freqs[p_idx])
            p_db = float(rel_mag[p_idx])

            # Exclude carrier line fundamental itself (within 0.6 Hz of supply line)
            if abs(p_freq - f_s) < 0.6:
                continue

            # Check BRB match
            matched_brb = False
            for (k, side), f_tgt in target_brb_freqs.items():
                if abs(p_freq - f_tgt) <= tolerance_hz:
                    label = f"BRB k={k} ({side})"
                    marker = PeakMarker(
                        freq_hz=round(p_freq, 2),
                        magnitude_db=round(p_db, 2),
                        label=label,
                        harmonic_k=k,
                        expected_freq_hz=round(f_tgt, 2),
                        deviation_hz=round(abs(p_freq - f_tgt), 2),
                        sideband_type=side,
                    )
                    brb_peaks.append(marker)
                    all_peaks.append(marker)
                    matched_brb = True
                    break

            if matched_brb:
                continue

            # Check Eccentricity match
            matched_ecc = False
            for (k, side), f_tgt in target_ecc_freqs.items():
                if abs(p_freq - f_tgt) <= tolerance_hz:
                    label = f"Eccentricity k={k} ({side})"
                    marker = PeakMarker(
                        freq_hz=round(p_freq, 2),
                        magnitude_db=round(p_db, 2),
                        label=label,
                        harmonic_k=k,
                        expected_freq_hz=round(f_tgt, 2),
                        deviation_hz=round(abs(p_freq - f_tgt), 2),
                        sideband_type=side,
                    )
                    ecc_peaks.append(marker)
                    all_peaks.append(marker)
                    matched_ecc = True
                    break

            if matched_ecc:
                continue

            # Check Harmonic match
            for k, f_tgt in target_harmonic_freqs.items():
                if abs(p_freq - f_tgt) <= tolerance_hz:
                    label = f"Harmonic {k}×f_s"
                    marker = PeakMarker(
                        freq_hz=round(p_freq, 2),
                        magnitude_db=round(p_db, 2),
                        label=label,
                        harmonic_k=k,
                        expected_freq_hz=round(f_tgt, 2),
                        deviation_hz=round(abs(p_freq - f_tgt), 2),
                        sideband_type="harmonic",
                    )
                    harmonic_peaks.append(marker)
                    all_peaks.append(marker)
                    break

        # 9. Targeted search at BRB/eccentricity sidebands if not found in general peaks
        # (some peaks may not meet prominence threshold but still be significant)
        if not brb_peaks:
            for (k, side), f_tgt in target_brb_freqs.items():
                if f_tgt > 5.0 and f_tgt < self.fs / 2:
                    mask = (fft_freqs >= f_tgt - tolerance_hz) & (fft_freqs <= f_tgt + tolerance_hz)
                    if np.any(mask):
                        local_idx = np.where(mask)[0][np.argmax(rel_mag[mask])]
                        local_p_db = float(rel_mag[local_idx])
                        if local_p_db > -60.0:  # Lower threshold for targeted search
                            marker = PeakMarker(
                                freq_hz=round(float(fft_freqs[local_idx]), 2),
                                magnitude_db=round(local_p_db, 2),
                                label=f"BRB k={k} ({side})",
                                harmonic_k=k,
                                expected_freq_hz=round(f_tgt, 2),
                                deviation_hz=round(abs(float(fft_freqs[local_idx]) - f_tgt), 2),
                                sideband_type=side,
                            )
                            brb_peaks.append(marker)
                            all_peaks.append(marker)

        if not ecc_peaks:
            for (k, side), f_tgt in target_ecc_freqs.items():
                mask = (fft_freqs >= f_tgt - tolerance_hz) & (fft_freqs <= f_tgt + tolerance_hz)
                if np.any(mask):
                    local_idx = np.where(mask)[0][np.argmax(rel_mag[mask])]
                    local_p_db = float(rel_mag[local_idx])
                    if local_p_db > -50.0:
                        marker = PeakMarker(
                            freq_hz=round(float(fft_freqs[local_idx]), 2),
                            magnitude_db=round(local_p_db, 2),
                            label=f"Eccentricity k={k} ({side})",
                            harmonic_k=k,
                            expected_freq_hz=round(f_tgt, 2),
                            deviation_hz=round(abs(float(fft_freqs[local_idx]) - f_tgt), 2),
                            sideband_type=side,
                        )
                        ecc_peaks.append(marker)
                        all_peaks.append(marker)

        # 10. Fault detection thresholds
        worst_brb_db = max((p.magnitude_db for p in brb_peaks), default=None)
        # Threshold: if BRB sideband is greater than -45 dBc, flag fault
        brb_detected = worst_brb_db is not None and worst_brb_db > -45.0
        ecc_detected = len(ecc_peaks) > 0 and any(p.magnitude_db > -45.0 for p in ecc_peaks)

        return MCSAResult(
            fs=self.fs,
            fundamental_freq=round(f_s, 2),
            fundamental_mag_db=round(fund_db, 2),
            slip=round(slip, 6),
            rotor_freq_hz=round(f_r, 2),
            window=self.window_type,
            freqs=psd_freqs,
            psd_db=psd_db,
            fft_freqs=fft_freqs,
            fft_mag_db=fft_mag_db,
            peaks=all_peaks,
            brb_peaks=brb_peaks,
            ecc_peaks=ecc_peaks,
            harmonic_peaks=harmonic_peaks,
            worst_brb_sideband_db=worst_brb_db,
            brb_fault_detected=brb_detected,
            eccentricity_detected=ecc_detected,
            thd_percent=thd,
            negative_seq_mag_db=neg_seq_db,
        )

    def _calculate_thd(
        self,
        freqs: np.ndarray,
        mag_db: np.ndarray,
        f_s: float,
        fund_idx: int,
    ) -> float:
        """Calculate Total Harmonic Distortion (THD) up to 50th harmonic."""
        if fund_idx < 0:
            return 0.0

        fund_mag = 10 ** (mag_db[fund_idx] / 20.0)
        harmonic_power = 0.0

        for k in range(2, 51):
            f_harm = k * f_s
            if f_harm >= self.fs / 2:
                break
            mask = (freqs >= f_harm - 1.0) & (freqs <= f_harm + 1.0)
            if np.any(mask):
                idx = np.where(mask)[0][np.argmax(mag_db[mask])]
                harm_mag = 10 ** (mag_db[idx] / 20.0)
                harmonic_power += harm_mag**2

        if fund_mag > 0:
            thd = math.sqrt(harmonic_power) / fund_mag * 100.0
            return round(thd, 2)
        return 0.0

    def _calculate_negative_sequence(
        self,
        freqs: np.ndarray,
        mag: np.ndarray,
        f_s: float,
    ) -> float | None:
        """Estimate negative sequence component from spectral analysis.

        In a perfectly balanced system, negative sequence appears at -f_s
        (or equivalently at f_s with opposite phase rotation).
        For single-phase analysis, we look for energy at f_s that doesn't
        match the positive sequence - this is approximated here.
        """
        # For single-phase, we approximate by looking at spectral asymmetry
        # around the fundamental. This is a simplified approach.
        mask = (freqs >= f_s - 2.0) & (freqs <= f_s + 2.0)
        if np.any(mask):
            # Use spectral flatness around fundamental as proxy
            local_mag = mag[mask]
            if len(local_mag) > 1:
                flatness = np.exp(np.mean(np.log(local_mag + 1e-12))) / (np.mean(local_mag) + 1e-12)
                neg_db = 20 * np.log10(flatness + 1e-12)
                return round(neg_db, 2)
        return None


def compute_slip_from_spectrum(
    fft_freqs: np.ndarray,
    fft_mag_db: np.ndarray,
    nominal_supply_freq: float,
    pole_pairs: int,
) -> float:
    """Estimate slip directly from current spectrum by locating rotor slot harmonics.

    Rotor slot harmonics appear at: f_s ± k * f_r * (N_r / p)
    where N_r = number of rotor bars.
    """
    # This is a placeholder for advanced slip estimation
    # Would require rotor bar count knowledge
    return 0.02  # Default nominal slip
