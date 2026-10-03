"""runtime/writer.py — batched, non-blocking DB writer with high-priority queue for critical audit records.

Telemetry (diagnoses, feature vectors, sensor readings) is queued by simulation workers
and written in batches. Critical audit records (SupervisoryAction, Alert, trip events) use a dedicated
high-priority queue that is never dropped under telemetry backpressure, retries with backoff during
DB outages, records to a dead-letter audit file, and replays upon DB recovery.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.core.metrics import (
    DB_BATCH_FAILED_TOTAL,
    DB_DEAD_LETTER_TOTAL,
    DB_DROPPED_TOTAL,
    DB_WRITE_ERRORS,
    DB_WRITE_SECONDS,
)
from app.db.models import Alert, SupervisoryAction
from app.db.session import session_factory

log = logging.getLogger(__name__)


class DBWriter:
    def __init__(
        self,
        max_batch: int = 500,
        max_queue: int = 20000,
        max_priority_queue: int = 5000,
        dead_letter_path: str = "dead_letter_audit.jsonl",
    ):
        self.queue: asyncio.Queue = asyncio.Queue(max_queue)
        self.priority_queue: asyncio.Queue = asyncio.Queue(max_priority_queue)
        self.max_batch = max_batch
        self._task: asyncio.Task | None = None
        self.dropped = 0
        self.priority_dropped = 0
        self.dead_letter_path = Path(dead_letter_path)
        self._notify_event: asyncio.Event = asyncio.Event()

    def put(self, obj: Any, priority: bool | None = None) -> None:
        """Enqueue an object for DB persistence. Automatically routes audit rows to high-priority queue."""
        if priority is None:
            priority = isinstance(obj, (SupervisoryAction, Alert))

        if priority:
            self.put_priority(obj)
            return

        try:
            self.queue.put_nowait(obj)
            self._notify_event.set()
        except asyncio.QueueFull:
            self.dropped += 1
            DB_WRITE_ERRORS.inc()
            DB_DROPPED_TOTAL.labels(priority="normal").inc()

    def put_priority(self, obj: Any) -> None:
        """Enqueue a safety-critical audit row to the high-priority queue."""
        try:
            self.priority_queue.put_nowait(obj)
            self._notify_event.set()
        except asyncio.QueueFull:
            # Under extreme pressure, immediately write to dead-letter log to prevent data loss
            self.priority_dropped += 1
            DB_DROPPED_TOTAL.labels(priority="high").inc()
            self._write_dead_letter([obj], reason="priority_queue_full")

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="db-writer")

    def _write(self, batch: list) -> None:
        t0 = time.perf_counter()
        with session_factory()() as db:
            db.add_all(batch)
            db.commit()
        DB_WRITE_SECONDS.observe(time.perf_counter() - t0)

    def _write_dead_letter(self, batch: list, reason: str = "unknown") -> None:
        DB_DEAD_LETTER_TOTAL.inc(len(batch))
        try:
            self.dead_letter_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.dead_letter_path, "a", encoding="utf-8") as f:
                for obj in batch:
                    row_data = {
                        "ts": time.time(),
                        "table": getattr(obj, "__tablename__", type(obj).__name__),
                        "reason": reason,
                    }
                    if hasattr(obj, "__dict__"):
                        for k, v in obj.__dict__.items():
                            if not k.startswith("_"):
                                if isinstance(v, (datetime, date)):
                                    row_data[k] = v.isoformat()
                                elif isinstance(v, (int, float, str, bool, type(None))):
                                    row_data[k] = v
                                else:
                                    row_data[k] = str(v)
                    f.write(json.dumps(row_data) + "\n")
        except Exception:
            log.exception("Failed to write dead letter file for %d rows", len(batch))

    async def _write_with_retry(self, batch: list, is_priority: bool = False) -> bool:
        max_attempts = 3 if is_priority else 1
        backoffs = [0.05, 0.1, 0.2]
        kind = "priority" if is_priority else "normal"

        for attempt in range(max_attempts):
            try:
                await asyncio.to_thread(self._write, batch)
                return True
            except Exception as exc:  # noqa: BLE001
                DB_WRITE_ERRORS.inc()
                DB_BATCH_FAILED_TOTAL.labels(kind=kind).inc()
                if attempt < max_attempts - 1:
                    log.warning(
                        "DB batch write failed (attempt %d/%d, %s, %d rows): %s; retrying...",
                        attempt + 1,
                        max_attempts,
                        kind,
                        len(batch),
                        exc,
                    )
                    await asyncio.sleep(backoffs[min(attempt, len(backoffs) - 1)])
                else:
                    log.exception("DB batch write failed permanently (%s, %d rows)", kind, len(batch))
                    self._write_dead_letter(batch, reason=f"db_write_error: {exc}")
                    if is_priority:
                        # Re-enqueue priority rows so they survive and commit once DB recovers
                        for item in batch:
                            try:
                                self.priority_queue.put_nowait(item)
                            except asyncio.QueueFull:
                                break
                        await asyncio.sleep(0.05)
        return False

    async def _drain_once(self) -> int:
        # 1. Drain priority queue first
        priority_batch: list[Any] = []
        while not self.priority_queue.empty() and len(priority_batch) < self.max_batch:
            try:
                priority_batch.append(self.priority_queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        if priority_batch:
            await self._write_with_retry(priority_batch, is_priority=True)
            return len(priority_batch)

        # 2. Drain normal queue if no priority items
        if not self.queue.empty():
            batch: list[Any] = []
            while not self.queue.empty() and len(batch) < self.max_batch:
                try:
                    batch.append(self.queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            if batch:
                await self._write_with_retry(batch, is_priority=False)
                return len(batch)

        # 3. Both empty, wait for next notification
        try:
            await asyncio.wait_for(self._notify_event.wait(), timeout=0.1)
            self._notify_event.clear()
        except TimeoutError:
            pass
        return 0

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
        while (not self.priority_queue.empty() or not self.queue.empty()) and time.monotonic() < deadline:
            drained = await self._drain_once()
            if drained == 0:
                break
