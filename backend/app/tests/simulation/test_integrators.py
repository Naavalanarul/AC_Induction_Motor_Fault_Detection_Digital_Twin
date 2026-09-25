"""tests/test_integrators.py

Verification suite for the RungeKutta4 integrator.
Confirms numerical accuracy and 4th-order convergence rate (~16x error reduction when halving h)
against the analytical benchmark problem: dy/dt = -y.
"""

import math

import numpy as np

from app.simulation.integrators import EventDrivenStepController, RungeKutta4


# ---------------------------------------------------------------------------
# Test Model: dy/dt = -y  => Exact solution: y(t) = y0 * exp(-t)
# ---------------------------------------------------------------------------
def linear_decay_derivative(t: float, state: np.ndarray, inputs: np.ndarray) -> np.ndarray:
    """Computes dy/dt = -y. inputs is unused for this autonomous test system."""
    return -state


def solve_decay_to_target(
    integrator: RungeKutta4,
    y0: float,
    t_end: float,
    h: float,
) -> float:
    """Integrates dy/dt = -y from t=0 to t=t_end using fixed step size h."""
    state = np.array([y0], dtype=np.float64)
    dummy_input = np.array([0.0], dtype=np.float64)
    t = 0.0

    # Number of steps required to reach t_end
    n_steps = int(round(t_end / h))
    for _ in range(n_steps):
        state = integrator.step(state, t, h, linear_decay_derivative, dummy_input)
        t += h

    return float(state[0])


# ---------------------------------------------------------------------------
# Convergence & Unit Tests
# ---------------------------------------------------------------------------
class TestRungeKutta4:
    """Test suite targeting RK4 implementation and order of convergence."""

    def test_rk4_step_single_step_taylor_accuracy(self):
        """A single RK4 step on dy/dt = -y should match Taylor expansion up to h^4."""
        rk4 = RungeKutta4()
        h = 0.1
        y0 = 1.0
        state = np.array([y0], dtype=np.float64)
        dummy_input = np.array([0.0], dtype=np.float64)

        # Numerical step
        y_next = rk4.step(state, t=0.0, h=h, f=linear_decay_derivative, inputs=dummy_input)[0]

        # RK4 polynomial for dy/dt = -y: 1 - h + h^2/2 - h^3/6 + h^4/24
        expected_taylor = y0 * (1.0 - h + (h**2) / 2.0 - (h**3) / 6.0 + (h**4) / 24.0)
        assert math.isclose(y_next, expected_taylor, rel_tol=1e-12)

    def test_rk4_fourth_order_convergence(self):
        """Verifies global error shrinks by ~16x when step size h is halved.

        Uses step sizes: h, h/2, h/4, h/8 with h = 0.2 down to 0.025 at t_target = 1.0.
        """
        rk4 = RungeKutta4()
        t_end = 1.0
        y0 = 1.0
        exact_solution = math.exp(-t_end)

        step_sizes = [0.2, 0.1, 0.05, 0.025]
        errors: list[float] = []

        for h in step_sizes:
            y_num = solve_decay_to_target(rk4, y0, t_end, h)
            err = abs(y_num - exact_solution)
            errors.append(err)

        # Compute error reduction factors when halving h
        # ratios[i] = errors[i] / errors[i + 1]
        convergence_ratios = [errors[i] / errors[i + 1] for i in range(len(errors) - 1)]

        print("\nRK4 Step-Size Convergence Analysis (t = 1.0 s):")
        for h, err in zip(step_sizes, errors, strict=True):
            print(f"  h = {h:6.4f} s | Absolute Error = {err:12.6e}")

        print("Error reduction ratios (expected ~16.0 for 4th order):")
        for i, ratio in enumerate(convergence_ratios):
            h_curr, h_next = step_sizes[i], step_sizes[i + 1]
            print(f"  Ratio (h={h_curr} -> h={h_next}): {ratio:.2f}")

        # Assert that all ratios cluster near 16.0
        for ratio in convergence_ratios:
            # ~16 asymptotically; the coarsest step is pre-asymptotic (~17.4). 3rd order would give ~8.
            assert 14.5 <= ratio <= 18.0, (
                f"Convergence ratio {ratio:.2f} deviates from expected ~16.0. "
                "Integrator may have dropped order."
            )

    def test_rk4_time_varying_callable_input(self):
        """Tests that rk4_step properly evaluates callable inputs at intermediate stages."""
        rk4 = RungeKutta4()

        # Problem: dy/dt = u(t), where u(t) = 2*t.
        # Exact solution from y(0) = 0 is y(t) = t^2.
        def pure_integrator_derivative(t: float, state: np.ndarray, inputs: np.ndarray) -> np.ndarray:
            return inputs

        def time_dependent_input(t: float) -> np.ndarray:
            return np.array([2.0 * t], dtype=np.float64)

        h = 0.5
        state0 = np.array([0.0], dtype=np.float64)

        # Single step to t = 0.5 s: exact y(0.5) = (0.5)^2 = 0.25
        state_next = rk4.step(
            state=state0,
            t=0.0,
            h=h,
            f=pure_integrator_derivative,
            inputs=time_dependent_input,
        )

        assert math.isclose(state_next[0], 0.25, abs_tol=1e-12)


class TestEventDrivenStepController:
    """Test suite for adaptive event-driven step boundary alignment."""

    def test_step_landing_on_event(self):
        controller = EventDrivenStepController(h_max=1e-4)

        # Case 1: Event occurs within h_max horizon
        t_now = 0.00100
        t_event = 0.00104  # 40 µs away (< 100 µs h_max)
        h = controller.compute_step(t_now, t_next_event=t_event)
        assert math.isclose(h, 40e-6, abs_tol=1e-12)

        # Case 2: Event occurs beyond h_max horizon
        t_event_far = 0.00150  # 500 µs away (> 100 µs h_max)
        h = controller.compute_step(t_now, t_next_event=t_event_far)
        assert math.isclose(h, 1e-4, abs_tol=1e-12)

        # Case 3: No scheduled event
        h = controller.compute_step(t_now, t_next_event=None)
        assert math.isclose(h, 1e-4, abs_tol=1e-12)
