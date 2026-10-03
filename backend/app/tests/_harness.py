from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.runtime.broker import InMemoryBroker
from app.runtime.worker import MotorWorker, WorkerConfig
from app.simulation.params import DEFAULT_MOTOR, MotorParams


def make(
    params: MotorParams = DEFAULT_MOTOR,
    load: float = 8.0,
    use_ml: bool = False,
    faults: list[dict] | None = None,
    seed: int = 0,
) -> MotorWorker:
    cfg = WorkerConfig(
        motor_id=1,
        name="t",
        params=params,
        base_load_nm=load,
        sensor_ids={},
        active_faults=faults or [],
        realtime_factor=0,
        use_ml=use_ml,
        seed=seed,
    )
    return MotorWorker(cfg, InMemoryBroker(), None)


async def run(w: MotorWorker, seconds: float, cb: Callable[[int, dict[str, Any]], None] | None = None) -> dict[str, Any] | None:
    out = None
    steps = int(seconds / w.sim.chunk_s)
    for i in range(steps):
        out = await w.tick()
        if cb:
            cb(i, out)
    return out
