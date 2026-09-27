"""sensors/hardware.py

Hardware sensor implementations (Phase 18). Each concrete class implements
`_acquire()`; the base class adds a circuit breaker so an unresponsive or
disconnected device degrades to a STALE frame instead of blocking the fusion layer.

Supported hardware channels:
- `ADS1115CurrentSensor`: 16-bit I2C ADC reading 3-phase current transducers.
- `MQTTVibrationSensor`: Tri-axial accelerometer streaming over MQTT from an edge MCU (e.g. ESP32).
- `VoltageADCSensor`: Potential-transformer ADC reader for 3-phase voltage.
- `EncoderSpeedSensor`: Incremental encoder / pulse-counter speed reader.
- `ThermocoupleTempSensor`: Thermocouple amplifier / Modbus temperature reader.
- `I2SAcousticSensor`: Digital I2S MEMS microphone reader for acoustic pressure.
"""

from __future__ import annotations

import json
import logging
import time
from abc import abstractmethod
from typing import Any

import numpy as np

from app.sensors.base import Sensor, SensorFrame, SensorMode, SensorType

log = logging.getLogger(__name__)


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
        self.breaker = CircuitBreaker(
            failure_threshold=int(self.config.get("failure_threshold", 3)),
            reset_timeout_s=float(self.config.get("reset_timeout_s", 10.0)),
        )

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
    """Reads 3 current transducers through an ADS1115 ADC over I2C."""

    sensor_type, unit = SensorType.CURRENT, "A"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.address = int(self.config.get("i2c_address", 0x48))
        self.bus_num = int(self.config.get("i2c_bus", 1))
        self.pga_fsr = float(self.config.get("pga_fsr", 4.096))
        self.volts_per_amp = float(self.config.get("volts_per_amp", 0.1))
        self.fs = float(self.config.get("fs", 5000.0))

    def calibrate(self, raw: Any) -> np.ndarray:
        # counts -> volts (+/-4.096 V FSR, 16-bit signed) -> amps
        return np.asarray(raw, dtype=np.float64) * (self.pga_fsr / 32768.0) / self.volts_per_amp

    async def _acquire(self) -> SensorFrame:
        reader = self.config.get("mock_reader") or self.config.get("reader")
        if callable(reader):
            raw = reader()
            t0 = time.time()
            if isinstance(raw, dict) and "a" in raw:
                ia, ib, ic = self.calibrate(raw["a"]), self.calibrate(raw["b"]), self.calibrate(raw["c"])
            elif isinstance(raw, (list, tuple, np.ndarray)) and len(raw) == 3:
                ia, ib, ic = self.calibrate(raw[0]), self.calibrate(raw[1]), self.calibrate(raw[2])
            else:
                raise ValueError(f"invalid ADS1115 raw reading: {type(raw)}")
            return SensorFrame(self.sensor_type, t0, self.fs, {"a": ia, "b": ib, "c": ic}, self.unit)

        # Real hardware path via smbus2 if available
        try:
            import smbus2  # type: ignore[import-not-found]

            with smbus2.SMBus(self.bus_num) as bus:
                # Read 3 channels (A0, A1, A2 single-ended relative to GND)
                counts = []
                for ch_idx in range(3):
                    # Config register: single-ended channel, PGA=4.096V, single-shot
                    mux = 0x4000 | (ch_idx << 12)
                    cfg_word = mux | 0x8183
                    bus.write_word_data(self.address, 0x01, ((cfg_word & 0xFF) << 8) | (cfg_word >> 8))
                    time.sleep(0.002)
                    raw_val = bus.read_word_data(self.address, 0x00)
                    signed_val = ((raw_val & 0xFF) << 8) | (raw_val >> 8)
                    if signed_val > 32767:
                        signed_val -= 65536
                    counts.append(signed_val)
                ia, ib, ic = [self.calibrate([c]) for c in counts]
                return SensorFrame(self.sensor_type, time.time(), self.fs, {"a": ia, "b": ib, "c": ic}, self.unit)
        except ImportError as err:
            raise NotImplementedError("ADS1115 requires smbus2 or a configured reader callback") from err


class MQTTVibrationSensor(HardwareSensor):
    """Subscribes to an ESP32 or MQTT broker publishing accelerometer frames."""

    sensor_type, unit = SensorType.VIBRATION, "m/s^2"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.topic = str(self.config.get("topic", "sensors/vibration"))
        self.fs = float(self.config.get("fs", 12800.0))
        self._last_frame: dict[str, np.ndarray] | None = None

    async def _acquire(self) -> SensorFrame:
        reader = self.config.get("mock_reader") or self.config.get("reader")
        if callable(reader):
            data = reader()
            t0 = time.time()
            if isinstance(data, str):
                data = json.loads(data)
            if isinstance(data, dict):
                x = np.asarray(data.get("x", []), dtype=np.float64)
                y = np.asarray(data.get("y", []), dtype=np.float64)
                z = np.asarray(data.get("z", []), dtype=np.float64)
                return SensorFrame(self.sensor_type, t0, self.fs, {"x": x, "y": y, "z": z}, self.unit)
            raise ValueError(f"invalid MQTT vibration payload format: {type(data)}")

        client = self.config.get("client")
        if client is not None and hasattr(client, "get_latest"):
            payload = client.get_latest(self.topic)
            if payload is None:
                raise TimeoutError(f"no vibration payload received on topic {self.topic}")
            if isinstance(payload, str):
                payload = json.loads(payload)
            x, y, z = (np.asarray(payload[k], dtype=np.float64) for k in ("x", "y", "z"))
            return SensorFrame(self.sensor_type, time.time(), self.fs, {"x": x, "y": y, "z": z}, self.unit)

        raise NotImplementedError("MQTT vibration sensor requires an active client or reader callback")


