"""diagnostics/supply.py — supply-side (voltage) anomaly detection.

Distinguishes supply problems from motor faults. Limits follow commonly cited
EN 50160 values (voltage unbalance <= 2 %, THD <= 8 %) and a 0.9 pu sag level;
severity is capped at 0.75 so a supply problem can derate but never trip the
motor on its own (tripping on supply faults is left to protection relays);
verify against the edition of the standard that applies to you.
"""

from __future__ import annotations

import math

import numpy as np

from app.diagnostics.schema import ChannelVerdict, DiagFault, DiagSource

A = np.exp(2j * math.pi / 3)


class SupplyDiagnostic:
    def __init__(self, rated_phase_peak: float, vuf_limit: float = 0.02, thd_limit: float = 0.08, sag_limit: float = 0.9):
        self.v_rated = rated_phase_peak
        self.vuf_limit, self.thd_limit, self.sag_limit = vuf_limit, thd_limit, sag_limit

    def analyze(self, u_abc: np.ndarray, fs: float, f: float) -> ChannelVerdict:
        n = u_abc.shape[1]
        t = np.arange(n) / fs
        ph = [2.0 * np.dot(u, np.exp(-2j * math.pi * f * t)) / n for u in u_abc]
        va, vb, vc = ph
        v_pos = abs(va + A * vb + A * A * vc) / 3
        v_neg = abs(va + A * A * vb + A * vc) / 3
        if v_pos < 0.05 * self.v_rated:
            return ChannelVerdict(DiagSource.SUPPLY, DiagFault.UNKNOWN, 0.0, 0.0, False, {"reason": "supply off"})
        vuf = float(v_neg / v_pos)
        harm = [abs(2.0 * np.dot(u_abc[0], np.exp(-2j * math.pi * k * f * t)) / n) for k in range(2, 14)]
        thd = float(math.sqrt(sum(h * h for h in harm)) / abs(va))
        pu = float(v_pos / self.v_rated)
        details = {"vuf": round(vuf, 4), "thd": round(thd, 4), "v_pos_pu": round(pu, 4)}
        sag_excess = float((1.0 - pu) / (1.0 - self.sag_limit))
        excess = float(max(vuf / self.vuf_limit, thd / self.thd_limit, sag_excess))
        if excess >= 1.0:
            fault_type = (
                DiagFault.VOLTAGE_SAG
                if (sag_excess >= excess - 1e-6 and pu < self.sag_limit)
                else DiagFault.SUPPLY_ANOMALY
            )
            return ChannelVerdict(
                DiagSource.SUPPLY,
                fault_type,
                float(min(1.0, 0.6 + 0.2 * excess)),
                float(min(0.75, 0.3 + 0.15 * (excess - 1))),
                True,
                details,
            )
        return ChannelVerdict(DiagSource.SUPPLY, DiagFault.HEALTHY, 0.9, 0.0, True, details)
