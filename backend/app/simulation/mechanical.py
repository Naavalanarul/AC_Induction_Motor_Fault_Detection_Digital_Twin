"""simulation/mechanical.py

Object-Oriented electromechanical torque production and rotor dynamics
for an induction machine in the stationary (alpha-beta) reference frame.

Reference:
    Chen et al. (Energies 2025), Eq. (13)-(14) [Healthy machine case].
"""

from __future__ import annotations
from dataclasses import dataclass
import math

from app.simulation.params import MotorParams
from app.simulation.transforms import AlphaBeta


@dataclass(frozen=True)
class MechanicalState:
    """Encapsulates rotor angular speed and electrical position."""

    omega_r: float  # Rotor electrical angular speed [rad/s]
    theta_r: float = 0.0  # Rotor electrical position [rad]

    def omega_m(self, pole_pairs: int) -> float:
        """Returns rotor mechanical shaft speed [rad/s]."""
        return self.omega_r / pole_pairs

    def rpm(self, pole_pairs: int) -> float:
        """Returns rotor mechanical shaft speed [RPM]."""
        return self.omega_m(pole_pairs) * (60.0 / (2.0 * math.pi))

    def electrical_freq_hz(self) -> float:
        """Returns electrical rotor frequency [Hz]."""
        return self.omega_r / (2.0 * math.pi)

    @classmethod
    def standstill(cls) -> MechanicalState:
        """Returns initial resting state at 0 speed and 0 angle."""
        return cls(omega_r=0.0, theta_r=0.0)


class InductionMotorMechanicalDynamics:
    """Encapsulates torque computation and the rotor equation of motion.

    Precomputes constant coefficients relating torque constant and effective inertia
    to eliminate redundant operations during simulation steps.
    """

    def __init__(self, params: MotorParams, damping: float = 0.0):
        """
        Args:
            params: MotorParams instance holding J, pole_pairs, Lm, and Lr.
            damping: Viscous friction damping coefficient B [N*m*s/rad].
        """
        self.params = params
        self.damping = damping

        # Precompute constants:
        # 1. Torque constant: (3/2) * p * (Lm / Lr)
        self._torque_const: float = 1.5 * params.pole_pairs * (params.Lm / params.Lr)

        # 2. Effective electrical inertia: J / p
        self._effective_inertia: float = params.J / params.pole_pairs

    def compute_electromagnetic_torque(
        self,
        stator_current: AlphaBeta,
        rotor_flux: AlphaBeta,
    ) -> float:
        """Computes instantaneous electromagnetic torque Te.

        Formula (Chen et al. Eq. 13, healthy machine):
            Te = (3/2) * p * (Lm / Lr) * (psi_r_alpha * i_beta - psi_r_beta * i_alpha)

        Args:
            stator_current: Stator current vector (i_salpha, i_sbeta) [A].
            rotor_flux: Rotor flux linkage vector (psi_ralpha, psi_rbeta) [Wb].

        Returns:
            float: Instantaneous electromagnetic torque [N·m].
        """
        cross_product = (rotor_flux.alpha * stator_current.beta) - (rotor_flux.beta * stator_current.alpha)
        return float(self._torque_const * cross_product)

    def evaluate_acceleration(
        self,
        Te: float,
        load_torque: float,
        current_omega_r: float = 0.0,
    ) -> float:
        """Computes time derivative of electrical rotor speed (d omega_r / dt).

        Formula (Chen et al. Eq. 14):
            Te = TL + (J / p) * (d omega_r / dt) + (B / p) * omega_r
            => d omega_r / dt = (Te - TL - (B / p) * omega_r) / (J / p)

        Args:
            Te: Developed electromagnetic torque [N·m].
            load_torque: Opposing mechanical load torque TL [N·m].
            current_omega_r: Current electrical rotor speed [rad/s] (used for viscous damping).

        Returns:
            float: Angular acceleration in electrical rad/s².
        """
        damping_torque = (self.damping / self.params.pole_pairs) * current_omega_r
        net_torque = Te - load_torque - damping_torque
        return float(net_torque / self._effective_inertia)

    def step_euler(
        self,
        state: MechanicalState,
        Te: float,
        load_torque: float,
        dt: float,
    ) -> MechanicalState:
        """Convenience forward step for mechanical state under quasi-static assumptions.

        Because mechanical time constants (J) are orders of magnitude slower than
        electrical time constants (L/R), a simple forward update is often decoupled:
            omega_r(t + dt) = omega_r + alpha * dt
            theta_r(t + dt) = (theta_r + omega_r * dt) % 2pi
        """
        d_omega_r = self.evaluate_acceleration(Te, load_torque, state.omega_r)
        new_omega_r = max(0.0, state.omega_r + d_omega_r * dt)  # Clamp against negative rotation if passive load
        new_theta_r = (state.theta_r + state.omega_r * dt) % (2.0 * math.pi)

        return MechanicalState(omega_r=new_omega_r, theta_r=new_theta_r)
