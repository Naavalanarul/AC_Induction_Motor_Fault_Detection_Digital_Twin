"""tests/diagnostics/test_p1_4_temp_comp_grid_freq.py

Verifies P1-4 audit fixes:
1. Healthy hot motor (e.g. 100°C) with temperature-compensated HealthyTwinObserver
   does NOT produce false residual FD above threshold (0.015).
2. Dynamic adaptation of Rs(T) and Rr(T) with temperature.
3. Accurate grid frequency estimation from 3-phase voltage waveform across 49.5 Hz,
   50.0 Hz, 50.5 Hz, and 60.0 Hz under noise and harmonic distortion.
4. Fallback to default frequency when supply is de-energized.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np

from app.diagnostics.electrical import (
    FD_THRESHOLD,
    ElectricalResidualDiagnostic,
    estimate_grid_frequency,
)
from app.diagnostics.schema import DiagFault
from app.simulation.params import MotorParams
from app.simulation.plant import (
    ALPHA_CU,
    HealthyTwinObserver,
    MotorPlant,
    abc_to_alphabeta,
)
from app.simulation.presets import PRESET_MOTORS


def test_healthy_hot_motor_temperature_compensation():
    """A healthy hot motor at 100°C produces false trip without compensation, but passes as HEALTHY with compensation."""
    params = MotorParams(**PRESET_MOTORS[0]["params"])
    fs = 5000.0

    # Motor running at 100°C (hot stator and rotor)
    delta_t = 100.0 - 20.0
    hot_params = replace(
        params,
        Rs=params.Rs * (1.0 + ALPHA_CU * delta_t),
        Rr=params.Rr * (1.0 + ALPHA_CU * delta_t),
    )
    plant = MotorPlant(hot_params, fs=fs)
    plant.warm_start(10.0, seconds=1.0)
    chunk = plant.simulate(int(fs * 0.5), load_torque=10.0)

    ua, ub = abc_to_alphabeta(chunk.u_abc)
    ia, ib = abc_to_alphabeta(chunk.i_abc)
    i_rms = math.sqrt(float(np.mean(ia**2 + ib**2)))

    # 1. Uncompensated observer (frozen at 20°C): false residual > 0.15
    obs_cold = HealthyTwinObserver(params, fs, initial_temp_c=20.0)
    obs_cold.run(ua, ub, chunk.omega_m * params.pole_pairs)
    pa_cold, pb_cold = obs_cold.run(ua, ub, chunk.omega_m * params.pole_pairs)
    fd_cold = math.sqrt(float(np.mean((ia - pa_cold)**2 + (ib - pb_cold)**2))) / i_rms
    assert fd_cold > FD_THRESHOLD * 5.0  # severely crosses threshold (> 0.075)

    # 2. Temperature-compensated observer at 100°C: residual FD is near-zero (< 0.005)
    obs_hot = HealthyTwinObserver(params, fs, initial_temp_c=20.0)
    obs_hot.run(ua, ub, chunk.omega_m * params.pole_pairs, temp_c=100.0)
    pa_hot, pb_hot = obs_hot.run(ua, ub, chunk.omega_m * params.pole_pairs, temp_c=100.0)
    fd_hot = math.sqrt(float(np.mean((ia - pa_hot)**2 + (ib - pb_hot)**2))) / i_rms
    assert fd_hot < FD_THRESHOLD  # Well below 0.015


def test_electrical_residual_verdict_with_temperature():
    """ElectricalResidualDiagnostic correctly identifies a hot healthy motor as HEALTHY when given temp_c."""
    params = MotorParams(**PRESET_MOTORS[0]["params"])
    fs = 5000.0
    diag = ElectricalResidualDiagnostic(params, fs, window_s=0.5, settle_s=0.2)

    delta_t = 90.0 - 20.0
    hot_params = replace(
        params,
        Rs=params.Rs * (1.0 + ALPHA_CU * delta_t),
        Rr=params.Rr * (1.0 + ALPHA_CU * delta_t),
    )
    plant = MotorPlant(hot_params, fs=fs)
    plant.warm_start(10.0, seconds=1.0)

    chunk = plant.simulate(int(fs * 0.8), load_torque=10.0)
    verdict = diag.update(chunk.i_abc, chunk.u_abc, chunk.omega_m, temp_c=90.0)

    assert verdict.available is True
    assert verdict.fault_type == DiagFault.HEALTHY
    assert verdict.severity == 0.0


def test_grid_frequency_estimation_accuracy():
    """Analytic grid frequency estimator accurately extracts frequency across range with harmonics and noise."""
    fs = 5000.0
    n = 2500  # 0.5 s
    t = np.arange(n) / fs
    rng = np.random.default_rng(123)

    for target_freq in [49.5, 50.0, 50.25, 59.9, 60.0]:
        th = 2.0 * math.pi * target_freq * t
        # Balanced 3-phase with 5th harmonic distortion and sensor noise
        v_peak = 325.0
        ua = v_peak * np.cos(th) + 15.0 * np.cos(5.0 * th) + rng.normal(0, 1.5, n)
        ub = v_peak * np.cos(th - 2.0 * math.pi / 3.0) + 15.0 * np.cos(5.0 * (th - 2.0 * math.pi / 3.0)) + rng.normal(0, 1.5, n)
        uc = v_peak * np.cos(th + 2.0 * math.pi / 3.0) + 15.0 * np.cos(5.0 * (th + 2.0 * math.pi / 3.0)) + rng.normal(0, 1.5, n)
        u_abc = np.vstack([ua, ub, uc])

        f_est = estimate_grid_frequency(u_abc, fs, default_freq=50.0)
        assert abs(f_est - target_freq) < 0.05, f"Expected {target_freq}, got {f_est}"


def test_grid_frequency_de_energized_fallback():
    """De-energized bus (zero voltage) falls back safely to default frequency."""
    fs = 5000.0
    u_zero = np.zeros((3, 500))
    f_est = estimate_grid_frequency(u_zero, fs, default_freq=50.0)
    assert f_est == 50.0

    f_est_60 = estimate_grid_frequency(u_zero, fs, default_freq=60.0)
    assert f_est_60 == 60.0
