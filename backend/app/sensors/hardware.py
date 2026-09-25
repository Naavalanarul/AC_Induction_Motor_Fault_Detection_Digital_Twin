"""sensors/hardware.py

Hardware sensor drop-ins (Phase 18, future). Each concrete class only has to
implement `_acquire()`; the base class adds a circuit breaker so an unresponsive
device degrades to a STALE frame instead of blocking the fusion layer.

The two concrete classes are placeholders: they document the intended wiring
but have no driver code yet, so they always report STALE.
"""

from __future__ import annotations

import time
from abc import abstractmethod

import numpy as np

from app.sensors.base import Sensor, SensorFrame, SensorMode, SensorType


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, reset_timeout_s: float = 10.0):
        self.failure_threshold = failure_threshold
        self.reset_timeout_s = reset_timeout_s
        self.failures = 0
        self.opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        if time.monotonic() - self.opened_at >= self.reset_timeout_s:
            return False  # half-open: allow one trial call
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = time.monotonic()


class HardwareSensor(Sensor):
    mode = SensorMode.HARDWARE

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.breaker = CircuitBreaker()

    @abstractmethod
    async def _acquire(self) -> SensorFrame: ...

    async def read(self) -> SensorFrame:
        if self.breaker.is_open:
            return SensorFrame.stale(self.sensor_type, self.unit, "circuit open")
        try:
            frame = await self._acquire()
        except Exception as exc:  # noqa: BLE001 - any driver error degrades to stale
            self.breaker.record_failure()
            return SensorFrame.stale(self.sensor_type, self.unit, f"{type(exc).__name__}: {exc}")
        self.breaker.record_success()
        return frame


class ADS1115CurrentSensor(HardwareSensor):
    """Reads 3 current transducers through an ADS1115 ADC over I2C (not implemented)."""

    sensor_type, unit = SensorType.CURRENT, "A"

    def calibrate(self, raw):
        # counts -> volts (+/-4.096 V FSR, 16-bit) -> amps (transducer gain, e.g. 0.1 V/A)
        gain = float(self.config.get("volts_per_amp", 0.1))
        return np.asarray(raw) * (4.096 / 32768.0) / gain

    async def _acquire(self) -> SensorFrame:
        raise NotImplementedError("ADS1115 driver not implemented yet")


class MQTTVibrationSensor(HardwareSensor):
    """Subscribes to an ESP32 publishing accelerometer blocks over MQTT (not implemented)."""

    sensor_type, unit = SensorType.VIBRATION, "m/s^2"

    async def _acquire(self) -> SensorFrame:
        raise NotImplementedError("MQTT vibration client not implemented yet")


class UnimplementedHardwareSensor(HardwareSensor):
    """Placeholder for channels that have no hardware driver yet."""

    def __init__(self, sensor_type: SensorType, unit: str, config: dict | None = None):
        super().__init__(config)
        self.sensor_type, self.unit = sensor_type, unit

    async def _acquire(self) -> SensorFrame:
        raise NotImplementedError(f"no hardware driver for {self.sensor_type.value}")


HARDWARE_SENSORS = {
    SensorType.CURRENT: ADS1115CurrentSensor,
    SensorType.VIBRATION: MQTTVibrationSensor,
}
