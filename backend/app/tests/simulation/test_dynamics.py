import math

import numpy as np

from app.simulation.dynamics import ElectricalState, InductionMotorElectricalDynamics
from app.simulation.params import CHEN_2025_MOTOR, DEFAULT_MOTOR
from app.simulation.transforms import AlphaBeta


def test_derived_constants_match_closed_form():
    d = DEFAULT_MOTOR.compute_derived_constants()
    p = DEFAULT_MOTOR
    assert math.isclose(d.sigma, 1 - p.Lm**2 / (p.Ls * p.Lr))
    assert math.isclose(d.Tr, p.Lr / p.Rr)
    assert math.isclose(d.lambda_, d.gamma)


def test_zero_state_zero_input_has_zero_derivative():
    dyn = InductionMotorElectricalDynamics(CHEN_2025_MOTOR)
    d = dyn.evaluate_derivatives(ElectricalState.zero(), AlphaBeta(0.0, 0.0), omega_r=100.0)
    assert np.allclose(d.to_numpy(), 0.0)


def test_voltage_drives_current_with_inverse_sigma_ls_gain():
    dyn = InductionMotorElectricalDynamics(DEFAULT_MOTOR)
    d = dyn.evaluate_derivatives(ElectricalState.zero(), AlphaBeta(10.0, 0.0), omega_r=0.0)
    sigma = DEFAULT_MOTOR.compute_derived_constants().sigma
    assert math.isclose(d.d_is_alpha, 10.0 / (sigma * DEFAULT_MOTOR.Ls))
    assert d.d_is_beta == 0.0
