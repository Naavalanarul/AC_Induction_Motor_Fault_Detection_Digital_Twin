"""WebSocket / multi-motor load test.

Opens V concurrent viewers spread across M motors (creating motors if needed)
and reports delivered frame rate, inter-arrival jitter, and the backend's own
simulation lag from /metrics. Establishes a capacity baseline instead of guessing.

    pip install websockets httpx
    python loadtest/ws_load.py --base http://localhost:8080 --user admin --password ... \
        --motors 4 --viewers 100 --seconds 30
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time

import httpx
import websockets


async def viewer(url: str, stop: float, stats: list):
    arrivals = []
    try:
        async with websockets.connect(url, max_size=8 * 2**20, open_timeout=20) as ws:
            while time.monotonic() < stop:
                try:
                    await asyncio.wait_for(ws.recv(), timeout=max(0.1, stop - time.monotonic()))
                    arrivals.append(time.monotonic())
                except TimeoutError:
                    break
    except Exception as exc:  # noqa: BLE001
        stats.append({"error": repr(exc)})
        return
    stats.append({"arrivals": arrivals})


def metric(text: str, name: str) -> list[float]:
    return [float(line.rsplit(" ", 1)[1]) for line in text.splitlines() if line.startswith(name)]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--metrics-url", default=None, help="backend /metrics URL (not exposed through nginx)")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", required=True)
    ap.add_argument("--motors", type=int, default=2)
    ap.add_argument("--viewers", type=int, default=50)
    ap.add_argument("--seconds", type=float, default=30)
    a = ap.parse_args()

    async with httpx.AsyncClient(base_url=a.base, timeout=20) as c:
        tok = (await c.post("/api/v1/auth/login", json={"username": a.user, "password": a.password})).json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}
        motors = (await c.get("/api/v1/motors", headers=h)).json()
        while len(motors) < a.motors:
            r = await c.post("/api/v1/motors", json={"name": f"Load Motor {len(motors) + 1}"}, headers=h)
            r.raise_for_status()
            motors.append(r.json())
        ids = [m["id"] for m in motors[: a.motors]]
        await asyncio.sleep(3)  # let new workers start

    ws_base = a.base.replace("http", "ws", 1)
    stop = time.monotonic() + a.seconds
    stats: list = []
    t0 = time.monotonic()
    await asyncio.gather(*(viewer(f"{ws_base}/api/v1/ws/motors/{ids[i % len(ids)]}/stream?token={tok}", stop, stats)
                           for i in range(a.viewers)))
    elapsed = time.monotonic() - t0

    errors = [s["error"] for s in stats if "error" in s]
    ok = [s["arrivals"] for s in stats if "arrivals" in s]
    rates = [len(x) / elapsed for x in ok]
    gaps = [b - a_ for x in ok for a_, b in zip(x, x[1:], strict=False)]
    print(f"motors={len(ids)} viewers={a.viewers} duration={elapsed:.1f}s")
    print(f"connected={len(ok)} errors={len(errors)} {errors[:3]}")
    if rates:
        print(f"frames/s per viewer: mean {statistics.mean(rates):.2f}  min {min(rates):.2f}")
        print(f"total frames/s delivered: {sum(rates):.0f}")
    if gaps:
        q = statistics.quantiles(gaps, n=100)
        print(f"inter-frame gap ms: p50 {q[49] * 1000:.0f}  p95 {q[94] * 1000:.0f}  p99 {q[98] * 1000:.0f}")
    if a.metrics_url:
        text = httpx.get(a.metrics_url, timeout=10).text
        lag = metric(text, "dt_sim_lag_seconds{")
        print(f"backend sim lag s (per motor): {[round(x, 3) for x in lag]}")


if __name__ == "__main__":
    asyncio.run(main())
