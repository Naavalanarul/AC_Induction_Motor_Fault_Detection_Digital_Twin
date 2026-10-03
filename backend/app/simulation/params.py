"""
backend/app/simulation/params.py

This module contains the core motor parameters and precomputes derived state space constants.
Reference: Chen et al. (Energies 2025, 'Digital Twin-Based Online Diagnosis...').
"""

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen = True)
class DerivedConstants:

    sigma: float        # Leakage Factor
    Tr: float           # Rotor Time Constant (Tr), seconds
    gamma: float        # Damping / equivalent stator coefficient (lambda in Chen et al.)
    K: float            # Coupling Factor (K)

    @property
    def lambda_(self) -> float:
        """Alias matching the symbol used in Chen et al. Eq. (3)."""
        return self.gamma

@dataclass(frozen = True)
class MotorParams:
    """
    Core electrical and mechanical parameters for the AC induction motor simulation.
    """
    Rs: float           # Stator Resistance
    Rr: float           # Rotor Resistance

    Ls: float           # Stator Inductance
    Lr: float           # Rotor Inductance
    Lm: float           # Mutual Inductance

    J: float            # Rotor Inertia
    pole_pairs: int     # Number of Pole Pairs

    """Rated Name Plate values (for validation)"""
    rated_power: float     # Watts (W)
    rated_voltage: float   # Volts (V)
    rated_current: float   # Amperes (A)
    rated_speed: float     # Revolutions per minute (rpm)
    rated_torque: float    # Newton-meters (Nm)

    # Thermal model parameters (scaled per motor size and insulation class)
    t_ambient: float = 25.0
    insulation_class: str = "F"
    r_th: float | None = None
    tau_s: float = 180.0
    warn_c: float | None = None
    trip_c: float | None = None

    def get_thermal_resistance(self) -> float:
        """Computes lumped thermal resistance R_th [K/W] targeted to 80 K rated-loss rise."""
        if self.r_th is not None and self.r_th > 0:
            return self.r_th
        p_cu = 1.5 * (self.Rs + self.Rr) * (self.rated_current ** 2)
        p_fe = 0.025 * self.rated_power
        p_loss = max(10.0, p_cu + p_fe)
        return 80.0 / p_loss

    def compute_derived_constants(self) -> DerivedConstants:
        """Precomputes derived constants used directly in the state-space dynamic model.

        Formulations from Chen et al. (2025), beneath Eq. (3):
        - σ  = 1 - Lm² / (Ls · Lr)
        - Tr = Lr / Rr
        - λ  = (Rs + Lm² / (Lr · Tr)) / (σ · Ls)
        - K  = Lm / (σ · Ls · Lr)
        """

        sigma = 1 - self.Lm**2 / (self.Ls * self.Lr)                         #Total Leakage Factor

        Tr = self.Lr / self.Rr                                               #Rotor Time Constant

        gamma = (self.Rs + self.Lm**2 / (self.Lr * Tr)) / (sigma * self.Ls)  #Damping Factor

        K = self.Lm / (sigma * self.Ls * self.Lr)                            #Flux-to-current coupling factor (K)

        return DerivedConstants(sigma = sigma, Tr = Tr, gamma = gamma, K = K)


INSULATION_LIMITS: dict[str, dict[str, float]] = {
    "B": {"warn_c": 100.0, "trip_c": 125.0, "max_hotspot": 130.0},
    "F": {"warn_c": 120.0, "trip_c": 145.0, "max_hotspot": 155.0},
    "H": {"warn_c": 140.0, "trip_c": 170.0, "max_hotspot": 180.0},
}


