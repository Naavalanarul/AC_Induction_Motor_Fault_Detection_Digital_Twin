"""simulation/integrators.py

Object-Oriented implementation of numerical solvers and event-driven timestepping.
Generic and physics-agnostic.

References:
    Chen et al. (Energies 2025), Eq. (4)-(5) [4th-order Runge-Kutta formulation].
    Zhu et al. (IEEE TPEL 2019) [Discrete-state event-driven framework].
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Protocol, Union

import numpy as np


class DerivativeFunction(Protocol):
    """Protocol signature for state derivative evaluation: dx/dt = f(t, x, u)."""

    def __call__(self, t: float, state: np.ndarray, inputs: np.ndarray) -> np.ndarray:
        ...


# Type alias: inputs can be constant across the step or a time-evaluated function
InputType = Union[np.ndarray, Callable[[float], np.ndarray]]


class Integrator(ABC):
    """Abstract base class for numerical ODE solvers."""

    @abstractmethod
    def step(
        self,
        state: np.ndarray,
        t: float,
        h: float,
        f: DerivativeFunction,
        inputs: InputType,
    ) -> np.ndarray:
        """Advances the state vector by a single time step h: x(t + h)."""
        pass


class RungeKutta4(Integrator):
    """Classic 4th-order Runge-Kutta (RK4) integration engine.

    Equations:
        k1 = f(t,         x,              u(t))
        k2 = f(t + h/2,   x + (h/2) * k1, u(t + h/2))
        k3 = f(t + h/2,   x + (h/2) * k2, u(t + h/2))
        k4 = f(t + h,     x + h * k3,     u(t + h))
        x(t + h) = x + (h/6) * (k1 + 2*k2 + 2*k3 + k4)
    """

    def step(
        self,
        state: np.ndarray,
        t: float,
        h: float,
        f: DerivativeFunction,
        inputs: InputType,
    ) -> np.ndarray:
        half_h = 0.5 * h
        t_mid = t + half_h
        t_end = t + h

        # Resolve inputs at RK4 stages
        if callable(inputs):
            u1 = inputs(t)
            u2 = inputs(t_mid)
            u3 = u2  # Midpoint stage
            u4 = inputs(t_end)
        else:
            u1 = u2 = u3 = u4 = inputs

        # Stage evaluations
        k1 = f(t, state, u1)
        k2 = f(t_mid, state + half_h * k1, u2)
        k3 = f(t_mid, state + half_h * k2, u3)
        k4 = f(t_end, state + h * k3, u4)

        # Weighted combination
        return state + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


class EventDrivenStepController:
    """Controls time step sizing to hit discrete events (e.g., PWM switching).

    Prevents integrating across discontinuous boundaries, guaranteeing that inputs
    remain piecewise-constant within each numerical step.
    """

    def __init__(self, h_max: float, h_min: float = 1e-9):
        """
        Args:
            h_max: Maximum allowable integration step [s].
            h_min: Safety threshold to prevent infinite loops near boundaries [s].
        """
        if h_max <= h_min:
            raise ValueError("h_max must be strictly greater than h_min.")
        self.h_max = h_max
        self.h_min = h_min

    def compute_step(self, t_now: float, t_next_event: float | None) -> float:
        """Determines the step size h for the current step.

        Args:
            t_now: Current simulation timestamp [s].
            t_next_event: Target event timestamp [s], or None if no event is scheduled.

        Returns:
            float: Adaptive step size h <= h_max.
        """
        if t_next_event is None:
            return self.h_max

        time_to_event = t_next_event - t_now

        # Already at or slightly past boundary: take normal step
        if time_to_event <= self.h_min:
            return self.h_max

        # Cap the step so we land exactly on the event without exceeding h_max
        return min(time_to_event, self.h_max)


# ---------------------------------------------------------------------------
# Demonstration / Unit Test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Test system: dx/dt = -2*x + u (analytic solution with u=0: x(t) = exp(-2*t))
    class DecayModel:
        def __init__(self, decay_rate: float = 2.0):
            self.rate = decay_rate

        def derivatives(self, t: float, state: np.ndarray, u: np.ndarray) -> np.ndarray:
            return -self.rate * state + u

    # 1. Instantiate objects
    rk4 = RungeKutta4()
    controller = EventDrivenStepController(h_max=0.01)
    model = DecayModel(decay_rate=2.0)

    # 2. Run simulation with an artificial event at t = 0.035 s
    t_sim = 0.0
    t_event = 0.035
    state = np.array([1.0], dtype=np.float64)
    u_zero = np.array([0.0], dtype=np.float64)

    steps_taken = []
    while t_sim < 0.05:
        # Schedule the event if we haven't crossed it yet
        next_event = t_event if t_sim < t_event else None
        h = controller.compute_step(t_sim, next_event)

        state = rk4.step(state, t_sim, h, model.derivatives, u_zero)
        t_sim += h
        steps_taken.append((t_sim, h, state[0]))

    print("OOP RK4 + Adaptive Step Controller Test:")
    for t_val, h_val, val in steps_taken:
        print(f"  t = {t_val * 1e3:6.2f} ms | h = {h_val * 1e3:5.2f} ms | x = {val:.6f}")

    # Check if exact event boundary was hit
    landed_on_event = any(np.isclose(step[0], t_event, atol=1e-9) for step in steps_taken)
    print(f"\nExact Event Landing (t = {t_event*1e3} ms): {'PASSED' if landed_on_event else 'FAILED'}")
