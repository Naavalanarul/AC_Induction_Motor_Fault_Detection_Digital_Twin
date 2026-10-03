"""tests/diagnostics/test_p1_6_thermal_channel.py — P1-6 Thermal diagnostic regression tests."""

from __future__ import annotations

from app.diagnostics.schema import DiagFault
from app.diagnostics.thermal import ThermalDiagnostic
from app.simulation.mechanical_signals import ThermalModel
from app.simulation.params import MotorParams
from app.simulation.presets import PRESET_MOTORS


def test_p1_6_conveyor_warmup_no_false_overheating():
    """P1-6: Healthy Conveyor motor warm-up past 60 °C at rated load does not trip false overheating."""
    conveyor_preset = PRESET_MOTORS[2]
    params = MotorParams(**conveyor_preset["params"])
    r_th = params.get_thermal_resistance()
    tau_s = getattr(params, "tau_s", 180.0)
    t_amb = getattr(params, "t_ambient", 25.0)

    sim_thermal = ThermalModel(t_ambient=t_amb, r_th=r_th, tau_s=tau_s)
    diag = ThermalDiagnostic(params=params)

    # Conveyor rated electrical losses
    p_loss = 1.5 * (params.Rs + params.Rr) * (params.rated_current**2) + 0.025 * params.rated_power

    # Simulate 120 seconds of warm-up starting cold from 25 °C
    dt = 0.1
    t = 0.0
    temperatures = []
    verdicts = []

    for _ in range(1200):
        t += dt
        temp = sim_thermal.step(dt, p_loss)
        verdict = diag.update(t, temp, i_rms=params.rated_current, dt=dt)
        temperatures.append(temp)
        verdicts.append(verdict)

    # Final temperature should exceed 60 °C (typical Conveyor reaches ~68 °C in 120s)
    assert temperatures[-1] > 60.0, f"Expected warm-up past 60 °C, got {temperatures[-1]:.1f} °C"

    # Crucial assertion: throughout the entire 120s warm-up, never trigger OVERHEATING
    for idx, v in enumerate(verdicts):
        assert v.fault_type == DiagFault.HEALTHY, (
            f"False overheating triggered at t={idx*dt:.1f}s, temp={temperatures[idx]:.1f}°C: {v.details}"
        )
        assert v.severity == 0.0


def test_p1_6_cooling_failure_detected_by_thermal_residual():
    """P1-6: Cooling failure (e.g. broken fan / clogged ducts) is flagged via twin residual."""
    conveyor_preset = PRESET_MOTORS[2]
    params = MotorParams(**conveyor_preset["params"])
    diag = ThermalDiagnostic(params=params)

    # Motor running at light load (half rated current)
    half_current = params.rated_current * 0.5
    dt = 0.5
    t = 0.0

    # Advance twin for 60 seconds
    for _ in range(120):
        t += dt
        # Twin would expect temp ~35-40 °C, but cooling failure causes measured temp to surge to 80 °C
        v = diag.update(t, temp_c=80.0, i_rms=half_current, dt=dt)

    assert v.fault_type == DiagFault.OVERHEATING
    assert v.severity > 0.3
    assert v.details["thermal_residual_c"] > 25.0


def test_p1_6_runaway_rate_of_rise_detected():
    """P1-6: Extreme rate of rise exceeding calibrated max_rise triggers overheating."""
    diag = ThermalDiagnostic(warn_c=120.0, trip_c=145.0, tau_s=180.0, t_ambient=25.0)

    # Inject rapid surge of 70 °C/min (exceeding ~42 °C/min threshold)
    t = 0.0
    temp = 62.0
    for _ in range(20):
        t += 0.5
        temp += 0.6  # 1.2 °C/s = 72 °C/min
        v = diag.update(t, temp)

    assert v.fault_type == DiagFault.OVERHEATING
    assert v.details["rise_c_per_min"] > diag.max_rise


def test_p1_6_absolute_warn_and_trip_limits():
    """P1-6: Absolute warn and trip limits are strictly observed."""
    diag = ThermalDiagnostic(warn_c=120.0, trip_c=145.0)

    # Normal below warn
    v_norm = diag.update(1.0, 110.0)
    assert v_norm.fault_type == DiagFault.HEALTHY

    # Exceeding warn limit
    v_warn = diag.update(2.0, 125.0)
    assert v_warn.fault_type == DiagFault.OVERHEATING
    assert v_warn.severity >= 0.5
    assert not v_warn.details["critical"]

    # Exceeding trip limit
    v_trip = diag.update(3.0, 146.0)
    assert v_trip.fault_type == DiagFault.OVERHEATING
    assert v_trip.severity == 1.0
    assert v_trip.details["critical"]
