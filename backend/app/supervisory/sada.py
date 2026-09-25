"""supervisory/sada.py

SADA supervisory layer: confidence gating -> severity smoothing -> graded
torque derate / emergency trip.

States
    NORMAL  : load 100 %
    WATCH   : smoothed severity >= 0.3, load 100 %, operator alerted
    DERATE  : smoothed severity >= 0.5, load reduced linearly to 50 % at 0.8
    TRIP    : smoothed severity >= 0.8, or thermal critical, or an immediate
              emergency (raw severity >= 0.95 with confidence >= 0.9). Latched
              until an operator reset.
Downward transitions use hysteresis so the state does not chatter.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum

from app.diagnostics.schema import DiagFault, DiagSource, FusedDiagnosis


class SadaState(str, Enum):
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    DERATE = "DERATE"
    TRIP = "TRIP"


@dataclass
class SadaConfig:
    confidence_gate: float = 0.6
    ema_alpha: float = 0.08          # per update (~10 Hz) -> ~1.2 s time constant
    watch: float = 0.3
    derate: float = 0.5
    trip: float = 0.8
    hysteresis: float = 0.05
    min_load: float = 0.5
    emergency_severity: float = 0.95
    emergency_confidence: float = 0.9


@dataclass
class SadaOutput:
    state: SadaState
    load_cmd: float
    reason_code: str
    trip: bool
    smoothed_severity: float
    fault_type: str
    manual_override: bool
    changed: bool

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"] = self.state.value
        return d


class SadaSupervisor:
    def __init__(self, config: SadaConfig | None = None):
        self.cfg = config or SadaConfig()
        self.state = SadaState.NORMAL
        self.smoothed = 0.0
        self.fault = DiagFault.HEALTHY
        self.reason = "OK"
        self.manual_load: float | None = None
        self.acknowledged = False
        self._last_out: SadaOutput | None = None

    # ---- operator actions ----------------------------------------------
    def reset(self) -> bool:
        """Clear a latched trip. Refused while the smoothed severity is still at trip level."""
        if self.state != SadaState.TRIP:
            return True
        if self.smoothed >= self.cfg.trip - self.cfg.hysteresis:
            return False
        self.state = SadaState.NORMAL
        self.reason = "RESET_BY_OPERATOR"
        return True

    def acknowledge(self) -> None:
        self.acknowledged = True

    def set_manual_load(self, load: float | None) -> None:
        if load is not None and not 0.0 <= load <= 1.0:
            raise ValueError("manual load must be within [0, 1]")
        self.manual_load = load

    # ---- main update -----------------------------------------------------
    def update(self, d: FusedDiagnosis) -> SadaOutput:
        c = self.cfg
        gated = d.confidence >= c.confidence_gate and d.fault_type not in (DiagFault.HEALTHY, DiagFault.UNKNOWN)
        target = d.severity if gated else 0.0
        if d.fault_type != DiagFault.UNKNOWN:
            self.smoothed += c.ema_alpha * (target - self.smoothed)
        if gated:
            self.fault = d.fault_type

        thermal = d.per_sensor_scores.get(DiagSource.THERMAL.value, {})
        thermal_critical = bool(thermal.get("details", {}).get("critical"))
        emergency = gated and d.severity >= c.emergency_severity and d.confidence >= c.emergency_confidence

        prev = self.state
        s = self.smoothed
        if self.state == SadaState.TRIP:
            pass  # latched
        elif thermal_critical:
            self._enter(SadaState.TRIP, "TRIP_THERMAL")
        elif emergency:
            self._enter(SadaState.TRIP, f"TRIP_EMERGENCY_{d.fault_type.value.upper()}")
        elif s >= c.trip:
            self._enter(SadaState.TRIP, f"TRIP_{self.fault.value.upper()}")
        else:
            h = c.hysteresis
            if s >= c.derate or (self.state == SadaState.DERATE and s >= c.derate - h):
                new = SadaState.DERATE
            elif s >= c.watch or (self.state in (SadaState.WATCH, SadaState.DERATE) and s >= c.watch - h):
                new = SadaState.WATCH
            else:
                new = SadaState.NORMAL
            if new != self.state:
                self._enter(new, "OK" if new == SadaState.NORMAL else f"{new.value}_{self.fault.value.upper()}")
        if self.state == SadaState.NORMAL and s < c.watch - c.hysteresis:
            self.fault = DiagFault.HEALTHY

        if self.state == SadaState.TRIP:
            load = 0.0
        elif self.state == SadaState.DERATE:
            frac = min(1.0, (s - c.derate) / (c.trip - c.derate)) if s > c.derate else 0.0
            load = 1.0 - frac * (1.0 - c.min_load)
        else:
            load = 1.0
        manual = self.manual_load is not None and self.state != SadaState.TRIP
        if manual:
            load = min(load, self.manual_load) if self.state == SadaState.DERATE else self.manual_load
        out = SadaOutput(self.state, round(load, 4), "MANUAL_OVERRIDE" if manual else self.reason,
                         self.state == SadaState.TRIP, round(s, 4), self.fault.value, manual,
                         changed=prev != self.state)
        self._last_out = out
        return out

    def _enter(self, state: SadaState, reason: str) -> None:
        self.state = state
        self.reason = reason
        self.acknowledged = False
