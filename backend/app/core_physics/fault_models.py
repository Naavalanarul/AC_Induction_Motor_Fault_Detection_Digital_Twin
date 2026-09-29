"""core_physics/fault_models.py

Analytical fault injection models for AC induction motors.
Replaces mock toggle flags with true physical parameter modulations.

1. Broken Rotor Bar (BRB): Modulates rotor resistance as asymmetrical function of rotor angle
2. Stator Inter-Turn Short Circuit (ITSC): Shorted-turn ratio and fault resistance
3. Eccentricity: Dynamic/static air-gap permeance modulation
4. Bearing Faults: Characteristic frequencies from geometry, load torque perturbations
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np


class FaultType(str, Enum):
    BROKEN_ROTOR_BAR = "broken_rotor_bar"
    INTERTURN_SHORT = "interturn_short"
    ECCENTRICITY = "eccentricity"
    BEARING_INNER = "bearing_inner"
    BEARING_OUTER = "bearing_outer"
    BEARING_BALL = "bearing_ball"
    UNBALANCE = "unbalance"
    MISALIGNMENT = "misalignment"
    VOLTAGE_ANOMALY = "voltage_anomaly"


class BearingDefect(str, Enum):
    IR = "inner_race"
    OR = "outer_race"
    BALL = "ball"
    CAGE = "cage"


class EccentricityType(str, Enum):
    STATIC = "static"
    DYNAMIC = "dynamic"
    MIXED = "mixed"


@dataclass
class BearingGeometry:
    """Bearing geometric parameters for defect frequency calculation.

    Standard SKF 6205-2RS deep-groove ball bearing (default):
    - Pitch diameter D = 39.04 mm
    - Ball diameter d = 7.94 mm
    - Number of balls N_b = 9
    - Contact angle β = 0° (deep groove)
    """
    pitch_diameter: float = 39.04e-3  # D [m]
    ball_diameter: float = 7.94e-3  # d [m]
    num_balls: int = 9  # N_b
    contact_angle_deg: float = 0.0  # β [deg]

    @property
    def contact_angle(self) -> float:
        return math.radians(self.contact_angle_deg)

    def defect_frequencies(self, shaft_freq_hz: float) -> dict[str, float]:
        """Calculate bearing defect characteristic frequencies.

        Returns multiples of shaft rotation frequency f_r.
        Formulas (for contact angle β):
        - BPFO (outer race) = N_b/2 * (1 - d/D * cosβ) * f_r
        - BPFI (inner race) = N_b/2 * (1 + d/D * cosβ) * f_r
        - BSF (ball spin) = D/(2d) * (1 - (d/D * cosβ)²) * f_r
        - FTF (cage/train) = 1/2 * (1 - d/D * cosβ) * f_r
        """
        D = self.pitch_diameter
        d = self.ball_diameter
        Nb = self.num_balls
        cos_beta = math.cos(self.contact_angle)

        bpfo_mult = Nb / 2.0 * (1.0 - d / D * cos_beta)
        bpfi_mult = Nb / 2.0 * (1.0 + d / D * cos_beta)
        bsf_mult = D / (2.0 * d) * (1.0 - (d / D * cos_beta) ** 2)
        ftf_mult = 0.5 * (1.0 - d / D * cos_beta)

        return {
            "BPFO": bpfo_mult * shaft_freq_hz,
            "BPFI": bpfi_mult * shaft_freq_hz,
            "BSF": bsf_mult * shaft_freq_hz,
            "FTF": ftf_mult * shaft_freq_hz,
            "bpfo_mult": bpfo_mult,
            "bpfi_mult": bpfi_mult,
            "bsf_mult": bsf_mult,
            "ftf_mult": ftf_mult,
        }


@dataclass
class ActiveFault:
    """One injected fault with normalized severity [0, 1]."""

    id: int
    fault_type: FaultType
    severity: float
    params: dict = field(default_factory=dict)


_ids = itertools.count(1)


def _check_severity(severity: float) -> float:
    s = float(severity)
    if not 0.0 <= s <= 1.0:
        raise ValueError(f"severity must be within [0, 1], got {severity}")
    return s


class FaultState:
    """Mutable container of all currently injected faults for one motor.

    Exposes aggregated physical coefficients that the dynamic solver,
    vibration generator, and thermal model all read from, ensuring
    cross-sensor consistency.
    """

    N_ROTOR_BARS: int = 28  # Default rotor bar count

    def __init__(self) -> None:
        self._faults: dict[int, ActiveFault] = {}
        self.bearing_geometry = BearingGeometry()

    # --- Bookkeeping -----------------------------------------------------
    def add(self, fault: ActiveFault) -> ActiveFault:
        self._faults[fault.id] = fault
        return fault

    def remove(self, fault_id: int) -> ActiveFault | None:
        return self._faults.pop(fault_id, None)

    def clear(self) -> None:
        self._faults.clear()

    @property
    def active(self) -> list[ActiveFault]:
        return list(self._faults.values())

    def of_type(self, fault_type: FaultType) -> list[ActiveFault]:
        return [f for f in self._faults.values() if f.fault_type == fault_type]

    def severity_of(self, fault_type: FaultType) -> float:
        """Max severity among active faults of one type (0 if none)."""
        return max((f.severity for f in self.of_type(fault_type)), default=0.0)

    # --- Aggregated physical coefficients for dynamic solver -------------
    @property
    def brb_delta(self) -> float:
        """Relative rise of rotor resistance along the faulted rotor axis.

        δ_BRB = min(0.9, 3.0 * N_broken_bars / N_rotor_bars)
        This maps to the brb_delta parameter in dynamic_solver.
        """
        bars = sum(int(f.params.get("count", 1)) for f in self.of_type(FaultType.BROKEN_ROTOR_BAR))
        return min(0.9, 3.0 * bars / self.N_ROTOR_BARS)

    @property
    def interturn(self) -> tuple[int, float, float] | None:
        """(phase index 0..2, μ, r_fault) of the worst inter-turn short.

        μ = N_sc / N_s (shorted turn ratio)
        r_fault = contact resistance of shorted loop [Ω]
        """
        faults = self.of_type(FaultType.INTERTURN_SHORT)
        if not faults:
            return None
        f = max(faults, key=lambda x: x.severity)
        phase_map = {"a": 0, "b": 1, "c": 2}
        phase = phase_map.get(str(f.params.get("phase", "a")).lower(), 0)
        # μ scales with severity: μ_min + (μ_max - μ_min) * severity
        mu = float(f.params.get("mu", 0.005 + 0.095 * f.severity))
        r_f = float(f.params.get("r_fault", 20.0))
        return phase, mu, r_f

    @property
    def eccentricity(self) -> tuple[float, float]:
        """(dynamic_depth, static_depth) of magnetizing-inductance modulation.

        Dynamic: L_m(θ_m) = L_m0 * (1 + δ_dyn * cos(θ_m))
        Static: L_m(θ_s) = L_m0 * (1 + δ_stat * cos(2θ_s))
        """
        dyn = stat = 0.0
        for f in self.of_type(FaultType.ECCENTRICITY):
            # Check for explicit depth parameters first
            if "dynamic_depth" in f.params:
                dyn = max(dyn, float(f.params["dynamic_depth"]))
            if "static_depth" in f.params:
                stat = max(stat, float(f.params["static_depth"]))

            # Fall back to severity-based calculation
            depth = 0.15 * f.severity  # Max 15% air-gap variation
            ecc_type = f.params.get("type", EccentricityType.DYNAMIC.value)
            if ecc_type == EccentricityType.STATIC.value:
                stat = max(stat, depth)
            elif ecc_type == EccentricityType.DYNAMIC.value:
                dyn = max(dyn, depth)
            elif ecc_type == EccentricityType.MIXED.value:
                # For mixed, split severity between dynamic and static
                dyn = max(dyn, depth * 0.6)
                stat = max(stat, depth * 0.4)
        return dyn, stat

    @property
    def unbalance(self) -> float:
        """Mechanical unbalance severity (0..1)."""
        return self.severity_of(FaultType.UNBALANCE)

    @property
    def misalignment(self) -> float:
        """Mechanical misalignment severity (0..1)."""
        return self.severity_of(FaultType.MISALIGNMENT)

    def bearing(self, defect: BearingDefect) -> float:
        """Bearing defect severity for specific defect type."""
        fault_map = {
            BearingDefect.IR: FaultType.BEARING_INNER,
            BearingDefect.OR: FaultType.BEARING_OUTER,
            BearingDefect.BALL: FaultType.BEARING_BALL,
            BearingDefect.CAGE: FaultType.BEARING_BALL,  # Approximate
        }
        return self.severity_of(fault_map[defect])

    @property
    def bearing_friction_torque(self) -> float:
        """Extra friction torque [N·m] from damaged bearings."""
        s = max(self.bearing(d) for d in BearingDefect)
        return 0.3 * s  # Up to 0.3 N·m additional friction

    # --- Vibration signal generation -------------------------------------
    def bearing_impulse_times(self, defect: BearingDefect, theta_m: np.ndarray) -> np.ndarray:
        """Compute impulse occurrence times for bearing defect.

        Returns boolean array marking impulse events at defect frequency.
        """
        sev = self.bearing(defect)
        if sev <= 0.0:
            return np.zeros_like(theta_m, dtype=bool)

        # Use precomputed multiples
        defects = self.bearing_geometry.defect_frequencies(1.0)  # per unit shaft freq
        mult = {
            BearingDefect.IR: defects["bpfi_mult"],
            BearingDefect.OR: defects["bpfo_mult"],
            BearingDefect.BALL: defects["bsf_mult"],
            BearingDefect.CAGE: defects["ftf_mult"],
        }[defect]

        # Impulses occur at integer multiples of defect angle
        # defect angle = mult * θ_m (electrical cycles per mechanical rev)
        count = np.floor(mult * theta_m / (2.0 * math.pi))
        hits = np.diff(np.concatenate([[count[0]], count])) > 0
        return hits

    def bearing_impulse_amplitude(
        self,
        defect: BearingDefect,
        theta_m: np.ndarray,
        omega_m: np.ndarray,
        speed_ratio: np.ndarray,
    ) -> np.ndarray:
        """Amplitude modulation for bearing impulses.

        Inner race: modulated by load zone passage (cos(θ_m))
        Outer race: constant (stationary defect in load zone)
        Ball: modulated by cage frequency (cos(FTF * θ_m))
        """
        sev = self.bearing(defect)
        if sev <= 0.0:
            return np.zeros_like(theta_m)

        base_amp = (2.0 + 8.0 * sev) * speed_ratio**2
        defects = self.bearing_geometry.defect_frequencies(1.0)

        if defect == BearingDefect.IR:
            mod = 0.55 + 0.45 * np.cos(theta_m)  # Load zone modulation
        elif defect == BearingDefect.BALL:
            mod = 0.55 + 0.45 * np.cos(defects["ftf_mult"] * theta_m)  # Cage modulation
        else:  # OR
            mod = np.ones_like(theta_m)

        return base_amp * mod

    # --- Load torque perturbations ---------------------------------------
    def load_torque_perturbation(self, theta_m: np.ndarray, omega_m: np.ndarray) -> np.ndarray:
        """Additional load torque from mechanical faults.

        Unbalance: 1× shaft frequency
        Misalignment: 2× shaft frequency
        Bearing: impulse train at defect frequencies
        """
        unb = self.unbalance
        mis = self.misalignment
        pert = np.zeros_like(theta_m)

        if unb:
            pert += 0.6 * unb * np.cos(theta_m)
        if mis:
            pert += 0.6 * mis * np.cos(2.0 * theta_m)

        # Bearing friction torque (velocity-dependent)
        pert += self.bearing_friction_torque * np.sign(omega_m)

        return pert


# --- Injector Functions ---------------------------------------------------
def _new(state: FaultState, ftype: FaultType, severity: float, **params) -> ActiveFault:
    return state.add(ActiveFault(id=next(_ids), fault_type=ftype, severity=_check_severity(severity), params=params))


def inject_broken_rotor_bar(
    state: FaultState,
    count: int = 1,
    position: int = 0,
    severity: float | None = None,
) -> ActiveFault:
    """Inject broken rotor bar fault.

    Args:
        state: FaultState container
        count: Number of broken bars (1-8)
        position: Angular position index (0 to N_bars-1)
        severity: Optional explicit severity (overrides count-based)
    """
    if not 1 <= count <= 8:
        raise ValueError("count must be within [1, 8]")
    sev = severity if severity is not None else count / 8.0
    return _new(state, FaultType.BROKEN_ROTOR_BAR, sev, count=count, position=position)


def inject_interturn_short(
    state: FaultState,
    phase: str = "a",
    mu: float = 0.05,
    r_fault: float = 20.0,
    severity: float | None = None,
) -> ActiveFault:
    """Inject stator inter-turn short circuit fault.

    Args:
        state: FaultState container
        phase: Shorted phase ('a', 'b', 'c')
        mu: Shorted turn ratio μ = N_sc / N_s (typically 0.01-0.15)
        r_fault: Shorted loop contact resistance [Ω]
        severity: Optional explicit severity (overrides mu-based)
    """
    if phase.lower() not in ("a", "b", "c"):
        raise ValueError("phase must be one of a, b, c")
    sev = severity if severity is not None else min(1.0, mu / 0.15)
    return _new(state, FaultType.INTERTURN_SHORT, sev, phase=phase.lower(), mu=mu, r_fault=r_fault)


def inject_eccentricity(
    state: FaultState,
    type: str = "dynamic",
    severity: float = 0.5,
    dynamic_depth: float | None = None,
    static_depth: float | None = None,
) -> ActiveFault:
    """Inject air-gap eccentricity fault.

    Args:
        state: FaultState container
        type: 'static', 'dynamic', or 'mixed'
        severity: Overall severity (0..1)
        dynamic_depth: Explicit dynamic eccentricity depth (overrides severity)
        static_depth: Explicit static eccentricity depth (overrides severity)
    """
    EccentricityType(type)
    params: dict[str, Any] = {"type": type}
    if dynamic_depth is not None:
        params["dynamic_depth"] = dynamic_depth
    if static_depth is not None:
        params["static_depth"] = static_depth
    return _new(state, FaultType.ECCENTRICITY, severity, **params)


def inject_bearing_fault(
    state: FaultState,
    defect: str = "OR",
    severity: float = 0.5,
) -> ActiveFault:
    """Inject bearing fault.

    Args:
        state: FaultState container
        defect: 'IR', 'OR', 'BALL', 'CAGE'
        severity: Fault severity (0..1)
    """
    defect_enum = BearingDefect(defect)
    fault_map = {
        BearingDefect.IR: FaultType.BEARING_INNER,
        BearingDefect.OR: FaultType.BEARING_OUTER,
        BearingDefect.BALL: FaultType.BEARING_BALL,
        BearingDefect.CAGE: FaultType.BEARING_BALL,
    }
    return _new(state, fault_map[defect_enum], severity, type=defect_enum.value)


def inject_unbalance(state: FaultState, magnitude: float = 0.5) -> ActiveFault:
    """Inject mechanical unbalance."""
    return _new(state, FaultType.UNBALANCE, magnitude)


def inject_misalignment(state: FaultState, magnitude: float = 0.5) -> ActiveFault:
    """Inject mechanical misalignment."""
    return _new(state, FaultType.MISALIGNMENT, magnitude)


def inject_fault(
    state: FaultState,
    fault_type: FaultType | str,
    severity: float,
    params: dict | None = None,
) -> ActiveFault:
    """Generic dispatcher used by API layer."""
    ft = FaultType(fault_type)
    p = dict(params or {})
    if ft == FaultType.BROKEN_ROTOR_BAR:
        count = int(p.get("count", max(1, round(_check_severity(severity) * 8))))
        return inject_broken_rotor_bar(state, count=count, position=int(p.get("position", 0)))
    if ft == FaultType.INTERTURN_SHORT:
        return inject_interturn_short(
            state,
            phase=str(p.get("phase", "a")),
            mu=float(p.get("mu", 0.005 + 0.095 * severity)),
            r_fault=float(p.get("r_fault", 20.0)),
        )
    if ft == FaultType.ECCENTRICITY:
        return inject_eccentricity(state, type=str(p.get("type", "dynamic")), severity=severity)
    if ft in (FaultType.BEARING_INNER, FaultType.BEARING_OUTER, FaultType.BEARING_BALL):
        defect_map = {
            FaultType.BEARING_INNER: "IR",
            FaultType.BEARING_OUTER: "OR",
            FaultType.BEARING_BALL: "BALL",
        }
        return inject_bearing_fault(state, defect=defect_map[ft], severity=severity)
    if ft == FaultType.UNBALANCE:
        return inject_unbalance(state, magnitude=severity)
    return inject_misalignment(state, magnitude=severity)
