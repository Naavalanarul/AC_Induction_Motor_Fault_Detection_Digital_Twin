"""tests/static_analysis/test_steady_state.py

Validates the steady-state solver against:
1. Classical textbook reference (Chapman "Electric Machinery Fundamentals" Ex 7.2).
2. The repository's digital twin simulator (MotorPlant steady state).
"""

import math

import numpy as np
import pytest

from app.simulation.params import DEFAULT_MOTOR, MotorParams
from app.simulation.plant import MotorPlant
from app.static_analysis.steady_state import solve_steady_state


def test_steady_state_solver_textbook_chapman():
    """Validates against Chapman Example 7.2:

    460 V line-line, 60 Hz, 4-pole (p=2), Y-connected motor:
    R1 = 0.641 Ohms, R2 = 0.332 Ohms, X1 = 1.106 Ohms, X2 = 0.464 Ohms, Xm = 26.3 Ohms.
    At slip s = 0.022 (speed = 1760.4 rpm):
    Chapman reports:
      I_s = 18.88 A (or 18.89 A), PF = 0.833 lagging, P_in = 12.53 kW,
      P_ag = 11.84 kW, P_conv = 11.58 kW, Torque = 62.8 N*m.
    """
    f = 60.0
    w_e = 2.0 * math.pi * f
    p = 2
    x_ls = 1.106
    x_lr = 0.464
    x_m = 26.3

    l_m = x_m / w_e
    l_ls = x_ls / w_e
    l_lr = x_lr / w_e

    chapman_motor = MotorParams(
        Rs=0.641,
        Rr=0.332,
        Ls=l_m + l_ls,
        Lr=l_m + l_lr,
        Lm=l_m,
        J=0.1,
        pole_pairs=p,
        rated_power=18650.0,  # 25 hp
        rated_voltage=460.0,
        rated_current=24.0,
        rated_speed=1760.4,
        rated_torque=100.0,
    )

    v_phase_rms = 460.0 / math.sqrt(3.0)
    speed_rpm = 1760.4

    res = solve_steady_state(chapman_motor, v_phase_rms, f, speed_rpm)

    assert res.slip == pytest.approx(0.022, rel=1e-3)
    assert res.stator_current_mag == pytest.approx(18.89, abs=0.05)
    assert res.power_factor == pytest.approx(0.832, abs=0.01)
    assert res.real_power_w == pytest.approx(12525.0, rel=0.01)
    assert res.mechanical_power_w == pytest.approx(11578.0, rel=0.01)
    assert res.torque_developed_nm == pytest.approx(62.8, abs=0.2)


def test_steady_state_solver_matches_simulator():
    """Validates that steady-state equivalent circuit matches MotorPlant steady-state current."""
    plant = MotorPlant(DEFAULT_MOTOR)
    plant.warm_start(load_torque=10.0, seconds=2.0)
    chunk = plant.simulate(5000, 10.0)

    mean_rpm = chunk.omega_m.mean() * 30.0 / math.pi
    sim_i_rms = float(np.mean(np.sqrt(np.mean(chunk.i_abc ** 2, axis=1))))

    v_phase_rms = DEFAULT_MOTOR.rated_voltage / math.sqrt(3.0)
    res = solve_steady_state(DEFAULT_MOTOR, v_phase_rms, 50.0, mean_rpm)

    # Must agree within 1% of simulated steady-state current
    assert res.stator_current_mag == pytest.approx(sim_i_rms, rel=0.01)
    # Developed torque balances 10 Nm load + viscous damping B*omega
    expected_torque = 10.0 + plant.B * chunk.omega_m.mean()
    assert res.torque_developed_nm == pytest.approx(expected_torque, rel=0.02)
