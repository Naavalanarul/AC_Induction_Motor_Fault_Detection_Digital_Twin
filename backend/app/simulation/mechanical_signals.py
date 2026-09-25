"""simulation/mechanical_signals.py

Vibration (tri-axial accelerometer), acoustic and thermal signal generators.

They are driven by the plant's shaft angle/speed and by the shared `FaultState`,
so a bearing fault appears in vibration *and* acoustic (same impulse instants)
*and* as a faint friction-torque signature in the current.

Bearing geometry: SKF 6205-2RS deep-groove ball bearing (9 balls, d = 7.94 mm,
D = 39.04 mm, contact angle 0). The defect-frequency multiples below are the
ones published with the Case Western Reserve University (CWRU) bearing dataset
for this bearing. Re-derive them if you use a different bearing.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import lfilter

from app.simulation.faults import BearingDefect, FaultState

# Defect frequencies as multiples of shaft rotation frequency fr (CWRU, 6205-2RS)
BPFI = 5.4152
BPFO = 3.5848
BSF = 2.3357
FTF = 0.39828
DEFECT_ORDER = {BearingDefect.IR: BPFI, BearingDefect.OR: BPFO, BearingDefect.BALL: 2.0 * BSF}

VIB_FS = 12800.0
ACOUSTIC_FS = 12800.0


def _impulse_response(fs: float, f_res: float, damping: float, duration: float = 0.006) -> np.ndarray:
    t = np.arange(int(duration * fs)) / fs
    return np.exp(-damping * t) * np.sin(2 * math.pi * f_res * t)


class _OverlapAdd:
    """Streaming convolution with carry-over tail between chunks."""

    def __init__(self, kernel: np.ndarray):
        self.k = kernel
        self.tail = np.zeros(len(kernel) - 1)

    def __call__(self, x: np.ndarray) -> np.ndarray:
        y = np.convolve(x, self.k)
        n = len(x)
        y[: len(self.tail)] += self.tail
        self.tail = y[n:].copy()
        return y[:n]


def interp_shaft(t_elec: np.ndarray, theta_m: np.ndarray, omega_m: np.ndarray, t0: float, n: int, fs: float):
    """Resample shaft angle/speed from the electrical grid to another sample grid."""
    t = t0 + np.arange(1, n + 1) / fs
    return t, np.interp(t, t_elec, theta_m), np.interp(t, t_elec, omega_m)


class VibrationGenerator:
    """Tri-axial acceleration [m/s^2]: x,y radial (y = load zone), z axial."""

    def __init__(self, fs: float = VIB_FS, seed: int | None = None, noise_rms: float = 0.05):
        self.fs = fs
        self.rng = np.random.default_rng(seed)
        self.noise_rms = noise_rms
        self._bearing = {d: _OverlapAdd(_impulse_response(fs, 3000.0, 600.0)) for d in BearingDefect}
        self._last_count = {d: None for d in BearingDefect}

    def generate(self, theta: np.ndarray, omega: np.ndarray, supply_freq: float, load_frac: float,
                 faults: FaultState) -> np.ndarray:
        n = len(theta)
        out = self.rng.normal(0.0, self.noise_rms, size=(3, n))
        speed_ratio = np.clip(omega / 157.0, 0.0, 1.2)
        th_e = 2 * math.pi * 2 * supply_freq * (np.arange(n) / self.fs)  # 2f electromagnetic
        # Healthy baseline: small residual 1x plus 2f magnetic vibration proportional to load
        out[0] += 0.04 * speed_ratio * np.cos(theta)
        out[1] += 0.04 * speed_ratio * np.sin(theta)
        out[:2] += 0.05 * (0.3 + load_frac) * speed_ratio * np.sin(th_e + self.rng.uniform(0, 2 * math.pi))

        unb = faults.unbalance
        if unb:
            a = 1.5 * unb * speed_ratio**2
            out[0] += a * np.cos(theta)
            out[1] += a * np.sin(theta)
        mis = faults.misalignment
        if mis:
            a = 1.2 * mis * speed_ratio
            out[0] += a * np.cos(2 * theta) + 0.3 * a * np.cos(theta)
            out[1] += a * np.sin(2 * theta) + 0.3 * a * np.sin(theta)
            out[2] += 1.0 * a * np.cos(theta + 0.4) + 0.5 * a * np.cos(2 * theta)

        for defect, order in DEFECT_ORDER.items():
            sev = faults.bearing(defect)
            ring = self._bearing[defect]
            if not sev:
                if self._last_count[defect] is not None:
                    ring(np.zeros(n))  # flush tail
                self._last_count[defect] = None
                continue
            count = np.floor(order * theta / (2 * math.pi))
            prev = self._last_count[defect]
            hits = np.diff(np.concatenate([[count[0] if prev is None else prev], count])) > 0
            self._last_count[defect] = count[-1]
            amp = (2.0 + 8.0 * sev) * speed_ratio**2
            if defect == BearingDefect.IR:
                mod = 0.55 + 0.45 * np.cos(theta)           # defect passes through load zone at fr
            elif defect == BearingDefect.BALL:
                mod = 0.55 + 0.45 * np.cos(FTF * theta)     # ball carried by cage at FTF
            else:
                mod = np.ones(n)                            # stationary outer race in load zone
            pulses = hits * amp * mod * self.rng.uniform(0.8, 1.2, n)
            sig = ring(pulses)
            out[1] += sig
            out[0] += 0.5 * sig
            out[2] += 0.2 * sig
        return out


class AcousticGenerator:
    """Microphone sound pressure [Pa]: hum, fan broadband noise, impulsive bursts."""

    def __init__(self, fs: float = ACOUSTIC_FS, seed: int | None = None):
        self.fs = fs
        self.rng = np.random.default_rng(seed)
        self._burst = _OverlapAdd(_impulse_response(fs, 4800.0, 1200.0, duration=0.004))
        self._fan_state = np.zeros(1)
        self._last_count = {d: None for d in BearingDefect}
        self._t = 0.0

    def generate(self, theta: np.ndarray, omega: np.ndarray, supply_freq: float, load_frac: float,
                 faults: FaultState) -> np.ndarray:
        n = len(theta)
        t = self._t + np.arange(n) / self.fs
        self._t += n / self.fs
        speed_ratio = np.clip(omega / 157.0, 0.0, 1.2)
        # Magnetic hum at 2f and harmonics
        hum = sum((0.02 / k) * (0.4 + load_frac) * np.sin(2 * math.pi * 2 * supply_freq * k * t) for k in (1, 2, 3))
        # Fan: low-pass filtered broadband noise scaled with speed^2
        white = self.rng.normal(0.0, 1.0, n)
        fan, self._fan_state = lfilter([0.15], [1.0, -0.85], white, zi=self._fan_state)
        sig = hum + 0.05 * speed_ratio**2 * fan + self.rng.normal(0.0, 0.004, n)
        sig += 0.01 * faults.unbalance * speed_ratio * np.sin(theta)
        sig += 0.01 * faults.misalignment * speed_ratio * np.sin(2 * theta)
        pulses = np.zeros(n)
        for defect, order in DEFECT_ORDER.items():
            sev = faults.bearing(defect)
            if not sev:
                self._last_count[defect] = None
                continue
            count = np.floor(order * theta / (2 * math.pi))
            prev = self._last_count[defect]
            hits = np.diff(np.concatenate([[count[0] if prev is None else prev], count])) > 0
            self._last_count[defect] = count[-1]
            pulses += hits * (0.1 + 0.4 * sev) * speed_ratio**2 * self.rng.uniform(0.7, 1.3, n)
        sig += self._burst(pulses)
        return sig


class ThermalModel:
    """First-order (RC) winding temperature model.

    C dT/dt = P_loss - (T - T_amb) / R_th

    A real 1.5 kW TEFC motor has a thermal time constant of tens of minutes;
    the default here (`tau_s`) is deliberately shortened so the demo shows
    thermal behaviour within minutes. Set it to your motor's value.
    """

    def __init__(self, t_ambient: float = 25.0, r_th: float = 0.35, tau_s: float = 180.0):
        self.t_amb = t_ambient
        self.r_th = r_th
        self.c_th = tau_s / r_th
        self.temp = t_ambient

    def step(self, dt: float, p_loss: float) -> float:
        d = (p_loss - (self.temp - self.t_amb) / self.r_th) / self.c_th
        self.temp += d * dt
        return self.temp
