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

import math
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
    sensor_loss_grace_s: float = 3.0
    sensor_loss_action: str = "trip"  # "trip" | "derate" | "hold"
    sensor_loss_derate_load: float = 0.5
    unknown_decay_rate: float = 0.02  # per update tick when UNKNOWN and sensors healthy


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
        self._sensor_loss_timer: float = 0.0
        self.sensor_loss_active: bool = False

    # ---- operator actions ----------------------------------------------
    def reset(self) -> bool:
        """Clear a latched trip. Refused while the smoothed severity is still at trip level or sensors lost."""
        if self.state != SadaState.TRIP:
            return True
        if self.sensor_loss_active:
            return False
        if self.smoothed >= self.cfg.trip - self.cfg.hysteresis:
            return False
        self.state = SadaState.NORMAL
        self.reason = "RESET_BY_OPERATOR"
        return True

    def acknowledge(self) -> None:
        self.acknowledged = True

    def trip(self, reason: str = "TRIP") -> None:
        self.smoothed = 1.0
        self.fault = DiagFault.UNKNOWN
        self._enter(SadaState.TRIP, reason)

    def set_manual_load(self, load: float | None) -> None:
        if load is not None and not 0.0 <= load <= 1.0:
            raise ValueError("manual load must be within [0, 1]")
        self.manual_load = load

    # ---- main update -----------------------------------------------------
    def update(
        self,
        d: FusedDiagnosis,
        dt: float = 0.1,
        critical_sensors_ok: bool = True,
    ) -> SadaOutput:
        c = self.cfg
        if not math.isfinite(d.severity) or not math.isfinite(d.confidence):
            self.smoothed = 1.0
            self.fault = DiagFault.UNKNOWN
            self._enter(SadaState.TRIP, "TRIP_SIM_NONFINITE")

        # Sensor-health watchdog
        if not critical_sensors_ok:
            self._sensor_loss_timer += dt
            if self._sensor_loss_timer >= c.sensor_loss_grace_s:
                self.sensor_loss_active = True
                if c.sensor_loss_action == "trip":
                    if self.state != SadaState.TRIP:
                        self.smoothed = 1.0
                        self.fault = DiagFault.UNKNOWN
                        self._enter(SadaState.TRIP, "TRIP_SENSOR_LOSS")
                elif c.sensor_loss_action == "derate":
                    if self.state not in (SadaState.TRIP, SadaState.DERATE):
                        self._enter(SadaState.DERATE, "DERATE_SENSOR_LOSS")
        else:
            self._sensor_loss_timer = 0.0
            self.sensor_loss_active = False

        gated = d.confidence >= c.confidence_gate and d.fault_type not in (DiagFault.HEALTHY, DiagFault.UNKNOWN)
        target = d.severity if gated else 0.0

        if d.fault_type == DiagFault.UNKNOWN:
            if critical_sensors_ok and not self.sensor_loss_active:
                # Sensors are healthy, fault is unclassified/cleared -> decay smoothed severity
                self.smoothed = max(0.0, self.smoothed - c.unknown_decay_rate)
        elif math.isfinite(target):
            self.smoothed += c.ema_alpha * (target - self.smoothed)

        if gated and self.state != SadaState.TRIP:
            self.fault = d.fault_type

        thermal = d.per_sensor_scores.get(DiagSource.THERMAL.value, {})
        thermal_critical = bool(thermal.get("details", {}).get("critical"))
        emergency = gated and (
            (d.severity >= c.emergency_severity and d.confidence >= c.emergency_confidence)
            or (d.fault_type in (DiagFault.OVERCURRENT, DiagFault.STALL, DiagFault.PHASE_LOSS) and d.confidence >= 0.8)
            or (d.fault_type == DiagFault.OVERLOAD and d.severity >= 0.95 and d.confidence >= 0.8)
        )

        prev = self.state
        s = self.smoothed
        if self.state == SadaState.TRIP:
            pass  # latched
        elif thermal_critical:
            self._enter(SadaState.TRIP, "TRIP_THERMAL")
        elif emergency:
            trip_reason = (
                f"TRIP_{d.fault_type.value.upper()}"
                if d.fault_type in (DiagFault.OVERCURRENT, DiagFault.STALL, DiagFault.PHASE_LOSS)
                else f"TRIP_EMERGENCY_{d.fault_type.value.upper()}"
            )
            self.smoothed = 1.0
            self.fault = d.fault_type
            self._enter(SadaState.TRIP, trip_reason)
        elif s >= c.trip:
            self._enter(SadaState.TRIP, f"TRIP_{self.fault.value.upper()}")
        elif self.sensor_loss_active and c.sensor_loss_action == "derate":
            if self.state != SadaState.DERATE:
                self._enter(SadaState.DERATE, "DERATE_SENSOR_LOSS")
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

        if self.state == SadaState.NORMAL and s < c.watch - c.hysteresis and not self.sensor_loss_active:
            self.fault = DiagFault.HEALTHY

        if self.state == SadaState.TRIP:
            load = 0.0
        elif self.state == SadaState.DERATE:
            if self.sensor_loss_active and c.sensor_loss_action == "derate":
                load = c.sensor_loss_derate_load
            else:
                frac = min(1.0, (s - c.derate) / (c.trip - c.derate)) if s > c.derate else 0.0
                load = 1.0 - frac * (1.0 - c.min_load)
        else:
            load = 1.0
        manual_load = self.manual_load
        manual = manual_load is not None and self.state != SadaState.TRIP
        if manual_load is not None and manual:
            load = min(load, manual_load) if self.state == SadaState.DERATE else manual_load
        out = SadaOutput(self.state, round(load, 4), "MANUAL_OVERRIDE" if manual else self.reason,
                         self.state == SadaState.TRIP, round(s, 4), self.fault.value, manual,
                         changed=prev != self.state)
        self._last_out = out
        return out

    def _enter(self, state: SadaState, reason: str) -> None:
        self.state = state
        self.reason = reason
        self.acknowledged = False
