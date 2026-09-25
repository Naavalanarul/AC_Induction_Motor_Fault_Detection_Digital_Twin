import asyncio

from app.simulation.loop import SimulationLoopConfig, simulation_loop
from app.simulation.motor_twin import InverterCommand, MotorTwin
from app.simulation.params import DEFAULT_MOTOR


def test_async_driver_emits_snapshots_and_drops_oldest_on_overflow():
    async def main():
        twin = MotorTwin(DEFAULT_MOTOR)
        q: asyncio.Queue = asyncio.Queue(maxsize=5)
        cmd = InverterCommand(u_dc=600.0, fund_freq_hz=50.0, modulation_index=0.9)
        cfg = SimulationLoopConfig(sample_rate_hz=1000.0, realtime_factor=0.0, queue_maxsize=5)
        await simulation_loop(twin, q, lambda t: cmd, lambda t: 0.0, cfg, max_duration_s=0.01)
        items = [q.get_nowait() for _ in range(q.qsize())]
        return twin, items

    twin, items = asyncio.run(main())
    assert twin.t >= 0.01
    assert len(items) == 5  # bounded queue kept only the newest snapshots
    assert items[-1].t > items[0].t
