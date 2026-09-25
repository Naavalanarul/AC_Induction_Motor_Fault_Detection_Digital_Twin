"""Phase 1 validation: averaged plant vs event-driven PWM twin, and healthy-twin tracking."""

import math

import numpy as np
import pytest

from app.simulation.motor_twin import InverterCommand, MotorTwin
from app.simulation.params import DEFAULT_MOTOR
from app.simulation.plant import HealthyTwinObserver, MotorPlant, abc_to_alphabeta


def fundamental_amplitude(x: np.ndarray, fs: float, f0: float) -> float:
    n = len(x)
    t = np.arange(n) / fs
    return 2.0 * abs(np.dot(x, np.exp(-2j * math.pi * f0 * t))) / n


def test_plant_steady_state_is_physically_plausible():
    plant = MotorPlant(DEFAULT_MOTOR)
    plant.warm_start(load_torque=10.0, seconds=2.0)
    chunk = plant.simulate(5000, 10.0)
    rpm = chunk.omega_m.mean() * 30 / math.pi
    # 4-pole, 50 Hz: synchronous speed 1500 rpm, slip should be a few percent at rated load.
    assert 1400 < rpm < 1500
    # Te balances load plus viscous friction B*omega in steady state
    assert abs(chunk.te.mean() - (10.0 + plant.B * chunk.omega_m.mean())) < 0.05
    i_rms = np.sqrt(np.mean(chunk.i_abc**2, axis=1))
    assert np.allclose(i_rms, i_rms.mean(), rtol=0.01)  # balanced when healthy


def test_averaged_plant_matches_pwm_twin_fundamental():
    """The fast averaged plant must reproduce the PWM twin's 50 Hz current and speed."""
    duration = 0.25
    m = 0.9
    plant = MotorPlant(DEFAULT_MOTOR, fs=20000.0)
    udc = 2.0 * plant.v_peak / m
    twin = MotorTwin(DEFAULT_MOTOR, pwm_freq_hz=5000.0, max_step_size=2e-5, viscous_damping=plant.B)
    cmd = InverterCommand(u_dc=udc, fund_freq_hz=50.0, modulation_index=m)

    fs = 20000.0
    samples_t, samples_i, samples_w = [], [], []
    next_sample = 0.0
    while twin.t < duration:
        s = twin.tick(cmd, load_torque=2.0)
        if s.t >= next_sample:
            samples_t.append(s.t)
            samples_i.append(s.i_alphabeta.alpha)
            samples_w.append(s.omega_m)
            next_sample += 1.0 / fs

    chunk = plant.simulate(int(duration * fs), load_torque=2.0)
    ia_avg, _ = abc_to_alphabeta(chunk.i_abc)

    # Compare over the last 0.1 s (5 electrical periods)
    n_win = int(0.1 * fs)
    amp_pwm = fundamental_amplitude(np.array(samples_i[-n_win:]), fs, 50.0)
    amp_avg = fundamental_amplitude(ia_avg[-n_win:], fs, 50.0)
    assert amp_avg == pytest.approx(amp_pwm, rel=0.05)
    assert chunk.omega_m[-1] == pytest.approx(samples_w[-1], rel=0.05)


def test_healthy_twin_tracks_healthy_plant():
    plant = MotorPlant(DEFAULT_MOTOR)
    twin = HealthyTwinObserver(DEFAULT_MOTOR, plant.fs)
    for step in range(20):
        c = plant.simulate(500, 8.0)
        ua, ub = abc_to_alphabeta(c.u_abc)
        pa, pb = twin.run(ua, ub, c.omega_m * DEFAULT_MOTOR.pole_pairs)
    ia, ib = abc_to_alphabeta(c.i_abc)
    residual = np.sqrt(np.mean((ia - pa) ** 2 + (ib - pb) ** 2))
    current = np.sqrt(np.mean(ia**2 + ib**2))
    assert residual / current < 0.005
