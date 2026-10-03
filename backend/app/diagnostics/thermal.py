"""diagnostics/thermal.py — threshold + rate-of-rise check + thermal twin residual.

Default limits derive from motor insulation class (e.g. Class F: 120/145 °C or 110/140 °C).
Rate of rise threshold is scaled dynamically to the motor's thermal model (tau_s and delta_T_rated)
so that fast compressed demo warm-up does not trigger false overheating alarms while real thermal
runaway, severe overload, or cooling loss is reliably flagged.
"""

from __future__ import annotations

from collections import deque

from app.diagnostics.schema import ChannelVerdict, DiagFault, DiagSource
from app.simulation.params import MotorParams


class ThermalDiagnostic:
    def __init__(
        self,
        warn_c: float = 110.0,
        trip_c: float = 140.0,
        max_rise_c_per_min: float | None = None,
        rate_window_s: float = 10.0,
        r_th: float = 0.35,
        tau_s: float = 180.0,
        t_ambient: float = 25.0,
        rated_current: float = 3.6,
        params: MotorParams | None = None,
    ):
        if params is not None:
            self.warn_c = getattr(params, "warn_c", warn_c) or warn_c
            self.trip_c = getattr(params, "trip_c", trip_c) or trip_c
            self.r_th = params.get_thermal_resistance()
            self.tau_s = getattr(params, "tau_s", tau_s)
            self.t_ambient = getattr(params, "t_ambient", t_ambient)
            self.rated_current = params.rated_current
        else:
            self.warn_c = warn_c
            self.trip_c = trip_c
            self.r_th = r_th
            self.tau_s = tau_s
            self.t_ambient = t_ambient
            self.rated_current = rated_current

        self.rate_window_s = rate_window_s
        self._hist: deque[tuple[float, float]] = deque()

        # Dynamic max rise: normal full-load warm-up rate from ambient to warn_c is:
        # dT/dt_max_normal = (warn_c - t_ambient) / tau_s.
        # Allow 30% margin for transient overload / peak starting losses.
        max_normal_rise = 1.30 * ((self.warn_c - self.t_ambient) / max(1.0, self.tau_s)) * 60.0
        if max_rise_c_per_min is not None:
            self.max_rise = max_rise_c_per_min
        else:
            self.max_rise = max(8.0, max_normal_rise)

        # Thermal twin observer state
        self.twin_temp: float = self.t_ambient
        self._last_t: float | None = None
        self.c_th: float = max(1e-3, self.tau_s / max(1e-4, self.r_th))
        # Expected rated loss in steady-state to reach rated temperature rise (~70-80 K)
        delta_t_rated = max(10.0, min(self.warn_c - self.t_ambient, 80.0))
        self.rated_loss: float = delta_t_rated / max(1e-4, self.r_th)

    def update(
        self,
        t: float,
        temp_c: float,
        i_rms: float | None = None,
        dt: float | None = None,
    ) -> ChannelVerdict:
        if self._last_t is None:
            if temp_c <= self.t_ambient + 10.0:
                self.twin_temp = temp_c
            step_dt = 0.1
        else:
            step_dt = dt if dt is not None else max(0.001, t - self._last_t)
        self._last_t = t

        # Update thermal twin observer if current is provided
        if i_rms is not None and self.rated_current > 0:
            load_factor = i_rms / self.rated_current
            # Copper losses scale with I^2, iron/mechanical losses ~ 20%
            p_loss = self.rated_loss * (0.2 + 0.8 * (load_factor**2))
        else:
            # Estimate from current steady-state
            p_loss = (self.twin_temp - self.t_ambient) / self.r_th

        # Evolve twin observer
        d_twin = (p_loss - (self.twin_temp - self.t_ambient) / self.r_th) / self.c_th
        self.twin_temp += d_twin * step_dt

        # Rate of rise tracking
        self._hist.append((t, temp_c))
        while self._hist and t - self._hist[0][0] > self.rate_window_s:
            self._hist.popleft()
        t0, c0 = self._hist[0]
        rate = (temp_c - c0) / (t - t0) * 60.0 if t - t0 > 1.0 else 0.0

        # Thermal residual: measured temp vs expected twin temp
        thermal_residual = temp_c - self.twin_temp

        details = {
            "temp_c": round(temp_c, 2),
            "twin_temp_c": round(self.twin_temp, 2),
            "thermal_residual_c": round(thermal_residual, 2),
            "rise_c_per_min": round(rate, 2),
            "max_rise_threshold": round(self.max_rise, 2),
            "critical": temp_c >= self.trip_c,
        }

        # 1. Absolute trip limit
        if temp_c >= self.trip_c:
            return ChannelVerdict(DiagSource.THERMAL, DiagFault.OVERHEATING, 0.99, 1.0, True, details)

        # 2. Absolute warn limit
        if temp_c >= self.warn_c:
            sev = min(1.0, 0.5 + 0.5 * (temp_c - self.warn_c) / max(1.0, self.trip_c - self.warn_c))
            return ChannelVerdict(DiagSource.THERMAL, DiagFault.OVERHEATING, 0.95, sev, True, details)

        # 3. Cooling failure / thermal residual anomaly:
        # If current is measured (load is known) and measured temp significantly exceeds expected twin temp
        if i_rms is not None and thermal_residual > 25.0 and temp_c > (self.t_ambient + 20.0):
            sev = min(0.65, 0.25 + 0.40 * (thermal_residual - 25.0) / 25.0)
            return ChannelVerdict(DiagSource.THERMAL, DiagFault.OVERHEATING, 0.85, sev, True, details)

        # 4. Rate-of-rise threshold (scaled to motor thermal model):
        # Only triggers if rate exceeds the calibrated max_rise threshold AND temp is warm (> 60 °C)
        if rate > self.max_rise and temp_c > 60.0:
            sev = min(0.5, 0.2 + 0.3 * (rate - self.max_rise) / max(1.0, self.max_rise))
            return ChannelVerdict(DiagSource.THERMAL, DiagFault.OVERHEATING, 0.75, sev, True, details)

        return ChannelVerdict(DiagSource.THERMAL, DiagFault.HEALTHY, 0.9, 0.0, True, details)
