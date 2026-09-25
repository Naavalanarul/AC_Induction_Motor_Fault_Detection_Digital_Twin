"""simulation/faults.py

Fault injector module. One injector function per fault type, each parameterized
by severity. Injectors only mutate a `FaultState` container; the plant model,
the vibration/acoustic generators and the thermal model all read from the same
container, so cross-sensor consistency is automatic.

Modelling notes (simplified, documented honestly):
    * Broken rotor bar   -> rotor resistance asymmetry fixed to the rotor axes
                            (backward field -> classic (1 +/- 2s)f current sidebands).
    * Inter-turn short   -> shorted-turn loop current added to the faulted phase
                            (i_f = eta * u_k / (R_f + eta * Rs)) plus loop heat.
    * Eccentricity       -> magnetizing inductance modulated by rotor angle
                            (dynamic: f +/- f_r sidebands) or by 2x supply angle (static).
    * Bearing IR/OR/Ball -> drives the vibration/acoustic generators, plus a small
                            friction torque increase (faint current signature).
    * Unbalance          -> 1x shaft-frequency load torque ripple + 1x radial vibration.
    * Misalignment       -> 2x shaft-frequency torque ripple + 2x radial / 1x axial vibration.
    * Voltage anomaly    -> supply-side sag / negative-sequence imbalance / 5th+7th harmonics.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import Enum


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
    IR = "IR"
    OR = "OR"
    BALL = "Ball"


class EccentricityType(str, Enum):
    STATIC = "static"
    DYNAMIC = "dynamic"


class VoltageAnomalyType(str, Enum):
    SAG = "sag"
    IMBALANCE = "imbalance"
    HARMONIC = "harmonic"


@dataclass
class ActiveFault:
    """One injected fault. `severity` is always normalized to [0, 1]."""

    id: int
    fault_type: FaultType
    severity: float
    params: dict = field(default_factory=dict)


_BEARING_TO_FAULT = {
    BearingDefect.IR: FaultType.BEARING_INNER,
    BearingDefect.OR: FaultType.BEARING_OUTER,
    BearingDefect.BALL: FaultType.BEARING_BALL,
}

_ids = itertools.count(1)


def _check_severity(severity: float) -> float:
    s = float(severity)
    if not 0.0 <= s <= 1.0:
        raise ValueError(f"severity must be within [0, 1], got {severity}")
    return s


class FaultState:
    """Mutable container of all currently injected faults for one motor.

    Exposes the aggregated physical coefficients the plant/generators need.
    """

    N_ROTOR_BARS = 28

    def __init__(self) -> None:
        self._faults: dict[int, ActiveFault] = {}

    # --- bookkeeping -----------------------------------------------------
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

    # --- aggregated physical coefficients ---------------------------------
    @property
    def brb_delta(self) -> float:
        """Relative rise of rotor resistance along the faulted rotor axis."""
        bars = sum(int(f.params.get("count", 1)) for f in self.of_type(FaultType.BROKEN_ROTOR_BAR))
        return min(0.9, 3.0 * bars / self.N_ROTOR_BARS)

    @property
    def interturn(self) -> tuple[int, float, float] | None:
        """(phase index 0..2, eta, fault resistance) of the worst inter-turn short."""
        faults = self.of_type(FaultType.INTERTURN_SHORT)
        if not faults:
            return None
        f = max(faults, key=lambda x: x.severity)
        phase = "abc".index(str(f.params.get("phase", "a")).lower())
        eta = float(f.params.get("eta", 0.005 + 0.095 * f.severity))
        r_f = float(f.params.get("r_fault", 20.0))
        return phase, eta, r_f

    @property
    def eccentricity(self) -> tuple[float, float]:
        """(dynamic_depth, static_depth) of magnetizing-inductance modulation."""
        dyn = stat = 0.0
        for f in self.of_type(FaultType.ECCENTRICITY):
            depth = 0.15 * f.severity
            if f.params.get("type", EccentricityType.DYNAMIC.value) == EccentricityType.STATIC.value:
                stat = max(stat, depth)
            else:
                dyn = max(dyn, depth)
        return dyn, stat

    @property
    def unbalance(self) -> float:
        return self.severity_of(FaultType.UNBALANCE)

    @property
    def misalignment(self) -> float:
        return self.severity_of(FaultType.MISALIGNMENT)

    def bearing(self, defect: BearingDefect) -> float:
        return self.severity_of(_BEARING_TO_FAULT[defect])

    @property
    def bearing_friction_torque(self) -> float:
        """Extra friction torque [N*m] from damaged bearings."""
        s = max(self.bearing(d) for d in BearingDefect)
        return 0.3 * s

    @property
    def voltage(self) -> tuple[float, float, float]:
        """(sag_fraction, negative_sequence_fraction, harmonic_fraction)."""
        sag = imb = harm = 0.0
        for f in self.of_type(FaultType.VOLTAGE_ANOMALY):
            kind = f.params.get("type", VoltageAnomalyType.SAG.value)
            if kind == VoltageAnomalyType.SAG.value:
                sag = max(sag, 0.5 * f.severity)
            elif kind == VoltageAnomalyType.IMBALANCE.value:
                imb = max(imb, 0.1 * f.severity)
            else:
                harm = max(harm, 0.1 * f.severity)
        return sag, imb, harm


# ---------------------------------------------------------------------------
# Injector functions (one per fault, parameterized by severity)
# ---------------------------------------------------------------------------
def _new(state: FaultState, ftype: FaultType, severity: float, **params) -> ActiveFault:
    return state.add(ActiveFault(id=next(_ids), fault_type=ftype, severity=_check_severity(severity), params=params))


def inject_broken_rotor_bar(state: FaultState, count: int = 1, position: int = 0) -> ActiveFault:
    if not 1 <= count <= 8:
        raise ValueError("count must be within [1, 8]")
    return _new(state, FaultType.BROKEN_ROTOR_BAR, count / 8.0, count=count, position=position)


def inject_interturn_short(state: FaultState, phase: str = "a", severity_eta: float = 0.5) -> ActiveFault:
    if phase.lower() not in ("a", "b", "c"):
        raise ValueError("phase must be one of a, b, c")
    return _new(state, FaultType.INTERTURN_SHORT, severity_eta, phase=phase.lower())


def inject_eccentricity(state: FaultState, type: str = "dynamic", severity: float = 0.5) -> ActiveFault:
    EccentricityType(type)
    return _new(state, FaultType.ECCENTRICITY, severity, type=type)


def inject_bearing_fault(state: FaultState, type: str = "OR", severity: float = 0.5) -> ActiveFault:
    defect = BearingDefect(type)
    return _new(state, _BEARING_TO_FAULT[defect], severity, type=defect.value)


def inject_unbalance(state: FaultState, magnitude: float = 0.5) -> ActiveFault:
    return _new(state, FaultType.UNBALANCE, magnitude)


def inject_misalignment(state: FaultState, magnitude: float = 0.5) -> ActiveFault:
    return _new(state, FaultType.MISALIGNMENT, magnitude)


def inject_voltage_anomaly(state: FaultState, type: str = "sag", severity: float = 0.5) -> ActiveFault:
    VoltageAnomalyType(type)
    return _new(state, FaultType.VOLTAGE_ANOMALY, severity, type=type)


def inject(state: FaultState, fault_type: FaultType | str, severity: float, params: dict | None = None) -> ActiveFault:
    """Generic dispatcher used by the API layer."""
    ft = FaultType(fault_type)
    p = dict(params or {})
    if ft == FaultType.BROKEN_ROTOR_BAR:
        count = int(p.get("count", max(1, round(_check_severity(severity) * 8))))
        return inject_broken_rotor_bar(state, count=count, position=int(p.get("position", 0)))
    if ft == FaultType.INTERTURN_SHORT:
        return inject_interturn_short(state, phase=str(p.get("phase", "a")), severity_eta=severity)
    if ft == FaultType.ECCENTRICITY:
        return inject_eccentricity(state, type=str(p.get("type", "dynamic")), severity=severity)
    if ft in (FaultType.BEARING_INNER, FaultType.BEARING_OUTER, FaultType.BEARING_BALL):
        defect = {FaultType.BEARING_INNER: "IR", FaultType.BEARING_OUTER: "OR", FaultType.BEARING_BALL: "Ball"}[ft]
        return inject_bearing_fault(state, type=defect, severity=severity)
    if ft == FaultType.UNBALANCE:
        return inject_unbalance(state, magnitude=severity)
    if ft == FaultType.MISALIGNMENT:
        return inject_misalignment(state, magnitude=severity)
    return inject_voltage_anomaly(state, type=str(p.get("type", "sag")), severity=severity)
