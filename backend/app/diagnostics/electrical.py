"""diagnostics/electrical.py

Electrical diagnostic by the digital-twin current-residual method (no ML).

A frozen-parameter healthy twin runs alongside the measured motor, driven by the
measured voltage and measured speed. The residual r = i_measured - i_twin is ~0
for a healthy machine (only sensor noise), and structured for a faulty one:

* FD (fault detection index)   = RMS|r| / RMS|i|
* FL (fault localization index)= per-phase residual RMS, normalized by its mean;
                                  a phase with FL >> 1 localizes a winding fault.
* Fault type is then classified from where the residual energy sits in the
  space-vector spectrum: (1 +/- 2s)f sidebands -> broken rotor bar,
  f +/- f_r -> eccentricity,
  a localized phase with negative-sequence content -> inter-turn short.

Thresholds were tuned against this project's simulator only. They must be
re-tuned for real hardware (noise floor, parameter mismatch).
"""

from __future__ import annotations

import math
from collections import deque

import numpy as np

from app.diagnostics.schema import ChannelVerdict, DiagFault, DiagSource
from app.simulation.params import MotorParams
from app.simulation.plant import HealthyTwinObserver, abc_to_alphabeta, alphabeta_to_abc

FD_THRESHOLD = 0.015     # 1.5 % of stator current
FD_FULL_SCALE = 0.15     # FD at which severity saturates to 1
FL_THRESHOLD = 1.25


class ElectricalResidualDiagnostic:
    def __init__(self, params: MotorParams, fs: float, window_s: float = 2.0, settle_s: float = 1.0):
        self.params = params
        self.fs = fs
        self.twin = HealthyTwinObserver(params, fs)
        self.n_window = int(window_s * fs)
        self.settle_samples = int(settle_s * fs)
        self._seen = 0
        self._buf: deque[np.ndarray] = deque()
        self._buf_len = 0
        self.last_residual_abc: np.ndarray | None = None

    def reset(self) -> None:
        self.twin.reset()
        self._buf.clear()
        self._buf_len = 0
        self._seen = 0

    def update(self, i_abc: np.ndarray, u_abc: np.ndarray, omega_m: np.ndarray, supply_freq: float) -> ChannelVerdict:
        """Feed one chunk of measured current, voltage, mechanical speed (rad/s, same fs)."""
        ua, ub = abc_to_alphabeta(u_abc)
        ia, ib = abc_to_alphabeta(i_abc)
        pa, pb = self.twin.run(ua, ub, omega_m * self.params.pole_pairs)
        block = np.vstack([ia, ib, ia - pa, ib - pb, omega_m])
        self._buf.append(block)
        self._buf_len += block.shape[1]
        while self._buf_len - self._buf[0].shape[1] >= self.n_window:
            self._buf_len -= self._buf.popleft().shape[1]
        self._seen += block.shape[1]
        self.last_residual_abc = alphabeta_to_abc(ia - pa, ib - pb)

        if self._seen < self.settle_samples + self.n_window // 2:
            return ChannelVerdict(DiagSource.ELECTRICAL_RESIDUAL, DiagFault.UNKNOWN, 0.0, 0.0, False,
                                  {"reason": "twin settling"})
        data = np.hstack(self._buf)[:, -self.n_window:]
        return self.analyze(data, supply_freq)

    def analyze(self, data: np.ndarray, f: float) -> ChannelVerdict:
        ia, ib, ra, rb, wm = data
        i_rms = math.sqrt(float(np.mean(ia**2 + ib**2)))
        if i_rms < 0.5:  # motor de-energized (e.g. tripped): no meaningful residual
            return ChannelVerdict(DiagSource.ELECTRICAL_RESIDUAL, DiagFault.UNKNOWN, 0.0, 0.0, False,
                                  {"reason": "motor de-energized"})
        r_rms = math.sqrt(float(np.mean(ra**2 + rb**2)))
        fd = r_rms / i_rms
        r_abc = alphabeta_to_abc(ra, rb)
        phase_rms = np.sqrt(np.mean(r_abc**2, axis=1))
        fl = phase_rms / max(float(np.mean(phase_rms)), 1e-12)
        worst = int(np.argmax(fl))

        # Space-vector spectrum of the residual
        n = len(ra)
        win = np.hanning(n)
        spec = np.fft.fftshift(np.fft.fft((ra + 1j * rb) * win)) / (np.sum(win) / 2)
        freqs = np.fft.fftshift(np.fft.fftfreq(n, 1.0 / self.fs))
        df = freqs[1] - freqs[0]
        fr = float(np.mean(wm)) / (2 * math.pi)
        slip = max(0.0, (f - self.params.pole_pairs * fr) / f)

        def e(freq: float, bw: float = 1.0) -> float:
            m = np.abs(freqs - freq) <= max(bw, df)
            return float(np.sum(np.abs(spec[m]) ** 2))

        sb = 2 * slip * f
        energies = {
            "brb": e(f - sb) + e(f + sb) if sb > 1.5 * df else 0.0,
            "fund": e(f),
            "neg": e(-f),
            "ecc_dyn": e(f - fr) + e(f + fr),
                    }
        total = sum(energies.values()) + 1e-12
        details = {
            "FD": round(fd, 5), "FL": [round(float(x), 3) for x in fl], "FL_phase": "abc"[worst],
            "slip": round(slip, 4), "residual_rms_A": round(r_rms, 4),
            "energy_share": {k: round(v / total, 3) for k, v in energies.items()},
        }
        if fd < FD_THRESHOLD:
            conf = min(1.0, 0.6 + 0.4 * (1 - fd / FD_THRESHOLD))
            return ChannelVerdict(DiagSource.ELECTRICAL_RESIDUAL, DiagFault.HEALTHY, conf, 0.0, True, details)

        severity = float(min(1.0, (fd - FD_THRESHOLD) / (FD_FULL_SCALE - FD_THRESHOLD)))
        share = {k: v / total for k, v in energies.items()}
        localized = fl[worst] > FL_THRESHOLD
        if localized and share["neg"] + share["fund"] > 0.5:
            fault, conf = DiagFault.INTERTURN_SHORT, min(1.0, 0.5 + (fl[worst] - 1.0))
        elif share["ecc_dyn"] > max(share["brb"], share["fund"]):
            fault, conf = DiagFault.ECCENTRICITY, share["ecc_dyn"] * 1.5
        elif share["brb"] + share["fund"] > 0.5 and not localized:
            fault, conf = DiagFault.BROKEN_ROTOR_BAR, share["brb"] + 0.5 * share["fund"]
        else:
            fault, conf = DiagFault.UNKNOWN, 0.4
        conf = float(max(0.0, min(1.0, conf)) * min(1.0, fd / (2 * FD_THRESHOLD)))
        return ChannelVerdict(DiagSource.ELECTRICAL_RESIDUAL, fault, conf, severity, True, details)
