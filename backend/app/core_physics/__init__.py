"""Core Physics Package for AC Induction Motor Digital Twin.

This package contains the fundamental physics models:
- Motor parameters and equivalent circuit values
- Dynamic state-space solver (RK45)
- Fault models (BRB, ITSC, Eccentricity, Bearing)
- Thermal Lumped Parameter Network (LPTN)
"""

from .dynamic_solver import StateSpaceMotorSolver, TransientResult
from .fault_models import (
    BearingDefect,
    EccentricityType,
    FaultState,
    FaultType,
    inject_bearing_fault,
    inject_broken_rotor_bar,
    inject_eccentricity,
    inject_interturn_short,
)
from .motor_parameters import DEFAULT_MOTOR, MotorParams
from .thermal_lptn import FourNodeThermalLPTN, LPTNState

__all__ = [
    "MotorParams",
    "DEFAULT_MOTOR",
    "StateSpaceMotorSolver",
    "TransientResult",
    "FaultType",
    "BearingDefect",
    "EccentricityType",
    "FaultState",
    "inject_broken_rotor_bar",
    "inject_interturn_short",
    "inject_eccentricity",
    "inject_bearing_fault",
    "FourNodeThermalLPTN",
    "LPTNState",
]
