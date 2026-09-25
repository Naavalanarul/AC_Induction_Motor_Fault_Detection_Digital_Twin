"""sensors/base.py

Common sensor interface. A simulated sensor and a real one are interchangeable
behind `Sensor.read()`; nothing above this layer knows which one it talks to.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

import numpy as np


class SensorType(str, Enum):
    CURRENT = "current"
    VIBRATION = "vibration"
    ACOUSTIC = "acoustic"
    TEMP = "temp"
    SPEED = "speed"
    VOLTAGE = "voltage"


class SensorMode(str, Enum):
    SIMULATED = "simulated"
    HARDWARE = "hardware"


class SensorStatus(str, Enum):
    OK = "ok"
    STALE = "stale"      # no fresh data (e.g. hardware not responding, circuit open)
    FAULT = "fault"


@dataclass
class SensorFrame:
    """One block of samples from one sensor.

    `data` maps a channel name (e.g. "a", "b", "c" or "x", "y", "z") to samples.
    `t0` is the timestamp of the first sample in simulation/acquisition seconds.
    """

    sensor_type: SensorType
    t0: float
    fs: float
    data: dict[str, np.ndarray]
    unit: str
    status: SensorStatus = SensorStatus.OK
    meta: dict = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(next(iter(self.data.values()))) if self.data else 0

    @classmethod
    def stale(cls, sensor_type: SensorType, unit: str, reason: str = "") -> SensorFrame:
        return cls(sensor_type, 0.0, 0.0, {}, unit, SensorStatus.STALE, {"reason": reason})


class Sensor(ABC):
    sensor_type: SensorType
    unit: str
    mode: SensorMode

    @abstractmethod
    async def read(self) -> SensorFrame: ...

    def calibrate(self, raw: np.ndarray | float) -> np.ndarray | float:
        """Raw counts -> physical units. Identity for simulated sensors."""
        return raw
