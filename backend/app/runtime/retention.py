"""runtime/retention.py — periodic deletion of old high-volume rows.

Deletes `sensor_readings` and `diagnoses` older than RETENTION_DAYS in batches.
Fault injections, supervisory actions and alerts are kept (audit trail).
Roll-up/archival to cheaper storage is not implemented; export before deleting
if you need long-term history.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete, select

from app.db.models import Diagnosis, SensorReading, utcnow
from app.db.session import session_factory

log = logging.getLogger(__name__)


def purge_old(days: int, batch: int = 5000) -> dict[str, int]:
    cutoff = utcnow() - timedelta(days=days)
    removed = {}
    with session_factory()() as db:
        for model in (SensorReading, Diagnosis):
            total = 0
            while True:
                ids = db.scalars(select(model.id).where(model.ts < cutoff).limit(batch)).all()
                if not ids:
                    break
                db.execute(delete(model).where(model.id.in_(ids)))
                db.commit()
                total += len(ids)
            removed[model.__tablename__] = total
    return removed


async def retention_loop(days: int, interval_s: float) -> None:
    while True:
        try:
            removed = await asyncio.to_thread(purge_old, days)
            if any(removed.values()):
                log.info("retention purge removed %s", removed)
        except Exception:  # noqa: BLE001
            log.exception("retention purge failed")
        await asyncio.sleep(interval_s)