def validate_motor_params(
    p: MotorParams,
    fs: float = 5000.0,
    supply_freq: float = 50.0,
) -> tuple[bool, str]:
    """Validates physical plausibility and RK4 numerical stability of motor parameters.

    Returns:
        (True, "OK") if parameters are physically plausible and numerically stable.
        (False, error_message) describing the violation.
    """
    dt = 1.0 / fs

    # 1. Non-negativity & physical minimums
    if p.rated_voltage < 50.0 or p.rated_voltage > 15000.0:
        return False, f"rated_voltage ({p.rated_voltage} V) out of plausible industrial range [50.0, 15000.0] V"
    if p.rated_power <= 0.0:
        return False, f"rated_power ({p.rated_power} W) must be positive"
    if p.rated_current <= 0.0:
        return False, f"rated_current ({p.rated_current} A) must be positive"
    if p.rated_speed <= 0.0:
        return False, f"rated_speed ({p.rated_speed} rpm) must be positive"
    if p.rated_torque <= 0.0:
        return False, f"rated_torque ({p.rated_torque} Nm) must be positive"
    if p.Rs <= 0.0 or p.Rr <= 0.0 or p.Ls <= 0.0 or p.Lr <= 0.0 or p.Lm <= 0.0:
        return False, "All resistances and inductances must be strictly positive"
    if p.Lm >= min(p.Ls, p.Lr):
        return False, "Lm must be strictly smaller than Ls and Lr (positive leakage inductance required)"
    if p.J < 1e-4:
        return False, f"Rotor inertia J ({p.J} kg*m^2) too small for physical motor (minimum 1e-4 kg*m^2)"

    # 2. Total leakage factor sigma in [0.02, 0.25]
    sigma = 1.0 - (p.Lm ** 2) / (p.Ls * p.Lr)
    if not (0.02 <= sigma <= 0.25):
        return False, f"Total leakage factor sigma={sigma:.5f} outside plausible range [0.02, 0.25]"

    # 3. Synchronous speed vs rated speed (induction motors require slip > 0)
    n_sync = 60.0 * supply_freq / p.pole_pairs
    if p.rated_speed >= n_sync:
        return False, f"rated_speed ({p.rated_speed} rpm) must be strictly below synchronous speed ({n_sync} rpm)"

    # 4. Consistency of rated torque vs rated power / omega_rated (within 15%)
    omega_rated = p.rated_speed * 2.0 * math.pi / 60.0
    t_expected = p.rated_power / omega_rated
    if abs(p.rated_torque - t_expected) / t_expected > 0.15:
        return False, (
            f"rated_torque ({p.rated_torque} Nm) deviates by more than 15% from "
            f"nameplate P/omega ({t_expected:.2f} Nm)"
        )

    # 5. Magnetizing current ratio: Im = V_phase / (2*pi*f*Lm) between 15% and 95% of rated_current
    v_phase = p.rated_voltage / math.sqrt(3.0)
    i_m = v_phase / (2.0 * math.pi * supply_freq * p.Lm)
    im_ratio = i_m / p.rated_current
    if not (0.15 <= im_ratio <= 0.95):
        return False, (
            f"Magnetizing current Im ({i_m:.2f} A, {im_ratio*100:.1f}% of rated) outside "
            "plausible range [15%, 95%] of rated_current"
        )

    # 6. RK4 electrical eigenvalue stability: max|lambda| * dt <= 2.78
    der = p.compute_derived_constants()
    lam = der.gamma
    K = der.K
    inv_tr = 1.0 / der.Tr
    lm_over_tr = p.Lm * inv_tr
    k_over_tr = K * inv_tr
    wr_sync = 2.0 * math.pi * supply_freq
    for wr in (0.0, wr_sync):
        A = np.array([
            [-lam, 0.0, k_over_tr, K * wr],
            [0.0, -lam, -K * wr, k_over_tr],
            [lm_over_tr, 0.0, -inv_tr, -wr],
            [0.0, lm_over_tr, wr, -inv_tr],
        ])
        max_ev = float(np.max(np.abs(np.linalg.eigvals(A))))
        if max_ev * dt > 2.78:
            return False, (
                f"RK4 numerical stability exceeded: max|lambda|*dt = {max_ev*dt:.2f} > 2.78 "
                f"(stiff electrical system at fs={fs} Hz)"
            )

    # 7. RK4 mechanical pole stability: (B / J) * dt <= 2.78 (viscous damping B=0.002)
    b_viscous = 0.002
    mech_ev = (b_viscous / p.J) * dt
    if mech_ev > 2.78:
        return False, f"Mechanical RK4 stability exceeded: (B/J)*dt = {mech_ev:.2f} > 2.78"

    return True, "OK"


CHEN_2025_MOTOR = MotorParams(
    Rs=1.2,
    Rr=0.69,
    Ls=0.241,
    Lr=0.241,
    Lm=0.115,
    J=0.02,               # Standard nominal inertia for a 1.5 kW frame
    pole_pairs=2,         # 4 poles (p = 2)
    rated_power=1500.0,   # 1.5 kW
    rated_voltage=380.0,  # 380 V (standard 3-phase line-to-line)
    rated_current=3.5,    # Approximate rated phase current [A]
    rated_speed=1420.0,   # 1420 rpm (typical 4-pole 50 Hz induction motor)
    rated_torque=10.1,    # T = P / ω_mech ≈ 1500 / (1420 * 2π / 60) ≈ 10.09 N·m
)


# NOTE: The CHEN_2025_MOTOR values above give a total leakage factor sigma ~= 0.77
# (Lm is less than half of Ls), which limits direct-on-line starting current to ~5 A
# and produces almost no starting torque. These values have not been re-verified
# against the paper; they are kept for traceability only.
#
# DEFAULT_MOTOR is a widely used 1.5 kW, 4-pole, 50 Hz parameter set from the
# field-oriented / DTC control literature (Rs=1.405, Rr=1.395, Lls=Llr=5.839 mH,
# Lm=172.2 mH, J=0.0131). It yields realistic starting, slip and rated current,
# so it drives the live digital twin. Verify against your own motor nameplate and
# no-load/locked-rotor tests before trusting absolute values.
DEFAULT_MOTOR = MotorParams(
    Rs=1.405,
    Rr=1.395,
    Ls=0.178039,
    Lr=0.178039,
    Lm=0.1722,
    J=0.0131,
    pole_pairs=2,
    rated_power=1500.0,
    rated_voltage=380.0,
    rated_current=4.7,     # what this parameter set draws at 10 N*m / 380 V star (simulated)
    rated_speed=1474.0,    # simulated speed at 10 N*m
    rated_torque=10.0,
)
