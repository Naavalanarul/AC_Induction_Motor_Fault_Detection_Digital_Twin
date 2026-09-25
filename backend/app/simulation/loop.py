"""simulation/loop.py

Real-time-paced asyncio driver for the digital twin simulation loop.
Publishes MotorState snapshots to an asyncio.Queue for downstream decoupling.

Architecture:
    Producer (MotorTwin Loop) ---> asyncio.Queue ---> Consumers (Telemetry, DB, WebSockets)
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional

from app.simulation.motor_twin import InverterCommand, MotorState, MotorTwin

logger = logging.getLogger(__name__)


# Dynamic command and load provider callbacks: (sim_time_s) -> value
CommandProvider = Callable[[float], InverterCommand]
LoadProvider = Callable[[float], float]


@dataclass(frozen=True)
class SimulationLoopConfig:
    """Configuration parameters for the real-time pacing engine."""

    sample_rate_hz: float = 1000.0   # Frequency of snapshots emitted to queue [Hz]
    realtime_factor: float = 1.0     # 1.0 = 1x real-world speed; 2.0 = 2x speed; 0.0 = uncapped
    queue_maxsize: int = 2000        # Maximum buffer capacity before drop/backpressure
    drop_on_overflow: bool = True    # If True, discard oldest frame on buffer full; else block


class AsyncSimulationDriver:
    """Orchestrates real-time execution of the MotorTwin ODE solver inside an asyncio event loop."""

    def __init__(
        self,
        twin: MotorTwin,
        queue: asyncio.Queue[MotorState],
        command_provider: CommandProvider,
        load_provider: LoadProvider,
        config: SimulationLoopConfig = SimulationLoopConfig(),
    ):
        self.twin = twin
        self.queue = queue
        self.get_command = command_provider
        self.get_load = load_provider
        self.config = config

        self._dt_sample = 1.0 / config.sample_rate_hz
        self._is_running = False
        self._stop_requested = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return self._is_running

    def stop(self) -> None:
        """Signals the simulation loop to stop gracefully."""
        self._stop_requested.set()

    async def run(self, max_duration_s: Optional[float] = None) -> None:
        """Runs the real-time paced simulation loop.

        Args:
            max_duration_s: Optional duration in simulation seconds. If None, runs indefinitely.
        """
        self._is_running = True
        self._stop_requested.clear()

        sim_start_time = self.twin.t
        sim_target_end = (sim_start_time + max_duration_s) if max_duration_s is not None else None

        loop = asyncio.get_running_loop()
        wall_start_time = loop.time()

        logger.info(
            "Starting Async MotorTwin Driver at %.1f Hz (RT factor: %.2fx)",
            self.config.sample_rate_hz,
            self.config.realtime_factor,
        )

        try:
            while not self._stop_requested.is_set():
                if sim_target_end is not None and self.twin.t >= sim_target_end:
                    break

                target_sim_time = self.twin.t + self._dt_sample

                # 1. Advance the digital twin by micro-steps until target_sim_time is reached
                latest_snapshot: MotorState | None = None
                while self.twin.t < target_sim_time:
                    cmd = self.get_command(self.twin.t)
                    tl = self.get_load(self.twin.t)
                    latest_snapshot = self.twin.tick(cmd, load_torque=tl)

                # 2. Push snapshot to the decoupled queue
                if latest_snapshot is not None:
                    self._dispatch_snapshot(latest_snapshot)

                # 3. Real-time pacing with clock drift compensation
                if self.config.realtime_factor > 0.0:
                    sim_progress = self.twin.t - sim_start_time
                    expected_wall_time = wall_start_time + (sim_progress / self.config.realtime_factor)
                    current_wall_time = loop.time()
                    time_to_sleep = expected_wall_time - current_wall_time

                    if time_to_sleep > 0.0:
                        await asyncio.sleep(time_to_sleep)
                    else:
                        # Solver is lagging behind real-time budget; yield execution
                        await asyncio.sleep(0)
                else:
                    # Uncapped speed: yield cooperatively to event loop
                    await asyncio.sleep(0)

        finally:
            self._is_running = False
            logger.info("Simulation driver stopped at simulation time t=%.4f s", self.twin.t)

    def _dispatch_snapshot(self, snapshot: MotorState) -> None:
        """Pushes state to queue, managing backpressure according to policy."""
        try:
            self.queue.put_nowait(snapshot)
        except asyncio.QueueFull:
            if self.config.drop_on_overflow:
                try:
                    _ = self.queue.get_nowait()  # Drop oldest frame
                    self.queue.put_nowait(snapshot)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass
            else:
                logger.warning("Downstream queue is saturated at t=%.4f s", snapshot.t)


async def simulation_loop(
    twin: MotorTwin,
    queue: asyncio.Queue[MotorState],
    command_provider: CommandProvider,
    load_provider: LoadProvider,
    config: SimulationLoopConfig = SimulationLoopConfig(),
    max_duration_s: Optional[float] = None,
) -> None:
    """Functional entrypoint for Step 9 driving the simulation loop asynchronously."""
    driver = AsyncSimulationDriver(
        twin=twin,
        queue=queue,
        command_provider=command_provider,
        load_provider=load_provider,
        config=config,
    )
    await driver.run(max_duration_s=max_duration_s)
