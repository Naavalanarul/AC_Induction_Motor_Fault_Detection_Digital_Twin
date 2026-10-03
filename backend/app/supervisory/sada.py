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
    # P0-6: Trip latching & reset guards
    cooldown_s: float = 5.0           # Minimum off-time cooldown before reset
    warn_temp_c: float = 130.0        # Stator warning temperature limit (Class F)
    max_reset_attempts: int = 3       # Max allowed restarts within window
    reset_window_s: float = 600.0     # 10 minute restart window
    # P1-1: Anti-hunting limit cycle protection
    derate_min_dwell_s: float = 5.0   # Minimum dwell time in DERATE before upward recovery
    ramp_down_rate: float = 0.8       # Max load decrease per second (fast ramp down on fault)
    ramp_up_rate: float = 0.05        # Max load increase per second (slow ramp up on recovery)


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
    latched_fault: str | None = None
    latched_severity: float | None = None
    latched_temp: float | None = None
    trip_time: float | None = None
    lockout: bool = False

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
        # P0-6 Latched trip evidence & reset tracking
        self.latched_fault: DiagFault | None = None
        self.latched_severity: float | None = None
        self.latched_temp: float | None = None
        self.trip_time: float | None = None
        self.current_time: float = 0.0
        self.current_temp: float = 25.0
        self.reset_timestamps: list[float] = []
        self.lockout: bool = False
        self.lockout_reason: str | None = None
        self.last_reset_error: str | None = None
        # P1-1 Limit cycle protection & load rate-limiting
        self._derate_dwell_timer: float = 0.0
        self._current_load_cmd: float = 1.0

    # ---- operator actions ----------------------------------------------
    def can_reset(
        self,
        t: float | None = None,
        forced_reason: str | None = None,
        current_temp: float | None = None,
    ) -> tuple[bool, str]:
        """Check whether a latched trip can be safely reset."""
        if self.state != SadaState.TRIP:
            return True, "NOT_TRIPPED"

        now = t if t is not None else self.current_time

        # 1. Lockout check (restart-attempt limiting)
        self.reset_timestamps = [ts for ts in self.reset_timestamps if (now - ts) <= self.cfg.reset_window_s]
        if self.lockout or len(self.reset_timestamps) >= self.cfg.max_reset_attempts:
            self.lockout = True
            msg = (
                f"LOCKOUT: exceeded {self.cfg.max_reset_attempts} restarts within "
                f"{self.cfg.reset_window_s:.0f}s"
            )
            return False, msg

        # 2. Critical sensor loss
        if self.sensor_loss_active:
            return False, "SENSOR_LOSS_ACTIVE: critical sensors offline"

        # 3. Minimum off-time cooldown check (t_cooldown >= 5.0 s)
        if self.trip_time is not None:
            elapsed = now - self.trip_time
            if elapsed < self.cfg.cooldown_s:
                return False, f"COOLDOWN_ACTIVE: elapsed {elapsed:.1f}s < minimum {self.cfg.cooldown_s:.1f}s"

        # 4. Temperature check: below warn_temp_c - 5.0 C
        temp = current_temp if current_temp is not None else self.current_temp
        if temp is not None and temp >= (self.cfg.warn_temp_c - 5.0):
            if not forced_reason:
                return False, f"THERMAL_HIGH: temperature {temp:.1f}°C >= safe limit {self.cfg.warn_temp_c - 5.0:.1f}°C"

        # 5. Fault clearance check
        if self.smoothed >= self.cfg.trip - self.cfg.hysteresis:
            if not forced_reason:
                return False, f"FAULT_ACTIVE: smoothed severity {self.smoothed:.2f} still at trip level"

        return True, "OK"

    def reset(
        self,
        t: float | None = None,
        forced_reason: str | None = None,
        current_temp: float | None = None,
    ) -> bool:
        """Clear a latched trip with cooldown, thermal guard, fault clearance, and restart limiting."""
        can, msg = self.can_reset(t=t, forced_reason=forced_reason, current_temp=current_temp)
        if not can:
            self.last_reset_error = msg
            return False

        if self.state == SadaState.TRIP:
            now = t if t is not None else self.current_time
            self.reset_timestamps.append(now)
            self.state = SadaState.NORMAL
            self.reason = f"RESET_BY_OPERATOR ({forced_reason})" if forced_reason else "RESET_BY_OPERATOR"
            self.acknowledged = True
            self.last_reset_error = None
            self._current_load_cmd = 1.0
            self._derate_dwell_timer = 0.0
            if self.smoothed >= self.cfg.trip - self.cfg.hysteresis and forced_reason:
                self.smoothed = 0.0
            return True
        return True

    def clear_lockout(self) -> None:
        """Explicitly clear restart lockout and reset history."""
        self.lockout = False
        self.lockout_reason = None
        self.reset_timestamps.clear()

    def acknowledge(self) -> None:
        self.acknowledged = True

    def trip(self, reason: str = "TRIP", t: float | None = None) -> None:
        self.smoothed = 1.0
        self.fault = DiagFault.UNKNOWN
        self._enter(SadaState.TRIP, reason, t=t)

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
        current_temp: float | None = None,
    ) -> SadaOutput:
        c = self.cfg
        self.current_time = d.t if hasattr(d, "t") and d.t > 0 else (self.current_time + dt)
        if current_temp is not None:
            self.current_temp = current_temp
        else:
            th_score = d.per_sensor_scores.get(DiagSource.THERMAL.value, {})
            det = th_score.get("details", {})
            if "stator_temp" in det:
                self.current_temp = float(det["stator_temp"])
            elif "temp_c" in det:
                self.current_temp = float(det["temp_c"])

        if self.state == SadaState.DERATE:
            self._derate_dwell_timer += dt
        else:
            self._derate_dwell_timer = 0.0

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
                if self.state == SadaState.DERATE and self._derate_dwell_timer < c.derate_min_dwell_s:
                    new = SadaState.DERATE
                else:
                    new = SadaState.WATCH
            else:
                if self.state == SadaState.DERATE and self._derate_dwell_timer < c.derate_min_dwell_s:
                    new = SadaState.DERATE
                else:
                    new = SadaState.NORMAL

            if new != self.state:
                if new == SadaState.DERATE:
                    self._derate_dwell_timer = 0.0
                self._enter(new, "OK" if new == SadaState.NORMAL else f"{new.value}_{self.fault.value.upper()}")

        if self.state == SadaState.NORMAL and s < c.watch - c.hysteresis and not self.sensor_loss_active:
            self.fault = DiagFault.HEALTHY

        if self.state == SadaState.TRIP:
            target_load = 0.0
            self._current_load_cmd = 0.0
        elif self.state == SadaState.DERATE:
            if self.sensor_loss_active and c.sensor_loss_action == "derate":
                target_load = c.sensor_loss_derate_load
            else:
                frac = min(1.0, (s - c.derate) / (c.trip - c.derate)) if s > c.derate else 0.0
                target_load = 1.0 - frac * (1.0 - c.min_load)
            if target_load < self._current_load_cmd:
                self._current_load_cmd = max(target_load, self._current_load_cmd - c.ramp_down_rate * dt)
            else:
                self._current_load_cmd = min(target_load, self._current_load_cmd + c.ramp_up_rate * dt)
        else:
            target_load = 1.0
            if self._current_load_cmd < target_load:
                self._current_load_cmd = min(target_load, self._current_load_cmd + c.ramp_up_rate * dt)
            else:
                self._current_load_cmd = target_load

        load = self._current_load_cmd
        manual_load = self.manual_load
        manual = manual_load is not None and self.state != SadaState.TRIP
        if manual_load is not None and manual:
            load = min(load, manual_load) if self.state == SadaState.DERATE else manual_load
        out = SadaOutput(
            self.state,
            round(load, 4),
            "MANUAL_OVERRIDE" if manual else self.reason,
            self.state == SadaState.TRIP,
            round(s, 4),
            self.fault.value,
            manual,
            changed=prev != self.state,
            latched_fault=self.latched_fault.value if self.latched_fault else None,
            latched_severity=round(self.latched_severity, 4) if self.latched_severity is not None else None,
            latched_temp=round(self.latched_temp, 2) if self.latched_temp is not None else None,
            trip_time=round(self.trip_time, 2) if self.trip_time is not None else None,
            lockout=self.lockout,
        )
        self._last_out = out
        return out

    def _enter(self, state: SadaState, reason: str, t: float | None = None) -> None:
        prev = self.state
        self.state = state
        self.reason = reason
        self.acknowledged = False
        if prev != SadaState.TRIP and state == SadaState.TRIP:
            self.trip_time = t if t is not None else self.current_time
            self.latched_fault = self.fault
            self.latched_severity = self.smoothed
            self.latched_temp = self.current_temp
