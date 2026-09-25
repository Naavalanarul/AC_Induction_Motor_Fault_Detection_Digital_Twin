"""diagnostics/thermal.py — threshold + rate-of-rise check (no ML).

Default limits assume class F insulation (155 degC hot-spot rating). Adjust
`warn_c`/`trip_c` for your insulation class and sensor placement.
"""

from __future__ import annotations

from collections import deque

from app.diagnostics.schema import ChannelVerdict, DiagFault, DiagSource


class ThermalDiagnostic:
    def __init__(self, warn_c: float = 110.0, trip_c: float = 140.0, max_rise_c_per_min: float = 8.0,
                 rate_window_s: float = 10.0):
        self.warn_c, self.trip_c = warn_c, trip_c
        self.max_rise = max_rise_c_per_min
        self.rate_window_s = rate_window_s
        self._hist: deque[tuple[float, float]] = deque()

    def update(self, t: float, temp_c: float) -> ChannelVerdict:
        self._hist.append((t, temp_c))
        while self._hist and t - self._hist[0][0] > self.rate_window_s:
            self._hist.popleft()
        t0, c0 = self._hist[0]
        rate = (temp_c - c0) / (t - t0) * 60.0 if t - t0 > 1.0 else 0.0
        details = {"temp_c": round(temp_c, 2), "rise_c_per_min": round(rate, 2), "critical": temp_c >= self.trip_c}
        if temp_c >= self.warn_c:
            sev = min(1.0, 0.5 + 0.5 * (temp_c - self.warn_c) / (self.trip_c - self.warn_c))
            return ChannelVerdict(DiagSource.THERMAL, DiagFault.OVERHEATING, 0.95, sev, True, details)
        if rate > self.max_rise and temp_c > 60.0:
            sev = min(0.5, 0.2 + 0.3 * (rate - self.max_rise) / self.max_rise)
            return ChannelVerdict(DiagSource.THERMAL, DiagFault.OVERHEATING, 0.7, sev, True, details)
        return ChannelVerdict(DiagSource.THERMAL, DiagFault.HEALTHY, 0.9, 0.0, True, details)
