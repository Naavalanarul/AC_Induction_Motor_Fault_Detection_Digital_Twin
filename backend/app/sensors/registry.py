"""sensors/registry.py

Decides at startup (and at runtime, via the API) which implementation backs each
channel: `mode: "simulated" | "hardware"` per sensor. Switching to hardware is a
config change, not a rewrite.
"""

from __future__ import annotations

from app.sensors.base import Sensor, SensorMode, SensorType
from app.sensors.hardware import HARDWARE_SENSORS, UnimplementedHardwareSensor
from app.sensors.simulated import SIMULATED_SENSORS
from app.simulation.twin_state import MotorTwinState

UNITS = {
    SensorType.CURRENT: "A", SensorType.VOLTAGE: "V", SensorType.SPEED: "rpm",
    SensorType.TEMP: "degC", SensorType.VIBRATION: "m/s^2", SensorType.ACOUSTIC: "Pa",
}


class SensorRegistry:
    def __init__(self, state: MotorTwinState, modes: dict[SensorType, SensorMode] | None = None,
                 configs: dict[SensorType, dict] | None = None, seed: int | None = 0):
        self.state = state
        self.seed = seed
        self.configs = configs or {}
        self.sensors: dict[SensorType, Sensor] = {}
        for i, st in enumerate(SensorType):
            mode = (modes or {}).get(st, SensorMode.SIMULATED)
            self.sensors[st] = self._build(st, mode, i)

    def _build(self, st: SensorType, mode: SensorMode, idx: int = 0) -> Sensor:
        if mode == SensorMode.SIMULATED:
            seed = None if self.seed is None else self.seed * 100 + idx
            return SIMULATED_SENSORS[st](self.state, seed=seed)
        cls = HARDWARE_SENSORS.get(st)
        cfg = self.configs.get(st, {})
        return cls(cfg) if cls else UnimplementedHardwareSensor(st, UNITS[st], cfg)

    def set_mode(self, st: SensorType, mode: SensorMode) -> Sensor:
        self.sensors[st] = self._build(st, mode, list(SensorType).index(st))
        return self.sensors[st]

    def mode_of(self, st: SensorType) -> SensorMode:
        return self.sensors[st].mode

    async def read_all(self):
        return {st: await s.read() for st, s in self.sensors.items()}
