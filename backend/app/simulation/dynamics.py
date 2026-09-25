"""simulation/dynamics.py

Object-Oriented electrical state-space dynamic model of an induction motor
in the orthogonal stationary reference frame (alpha-beta).

Reference:
    Chen et al. (Energies 2025), Eq. (3).
    State vector: [i_salpha, i_sbeta, psi_ralpha, psi_rbeta]
"""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np

from app.simulation.params import MotorParams, DerivedConstants
from app.simulation.transforms import AlphaBeta


@dataclass(frozen=True)
class ElectricalState:
    """Encapsulates the 4-state electrical vector in alpha-beta coordinates."""

    i_salpha: float   # Stator current alpha [A]
    i_sbeta: float    # Stator current beta [A]
    psi_ralpha: float # Rotor flux alpha [Wb]
    psi_rbeta: float  # Rotor flux beta [Wb]

    def to_numpy(self) -> np.ndarray:
        """Export as 1D float64 array for numerical solvers."""
        return np.array([self.i_salpha, self.i_sbeta, self.psi_ralpha, self.psi_rbeta], dtype=np.float64)

    @classmethod
    def from_numpy(cls, arr: np.ndarray | list[float]) -> ElectricalState:
        """Factory method to construct state from flat array."""
        return cls(
            i_salpha=float(arr[0]),
            i_sbeta=float(arr[1]),
            psi_ralpha=float(arr[2]),
            psi_rbeta=float(arr[3]),
        )

    @classmethod
    def zero(cls) -> ElectricalState:
        """Returns initial resting state (all currents and fluxes zero)."""
        return cls(0.0, 0.0, 0.0, 0.0)

    @property
    def stator_current(self) -> AlphaBeta:
        """Returns stator current as an AlphaBeta vector."""
        return AlphaBeta(alpha=self.i_salpha, beta=self.i_sbeta)

    @property
    def rotor_flux(self) -> AlphaBeta:
        """Returns rotor flux linkage as an AlphaBeta vector."""
        return AlphaBeta(alpha=self.psi_ralpha, beta=self.psi_rbeta)


@dataclass(frozen=True)
class StateDerivatives:
    """Encapsulates time derivatives of the electrical states."""

    d_is_alpha: float
    d_is_beta: float
    d_psi_ralpha: float
    d_psi_rbeta: float

    def to_numpy(self) -> np.ndarray:
        """Export as 1D float64 array."""
        return np.array([self.d_is_alpha, self.d_is_beta, self.d_psi_ralpha, self.d_psi_rbeta], dtype=np.float64)


class InductionMotorElectricalDynamics:
    """Evaluates the 4th-order electrical state-space ODEs.

    Pre-caches invariant factor combinations from MotorParams and DerivedConstants
    to maximize evaluation speed during repeated solver stages.
    """

    def __init__(self, params: MotorParams, derived: DerivedConstants | None = None):
        self.params = params
        self.derived = derived if derived is not None else params.compute_derived_constants()

        # Precompute algebraic factor products to eliminate runtime division/multiplication overhead
        self._inv_tr: float = 1.0 / self.derived.Tr
        self._k_over_tr: float = self.derived.K * self._inv_tr
        self._inv_sigma_ls: float = 1.0 / (self.derived.sigma * self.params.Ls)
        self._lm_over_tr: float = self.params.Lm * self._inv_tr
        self._lambda: float = self.derived.gamma
        self._k: float = self.derived.K

    def evaluate_derivatives(
        self,
        state: ElectricalState,
        u_stator: AlphaBeta,
        omega_r: float,
    ) -> StateDerivatives:
        """Calculates dx/dt = f(x, u, omega_r) per Chen et al. Eq. (3).

        Args:
            state: Current ElectricalState instance.
            u_stator: Applied stator voltage AlphaBeta vector [V].
            omega_r: Electrical rotor speed in rad/s (omega_r = pole_pairs * omega_mech).

        Returns:
            StateDerivatives instance with computed time derivatives.
        """
        # Coupled rotational back-EMF terms
        k_omega_psi_b = self._k * omega_r * state.psi_rbeta
        k_omega_psi_a = self._k * omega_r * state.psi_ralpha
        omega_psi_b = omega_r * state.psi_rbeta
        omega_psi_a = omega_r * state.psi_ralpha

        # Stator current derivatives (Eq. 3 lines 1-2)
        d_is_alpha = (
            -self._lambda * state.i_salpha
            + self._k_over_tr * state.psi_ralpha
            + k_omega_psi_b
            + self._inv_sigma_ls * u_stator.alpha
        )

        d_is_beta = (
            -self._lambda * state.i_sbeta
            - k_omega_psi_a
            + self._k_over_tr * state.psi_rbeta
            + self._inv_sigma_ls * u_stator.beta
        )

        # Rotor flux linkage derivatives (Eq. 3 lines 3-4)
        d_psi_ralpha = self._lm_over_tr * state.i_salpha - self._inv_tr * state.psi_ralpha - omega_psi_b
        d_psi_rbeta = self._lm_over_tr * state.i_sbeta + omega_psi_a - self._inv_tr * state.psi_rbeta

        return StateDerivatives(
            d_is_alpha=d_is_alpha,
            d_is_beta=d_is_beta,
            d_psi_ralpha=d_psi_ralpha,
            d_psi_rbeta=d_psi_rbeta,
        )

    def as_vector_derivative_function(
        self, omega_r: float
    ):
        """Adapter returning a callable matching the DerivativeFunction protocol:

            f(t: float, state_vec: np.ndarray, input_vec: np.ndarray) -> np.ndarray

        where:
            input_vec is [u_alpha, u_beta].
        """
        def derivative_func(t: float, state_arr: np.ndarray, inputs: np.ndarray) -> np.ndarray:
            curr_state = ElectricalState.from_numpy(state_arr)
            u_stat = AlphaBeta(alpha=float(inputs[0]), beta=float(inputs[1]))
            derivs = self.evaluate_derivatives(curr_state, u_stat, omega_r)
            return derivs.to_numpy()

        return derivative_func
