import asyncio
import json

import numpy as np

from app.sensors import SensorMode, SensorRegistry, SensorStatus, SensorType
from app.sensors.hardware import (
    HARDWARE_SENSORS,
    ADS1115CurrentSensor,
    CircuitBreaker,
    EncoderSpeedSensor,
    I2SAcousticSensor,
    MQTTVibrationSensor,
    ThermocoupleTempSensor,
    VoltageADCSensor,
)
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


def test_ads1115_current_sensor_acquisition_and_calibration():
    # 32768 counts = 4.096 V / 0.1 V/A = 40.96 A
    raw_counts = {"a": [3276], "b": [1638], "c": [-3276]}
    sensor = ADS1115CurrentSensor({
        "mock_reader": lambda: raw_counts,
        "volts_per_amp": 0.1,
        "pga_fsr": 4.096,
        "fs": 5000.0,
    })
    frame = asyncio.run(sensor.read())
    assert frame.status == SensorStatus.OK
    assert frame.sensor_type == SensorType.CURRENT
    assert frame.unit == "A"
    assert np.isclose(frame.data["a"][0], 4.095, atol=0.01)
    assert np.isclose(frame.data["b"][0], 2.047, atol=0.01)
    assert np.isclose(frame.data["c"][0], -4.095, atol=0.01)


def test_ads1115_current_sensor_failure_trips_breaker():
    def failing_reader():
        raise OSError("I2C bus error")

    sensor = ADS1115CurrentSensor({
        "mock_reader": failing_reader,
        "failure_threshold": 2,
    })
    frame1 = asyncio.run(sensor.read())
    assert frame1.status == SensorStatus.STALE
    assert "I2C bus error" in frame1.meta.get("reason", "")
    assert not sensor.breaker.is_open

    frame2 = asyncio.run(sensor.read())
    assert frame2.status == SensorStatus.STALE
    assert sensor.breaker.is_open

    # Next call fails fast without calling reader
    frame3 = asyncio.run(sensor.read())
    assert frame3.status == SensorStatus.STALE
    assert "circuit open" in frame3.meta.get("reason", "")


def test_mqtt_vibration_sensor_with_json_payload():
    payload = json.dumps({
        "x": [0.01, 0.02, 0.03],
        "y": [0.10, 0.20, 0.30],
        "z": [-0.05, 0.0, 0.05],
    })
    sensor = MQTTVibrationSensor({"mock_reader": lambda: payload, "fs": 12800.0})
    frame = asyncio.run(sensor.read())
    assert frame.status == SensorStatus.OK
    assert frame.sensor_type == SensorType.VIBRATION
    assert frame.unit == "m/s^2"
    assert frame.n == 3
    assert np.array_equal(frame.data["x"], [0.01, 0.02, 0.03])


def test_mqtt_vibration_sensor_client_interface():
    class MockMqttClient:
        def get_latest(self, topic):
            if topic == "sensors/vibration":
                return {"x": [1.0], "y": [2.0], "z": [3.0]}
            return None

    sensor = MQTTVibrationSensor({"client": MockMqttClient(), "topic": "sensors/vibration"})
    frame = asyncio.run(sensor.read())
    assert frame.status == SensorStatus.OK
    assert frame.data["y"][0] == 2.0


def test_voltage_adc_sensor():
    sensor = VoltageADCSensor({
        "mock_reader": lambda: {"a": [2.3], "b": [-1.15], "c": [-1.15]},
        "scale": 100.0,
    })
    frame = asyncio.run(sensor.read())
    assert frame.status == SensorStatus.OK
    assert frame.sensor_type == SensorType.VOLTAGE
    assert frame.unit == "V"
    assert np.isclose(frame.data["a"][0], 230.0)


def test_encoder_speed_sensor():
    sensor = EncoderSpeedSensor({
        "mock_reader": lambda: {"rpm": [1465.0, 1466.0]},
    })
    frame = asyncio.run(sensor.read())
    assert frame.status == SensorStatus.OK
    assert frame.sensor_type == SensorType.SPEED
    assert frame.unit == "rpm"
    assert frame.data["rpm"][0] == 1465.0


def test_thermocouple_temp_sensor():
    sensor = ThermocoupleTempSensor({
        "mock_reader": lambda: {"winding": 52.3},
    })
    frame = asyncio.run(sensor.read())
    assert frame.status == SensorStatus.OK
    assert frame.sensor_type == SensorType.TEMP
    assert frame.unit == "degC"
    assert frame.data["winding"][0] == 52.3


def test_i2s_acoustic_sensor():
    sensor = I2SAcousticSensor({
        "mock_reader": lambda: {"p": [0.001, 0.002, -0.001]},
    })
    frame = asyncio.run(sensor.read())
    assert frame.status == SensorStatus.OK
    assert frame.sensor_type == SensorType.ACOUSTIC
    assert frame.unit == "Pa"
    assert len(frame.data["p"]) == 3


def test_registry_full_hardware_mode():
    sim = MotorSimulator()
    configs = {
        SensorType.CURRENT: {"mock_reader": lambda: {"a": [100], "b": [-50], "c": [-50]}},
        SensorType.VOLTAGE: {"mock_reader": lambda: {"a": [2.3], "b": [-1.15], "c": [-1.15]}},
        SensorType.SPEED: {"mock_reader": lambda: {"rpm": [1470.0]}},
        SensorType.TEMP: {"mock_reader": lambda: {"winding": 45.0}},
        SensorType.VIBRATION: {"mock_reader": lambda: {"x": [0.1], "y": [0.2], "z": [0.3]}},
        SensorType.ACOUSTIC: {"mock_reader": lambda: {"p": [0.05]}},
    }
    all_hw_modes = {st: SensorMode.HARDWARE for st in SensorType}
    reg = SensorRegistry(sim.state, modes=all_hw_modes, configs=configs)
    assert len(HARDWARE_SENSORS) == len(SensorType)
    frames = asyncio.run(reg.read_all())
    assert all(f.status == SensorStatus.OK for f in frames.values())
    assert all(reg.mode_of(st) == SensorMode.HARDWARE for st in SensorType)
