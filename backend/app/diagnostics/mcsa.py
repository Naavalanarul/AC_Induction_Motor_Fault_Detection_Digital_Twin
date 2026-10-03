"""diagnostics/mcsa.py — Motor Current Signature Analysis (MCSA) Pipeline.

Captures high-resolution stator current vectors (Fs >= 5000 Hz), applies flat-top
or Hann windowing before Fast Fourier Transform (FFT) and Welch Power Spectral Density
(PSD) to suppress spectral leakage around the 50/60 Hz fundamental line, and executes
automated peak detection using scipy.signal.find_peaks targeting:
    f_BRB = f_s * (1 +/- 2*k*s),  k in {1, 2, 3}
and dynamic eccentricity sidebands:
    f_ecc = f_s +/- k * f_r
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from scipy.signal import find_peaks, welch

from app.diagnostics.calibration import brb_db_to_severity, eccentricity_db_to_severity


@dataclass
class PeakMarker:
    """Detected spectral peak associated with a diagnostic signature."""

    freq_hz: float
    magnitude_db: float
    label: str
    harmonic_k: int | None = None
    expected_freq_hz: float | None = None
    deviation_hz: float | None = None


@dataclass
class MCSAResult:
    """Encapsulates spectral PSD analysis and fault marker peak detection."""

    fs: float
    fundamental_freq: float
    fundamental_mag_db: float
    slip: float
    rotor_freq_hz: float
    window: str
    freqs: np.ndarray
    psd_db: np.ndarray
    fft_freqs: np.ndarray
    fft_mag_db: np.ndarray
    peaks: list[PeakMarker] = field(default_factory=list)
    brb_peaks: list[PeakMarker] = field(default_factory=list)
    ecc_peaks: list[PeakMarker] = field(default_factory=list)
    worst_brb_sideband_db: float | None = None
    worst_ecc_sideband_db: float | None = None
    brb_fault_detected: bool = False
    eccentricity_detected: bool = False
    brb_severity: float = 0.0
    eccentricity_severity: float = 0.0


class MCSAAnalyzer:
    """Motor Current Signature Analysis (MCSA) processor."""

    def __init__(
        self,
        fs: float = 5000.0,
        window: Literal["hann", "flattop"] = "hann",
        nperseg: int = 4096,
    ):
        self.fs = fs
        self.window_type = window
        self.nperseg = nperseg

    def analyze(
        self,
        current_waveform: np.ndarray,
        nominal_supply_freq: float = 50.0,
        omega_m: float | None = None,
        pole_pairs: int = 2,
    ) -> MCSAResult:
        """Runs MCSA pipeline on a single phase current array (length >= 2048)."""
        x = np.asarray(current_waveform, dtype=np.float64)
        n = len(x)
        if n < 512:
            raise ValueError(f"waveform length too short for MCSA: {n} < 512")

        # 1. Window selection: Flat-top or Hann
        if self.window_type == "flattop":
            from scipy.signal.windows import flattop
            win = flattop(n)
        else:
            win = np.hanning(n)

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

        # 5. Rotor mechanical and electrical frequency
        if omega_m is not None and omega_m > 1.0:
            f_r = float(omega_m / (2.0 * math.pi))
            f_e = pole_pairs * f_r
            slip = max(0.001, (f_s - f_e) / f_s)
        else:
            # Estimate slip from default running point
            f_r = 1474.0 / 60.0
            slip = max(0.001, (f_s - pole_pairs * f_r) / f_s)

        # 6. Automated Peak Detection using scipy.signal.find_peaks
        rel_mag = fft_mag_db - fund_db  # Normalized dB relative to carrier (dBc)

        peak_indices, properties = find_peaks(
            rel_mag,
            height=-80.0,      # at least -80 dBc
            prominence=3.0,    # distinct prominence peak
            distance=max(1, int(self.fs / (n * 0.5) * 0.5)),
        )

        all_peaks: list[PeakMarker] = []
        brb_peaks: list[PeakMarker] = []
        ecc_peaks: list[PeakMarker] = []

        # Target BRB frequencies: f_BRB = f_s * (1 +/- 2*k*s) for k in {1, 2, 3}
        target_brb_freqs = {}
        for k in (1, 2, 3):
            f_lower = f_s * (1.0 - 2.0 * k * slip)
            f_upper = f_s * (1.0 + 2.0 * k * slip)
            if f_lower > 5.0:
                target_brb_freqs[(k, "lower")] = f_lower
            target_brb_freqs[(k, "upper")] = f_upper

        # Target Eccentricity frequencies: f_ecc = f_s +/- f_r
        target_ecc_freqs = {
            "lower": f_s - f_r,
            "upper": f_s + f_r,
        }

        tolerance_hz = max(1.2, 2.5 * (fft_freqs[1] - fft_freqs[0]))

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
                    )
                    brb_peaks.append(marker)
                    all_peaks.append(marker)
                    matched_brb = True
                    break

            if matched_brb:
                continue

            # Check Eccentricity match
            for side, f_tgt in target_ecc_freqs.items():
                if abs(p_freq - f_tgt) <= tolerance_hz:
                    label = f"Eccentricity ({side})"
                    marker = PeakMarker(
                        freq_hz=round(p_freq, 2),
                        magnitude_db=round(p_db, 2),
                        label=label,
                        expected_freq_hz=round(f_tgt, 2),
                        deviation_hz=round(abs(p_freq - f_tgt), 2),
                    )
                    ecc_peaks.append(marker)
                    all_peaks.append(marker)
                    break

        # Also perform targeted search at eccentricity sidebands if not found in general peaks
        if not ecc_peaks:
            for side, f_tgt in target_ecc_freqs.items():
                mask_ecc = (fft_freqs >= f_tgt - tolerance_hz) & (fft_freqs <= f_tgt + tolerance_hz)
                if np.any(mask_ecc):
                    local_idx = np.where(mask_ecc)[0][np.argmax(rel_mag[mask_ecc])]
                    local_p_db = float(rel_mag[local_idx])
                    # If power at target sideband exceeds -50 dBc, register it
                    if local_p_db > -50.0:
                        marker = PeakMarker(
                            freq_hz=round(float(fft_freqs[local_idx]), 2),
                            magnitude_db=round(local_p_db, 2),
                            label=f"Eccentricity ({side})",
                            expected_freq_hz=round(f_tgt, 2),
                            deviation_hz=round(abs(float(fft_freqs[local_idx]) - f_tgt), 2),
                        )
                        ecc_peaks.append(marker)
                        all_peaks.append(marker)

        worst_brb_db = max((p.magnitude_db for p in brb_peaks), default=None)
        worst_ecc_db = max((p.magnitude_db for p in ecc_peaks), default=None)
        # Threshold: if BRB sideband is greater than -45 dBc, flag fault
        brb_detected = worst_brb_db is not None and worst_brb_db > -45.0
        ecc_detected = len(ecc_peaks) > 0 and any(p.magnitude_db > -45.0 for p in ecc_peaks)
        brb_sev = brb_db_to_severity(worst_brb_db)
        ecc_sev = eccentricity_db_to_severity(worst_ecc_db)

        return MCSAResult(
            fs=self.fs,
            fundamental_freq=round(f_s, 2),
            fundamental_mag_db=round(fund_db, 2),
            slip=round(slip, 4),
            rotor_freq_hz=round(f_r, 2),
            window=self.window_type,
            freqs=psd_freqs,
            psd_db=psd_db,
            fft_freqs=fft_freqs,
            fft_mag_db=fft_mag_db,
            peaks=all_peaks,
            brb_peaks=brb_peaks,
            ecc_peaks=ecc_peaks,
            worst_brb_sideband_db=worst_brb_db,
            worst_ecc_sideband_db=worst_ecc_db,
            brb_fault_detected=brb_detected,
            eccentricity_detected=ecc_detected,
            brb_severity=round(brb_sev, 4),
            eccentricity_severity=round(ecc_sev, 4),
        )