class VoltageADCSensor(HardwareSensor):
    """Reads 3-phase supply voltage via potential transformers and ADC."""

    sensor_type, unit = SensorType.VOLTAGE, "V"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.fs = float(self.config.get("fs", 5000.0))
        self.scale = float(self.config.get("scale", 100.0))

    async def _acquire(self) -> SensorFrame:
        reader = self.config.get("mock_reader") or self.config.get("reader")
        if callable(reader):
            raw = reader()
            t0 = time.time()
            if isinstance(raw, dict):
                u = {k: np.asarray(raw[k], dtype=np.float64) * self.scale for k in ("a", "b", "c")}
            else:
                u = {"a": np.asarray(raw[0]) * self.scale, "b": np.asarray(raw[1]) * self.scale, "c": np.asarray(raw[2]) * self.scale}
            return SensorFrame(self.sensor_type, t0, self.fs, u, self.unit)
        raise NotImplementedError("VoltageADCSensor requires a hardware driver or reader callback")


class EncoderSpeedSensor(HardwareSensor):
    """Reads motor shaft speed from a hardware incremental encoder or tachometer."""

    sensor_type, unit = SensorType.SPEED, "rpm"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.pulses_per_rev = int(self.config.get("pulses_per_rev", 1024))
        self.fs = float(self.config.get("fs", 1000.0))

    async def _acquire(self) -> SensorFrame:
        reader = self.config.get("mock_reader") or self.config.get("reader")
        if callable(reader):
            raw = reader()
            t0 = time.time()
            rpm = np.asarray(raw["rpm"] if isinstance(raw, dict) else raw, dtype=np.float64)
            return SensorFrame(self.sensor_type, t0, self.fs, {"rpm": rpm}, self.unit)
        raise NotImplementedError("EncoderSpeedSensor requires a pulse capture driver or reader callback")


class ThermocoupleTempSensor(HardwareSensor):
    """Reads winding temperature from thermocouple amplifier (e.g. MAX31855) or RTD."""

    sensor_type, unit = SensorType.TEMP, "degC"

    async def _acquire(self) -> SensorFrame:
        reader = self.config.get("mock_reader") or self.config.get("reader")
        if callable(reader):
            val = reader()
            temp = float(val["winding"] if isinstance(val, dict) else val)
            return SensorFrame(self.sensor_type, time.time(), 0.0, {"winding": np.array([temp])}, self.unit)
        raise NotImplementedError("ThermocoupleTempSensor requires a temperature driver or reader callback")


class I2SAcousticSensor(HardwareSensor):
    """Reads acoustic sound pressure via digital I2S microphone or USB audio."""

    sensor_type, unit = SensorType.ACOUSTIC, "Pa"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.fs = float(self.config.get("fs", 25600.0))

    async def _acquire(self) -> SensorFrame:
        reader = self.config.get("mock_reader") or self.config.get("reader")
        if callable(reader):
            raw = reader()
            t0 = time.time()
            p = np.asarray(raw["p"] if isinstance(raw, dict) else raw, dtype=np.float64)
            return SensorFrame(self.sensor_type, t0, self.fs, {"p": p}, self.unit)
        raise NotImplementedError("I2SAcousticSensor requires an audio device driver or reader callback")


class UnimplementedHardwareSensor(HardwareSensor):
    """Placeholder for channels that have no hardware driver configured."""

    def __init__(self, sensor_type: SensorType, unit: str, config: dict | None = None):
        super().__init__(config)
        self.sensor_type, self.unit = sensor_type, unit

    async def _acquire(self) -> SensorFrame:
        raise NotImplementedError(f"no hardware driver for {self.sensor_type.value}")


HARDWARE_SENSORS: dict[SensorType, type[HardwareSensor]] = {
    SensorType.CURRENT: ADS1115CurrentSensor,
    SensorType.VOLTAGE: VoltageADCSensor,
    SensorType.SPEED: EncoderSpeedSensor,
    SensorType.TEMP: ThermocoupleTempSensor,
    SensorType.VIBRATION: MQTTVibrationSensor,
    SensorType.ACOUSTIC: I2SAcousticSensor,
}
