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

from app.diagnostics.fusion import SUPPLY_DOMAIN
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

        candidates: list[dict] = []
        if d.fault_type not in (DiagFault.HEALTHY, DiagFault.UNKNOWN):
            candidates.append({
                "fault_type": d.fault_type,
                "confidence": d.confidence,
                "severity": d.severity,
            })
        for sec in (d.secondary or []):
            ft_raw = sec.get("fault_type", "")
            try:
                ft_enum = DiagFault(ft_raw)
            except (ValueError, KeyError):
                continue
            if ft_enum not in (DiagFault.HEALTHY, DiagFault.UNKNOWN):
                candidates.append({
                    "fault_type": ft_enum,
                    "confidence": float(sec.get("confidence", 0.0)),
                    "severity": float(sec.get("severity", 0.0)),
                })

        credible = [c_cand for c_cand in candidates if c_cand["confidence"] >= c.confidence_gate]

        thermal = d.per_sensor_scores.get(DiagSource.THERMAL.value, {})
        thermal_critical = bool(thermal.get("details", {}).get("critical"))

        def _is_emergency_candidate(c_item: dict) -> bool:
            f_type = c_item["fault_type"]
            f_sev = c_item["severity"]
            f_conf = c_item["confidence"]
            return bool(
                (f_sev >= c.emergency_severity and f_conf >= c.emergency_confidence)
                or (f_type in (DiagFault.OVERCURRENT, DiagFault.STALL, DiagFault.PHASE_LOSS) and f_conf >= 0.8)
                or (f_type == DiagFault.OVERLOAD and f_sev >= 0.95 and f_conf >= 0.8)
            )

        emergency_candidates = [c_cand for c_cand in credible if _is_emergency_candidate(c_cand)]
        emergency = bool(emergency_candidates)
        emergency_fault: DiagFault | None = None
        if emergency:
            emergency_worst = max(
                emergency_candidates,
                key=lambda c_cand: (round(c_cand["severity"], 4), round(c_cand["confidence"], 4)),
            )
            emergency_fault = emergency_worst["fault_type"]

        if credible:
            worst = max(
                credible,
                key=lambda c_cand: (
                    1 if _is_emergency_candidate(c_cand) else 0,
                    1 if c_cand["fault_type"] not in SUPPLY_DOMAIN else 0,
                    round(c_cand["severity"], 4),
                    round(c_cand["confidence"], 4),
                ),
            )
            target = worst["severity"]
            if self.state != SadaState.TRIP:
                self.fault = worst["fault_type"]
        else:
            target = 0.0

        if not credible:
            if d.fault_type == DiagFault.UNKNOWN:
                if critical_sensors_ok and not self.sensor_loss_active:
                    # Sensors are healthy, fault is unclassified/cleared -> decay smoothed severity
                    self.smoothed = max(0.0, self.smoothed - c.unknown_decay_rate)
            elif math.isfinite(target):
                self.smoothed += c.ema_alpha * (target - self.smoothed)
        elif math.isfinite(target):
            self.smoothed += c.ema_alpha * (target - self.smoothed)

        prev = self.state
        s = self.smoothed
        if self.state == SadaState.TRIP:
            pass  # latched
        elif thermal_critical:
            self._enter(SadaState.TRIP, "TRIP_THERMAL")
        elif emergency and emergency_fault is not None:
            trip_reason = (
                f"TRIP_{emergency_fault.value.upper()}"
                if emergency_fault in (DiagFault.OVERCURRENT, DiagFault.STALL, DiagFault.PHASE_LOSS)
                else f"TRIP_EMERGENCY_{emergency_fault.value.upper()}"
            )
            self.smoothed = 1.0
            self.fault = emergency_fault
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
