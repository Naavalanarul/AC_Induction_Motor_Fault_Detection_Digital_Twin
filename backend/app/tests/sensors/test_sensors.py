import asyncio

import numpy as np

from app.sensors import SensorMode, SensorRegistry, SensorStatus, SensorType
from app.sensors.hardware import CircuitBreaker
from app.simulation.twin_state import MotorSimulator


def test_all_six_simulated_sensors_read_consistent_frames():
    sim = MotorSimulator()
    reg = SensorRegistry(sim.state)
    for _ in range(10):
        sim.step()
    frames = asyncio.run(reg.read_all())
    assert set(frames) == set(SensorType)
    assert all(f.status == SensorStatus.OK for f in frames.values())
    assert frames[SensorType.CURRENT].fs == 5000.0 and frames[SensorType.CURRENT].n == 500
    assert frames[SensorType.VIBRATION].n == 1280
    # speed sensor agrees with ground truth
    rpm_truth = sim.state.electrical.omega_m.mean() * 30 / np.pi
    assert abs(frames[SensorType.SPEED].data["rpm"].mean() - rpm_truth) < 1.0


def test_switch_to_hardware_degrades_to_stale_and_back():
    sim = MotorSimulator()
    reg = SensorRegistry(sim.state)
    sim.step()
    reg.set_mode(SensorType.VIBRATION, SensorMode.HARDWARE)
    assert reg.mode_of(SensorType.VIBRATION) == SensorMode.HARDWARE
    frame = asyncio.run(reg.sensors[SensorType.VIBRATION].read())
    assert frame.status == SensorStatus.STALE
    reg.set_mode(SensorType.VIBRATION, SensorMode.SIMULATED)
    assert asyncio.run(reg.sensors[SensorType.VIBRATION].read()).status == SensorStatus.OK


def test_circuit_breaker_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=2, reset_timeout_s=60)
    cb.record_failure()
    assert not cb.is_open
    cb.record_failure()
    assert cb.is_open
    cb.record_success()
    assert not cb.is_open
