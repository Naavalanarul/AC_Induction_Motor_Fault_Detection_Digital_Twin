"""runtime/writer.py — batched, non-blocking DB writer for high-rate telemetry.

Telemetry (diagnoses, feature vectors, SADA transitions, alerts) is queued by the
simulation workers and written in batches from a thread, so the event loop never
waits on MySQL. Operator-initiated records (fault injections, overrides) are NOT
written here: the API writes them synchronously before they are acted on.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from app.core.metrics import DB_WRITE_ERRORS, DB_WRITE_SECONDS
from app.db.session import session_factory

log = logging.getLogger(__name__)


class DBWriter:
    def __init__(self, max_batch: int = 500, max_queue: int = 20000):
        self.queue: asyncio.Queue = asyncio.Queue(max_queue)
        self.max_batch = max_batch
        self._task: asyncio.Task | None = None
        self.dropped = 0

    def put(self, obj) -> None:
        try:
            self.queue.put_nowait(obj)
        except asyncio.QueueFull:
            self.dropped += 1
            DB_WRITE_ERRORS.inc()

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="db-writer")

    def _write(self, batch: list) -> None:
        t0 = time.perf_counter()
        with session_factory()() as db:
            db.add_all(batch)
            db.commit()
        DB_WRITE_SECONDS.observe(time.perf_counter() - t0)

    async def _drain_once(self) -> int:
        batch = [await self.queue.get()]
        while len(batch) < self.max_batch and not self.queue.empty():
            batch.append(self.queue.get_nowait())
        try:
            await asyncio.to_thread(self._write, batch)
        except Exception:  # noqa: BLE001
            DB_WRITE_ERRORS.inc()
            log.exception("DB batch write failed (%d rows dropped)", len(batch))
        return len(batch)

    async def _run(self) -> None:
        while True:
            await self._drain_once()

    async def flush(self, timeout: float = 5.0) -> None:
        """Stop the background task and write everything still queued (graceful shutdown)."""
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        deadline = time.monotonic() + timeout
        while not self.queue.empty() and time.monotonic() < deadline:
            await self._drain_once()
