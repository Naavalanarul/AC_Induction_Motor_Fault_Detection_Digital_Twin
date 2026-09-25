"""sensors/simulated.py

Simulated sensors. Each pulls from the shared `MotorTwinState` and adds its own
measurement imperfections (noise, bandwidth/decimation, quantization).
"""

from __future__ import annotations

import math

import numpy as np

from app.sensors.base import Sensor, SensorFrame, SensorMode, SensorType
from app.simulation.twin_state import MotorTwinState


class _SimBase(Sensor):
    mode = SensorMode.SIMULATED

    def __init__(self, state: MotorTwinState, seed: int | None = None, noise: float | None = None):
        self.state = state
        self.rng = np.random.default_rng(seed)
        if noise is not None:
            self.noise = noise

    def _noisy(self, x: np.ndarray) -> np.ndarray:
        return x + self.rng.normal(0.0, self.noise, size=x.shape)


class SimulatedCurrentSensor(_SimBase):
    """3-phase Hall-effect current transducer, 12-bit over +/-50 A."""

    sensor_type, unit, noise = SensorType.CURRENT, "A", 0.02
    lsb = 100.0 / 4096

    async def read(self) -> SensorFrame:
        ch = self.state.electrical
        i = np.round(self._noisy(ch.i_abc) / self.lsb) * self.lsb
        return SensorFrame(self.sensor_type, float(ch.t[0]), ch.fs, {"a": i[0], "b": i[1], "c": i[2]}, self.unit)


class SimulatedVoltageSensor(_SimBase):
    sensor_type, unit, noise = SensorType.VOLTAGE, "V", 0.5

    async def read(self) -> SensorFrame:
        ch = self.state.electrical
        u = self._noisy(ch.u_abc)
        return SensorFrame(self.sensor_type, float(ch.t[0]), ch.fs, {"a": u[0], "b": u[1], "c": u[2]}, self.unit)


class SimulatedSpeedSensor(_SimBase):
    """Incremental encoder, speed estimated at 1 kHz."""

    sensor_type, unit, noise = SensorType.SPEED, "rpm", 0.5
    decimate = 5

    async def read(self) -> SensorFrame:
        ch = self.state.electrical
        rpm = ch.omega_m[self.decimate - 1 :: self.decimate] * 30.0 / math.pi
        return SensorFrame(self.sensor_type, float(ch.t[self.decimate - 1]), ch.fs / self.decimate,
                           {"rpm": self._noisy(rpm)}, self.unit)


class SimulatedTempSensor(_SimBase):
    """Winding thermocouple, one sample per read."""

    sensor_type, unit, noise = SensorType.TEMP, "degC", 0.15

    async def read(self) -> SensorFrame:
        temp = self._noisy(np.array([self.state.temperature_c]))
        return SensorFrame(self.sensor_type, self.state.t, 0.0, {"winding": temp}, self.unit)


class SimulatedVibrationSensor(_SimBase):
    """Tri-axial accelerometer (m/s^2)."""

    sensor_type, unit, noise = SensorType.VIBRATION, "m/s^2", 0.02

    async def read(self) -> SensorFrame:
        v = self._noisy(self.state.vibration)
        t0 = self.state.t - v.shape[1] / self.state.vib_fs
        return SensorFrame(self.sensor_type, t0, self.state.vib_fs, {"x": v[0], "y": v[1], "z": v[2]}, self.unit)


class SimulatedAcousticSensor(_SimBase):
    sensor_type, unit, noise = SensorType.ACOUSTIC, "Pa", 0.002

    async def read(self) -> SensorFrame:
        a = self._noisy(self.state.acoustic)
        t0 = self.state.t - len(a) / self.state.acoustic_fs
        return SensorFrame(self.sensor_type, t0, self.state.acoustic_fs, {"p": a}, self.unit)


SIMULATED_SENSORS: dict[SensorType, type[_SimBase]] = {
    SensorType.CURRENT: SimulatedCurrentSensor,
    SensorType.VOLTAGE: SimulatedVoltageSensor,
    SensorType.SPEED: SimulatedSpeedSensor,
    SensorType.TEMP: SimulatedTempSensor,
    SensorType.VIBRATION: SimulatedVibrationSensor,
    SensorType.ACOUSTIC: SimulatedAcousticSensor,
}
