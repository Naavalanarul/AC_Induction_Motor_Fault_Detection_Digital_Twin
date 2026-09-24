"""
backend/app/simulation/params.py

This module contains the core motor parameters and precomputes derived state space constants.
Reference: Chen et al. (Energies 2025, 'Digital Twin-Based Online Diagnosis...').
"""

from dataclasses import dataclass

@dataclass(frozen = True)
class DerivedConstants:

    sigma: float        # Leakage Factor
    Tr: float           # Rotor Time Constant (Tr), seconds
    gamma: float        # Damping / equivalent stator coefficient
    K: float            # Coupling Factor (K)

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
