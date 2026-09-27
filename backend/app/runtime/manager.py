"""runtime/manager.py — supervises one worker task per motor.

A crash in one motor's loop is logged, counted, and the worker is rebuilt from
the durable DB state (active faults, sensor modes) after an exponential backoff.
Other motors are unaffected. With the Redis broker, a per-motor lock ensures
exactly one replica runs each motor; the others stand by and take over when the
lock expires.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.metrics import ML_BACKEND, WORKER_RESTARTS
from app.db.models import FaultInjected, Motor
from app.db.session import session_factory
from app.runtime.broker import Broker
from app.runtime.worker import MotorWorker, WorkerConfig, shared_classifier
from app.simulation.params import MotorParams

log = logging.getLogger(__name__)


def load_worker_config(motor_id: int, settings: Settings) -> WorkerConfig:
    with session_factory()() as db:
        motor = db.get(Motor, motor_id)
        if motor is None:
            raise LookupError(f"motor {motor_id} not found")
        faults = db.scalars(select(FaultInjected).where(FaultInjected.motor_id == motor_id,
                                                        FaultInjected.end_ts.is_(None))).all()
        return WorkerConfig(
            motor_id=motor.id, name=motor.name, params=MotorParams(**motor.params_json),
            base_load_nm=motor.base_load_nm,
            sensor_ids={s.type.value: s.id for s in motor.sensors},
            sensor_modes={s.type.value: s.mode.value for s in motor.sensors},
            active_faults=[{"id": f.id, "fault_type": f.fault_type, "severity": f.severity, "params": f.params_json}
                           for f in faults],
            realtime_factor=settings.realtime_factor, stream_hz=settings.stream_hz,
            persist_interval_s=settings.persist_interval_s, use_ml=settings.use_ml, seed=settings.sim_seed,
        )


class WorkerManager:
    def __init__(self, settings: Settings, broker: Broker, writer):
        self.settings = settings
        self.broker = broker
        self.writer = writer
        self.workers: dict[int, MotorWorker] = {}
        self.tasks: dict[int, asyncio.Task] = {}
        self.restarts: dict[int, int] = {}
        self.accepting = True

    def start(self, motor_id: int) -> None:
        if motor_id in self.tasks and not self.tasks[motor_id].done():
            return
        self.tasks[motor_id] = asyncio.create_task(self._supervise(motor_id), name=f"motor-{motor_id}")

    async def _supervise(self, motor_id: int) -> None:
        backoff = 1.0
        while True:
            if not await self.broker.acquire(motor_id):
                await asyncio.sleep(5.0)  # standby: another replica owns this motor
                continue
            renew = asyncio.create_task(self._renew(motor_id))
            started = time.monotonic()
            try:
                cfg = await asyncio.to_thread(load_worker_config, motor_id, self.settings)
                worker = MotorWorker(cfg, self.broker, self.writer)
                ML_BACKEND.set(1 if worker.engine.classifier.backend == "conv_bilstm" else 0)
                self.workers[motor_id] = worker
                await worker.run()
            except asyncio.CancelledError:
                raise
            except LookupError:
                log.warning("motor %s no longer exists; stopping its worker", motor_id)
                return
            except Exception:  # noqa: BLE001
                WORKER_RESTARTS.labels(str(motor_id)).inc()
                self.restarts[motor_id] = self.restarts.get(motor_id, 0) + 1
                log.exception("motor %s worker crashed; restarting in %.1fs", motor_id, backoff)
                if time.monotonic() - started > 60:
                    backoff = 1.0
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            finally:
                renew.cancel()
                self.workers.pop(motor_id, None)

    async def _renew(self, motor_id: int) -> None:
        while True:
            await asyncio.sleep(5.0)
            await self.broker.acquire(motor_id)

    async def stop(self, motor_id: int) -> None:
        task = self.tasks.pop(motor_id, None)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self.broker.release(motor_id)

    async def stop_all(self) -> None:
        self.accepting = False
        for mid in list(self.tasks):
            await self.stop(mid)

    def health(self, stale_after_s: float = 5.0) -> dict:
        now = time.monotonic()
        status = {}
        for mid, task in self.tasks.items():
            w = self.workers.get(mid)
            status[mid] = {
                "running": not task.done(),
                "owner": w is not None,
                "last_tick_age_s": None if w is None else round(now - w.last_tick, 2),
                "restarts": self.restarts.get(mid, 0),
            }
        return status

    def healthy(self) -> bool:
        if not self.settings.run_simulation:
            return True
        for s in self.health().values():
            if not s["running"]:
                return False
            if s["owner"] and s["last_tick_age_s"] is not None and s["last_tick_age_s"] > 5.0:
                return False
        return True

    async def start_all_from_db(self) -> None:
        def ids() -> list[int]:
            with session_factory()() as db:
                return list(db.scalars(select(Motor.id)).all())

        motor_ids = await asyncio.to_thread(ids)
        await asyncio.to_thread(shared_classifier, self.settings.use_ml)  # load the model once, up front
        for mid in motor_ids:
            self.start(mid)

    def get_prognosis(
        self,
        motor_id: int,
        db: Session | None = None,
        derate_thresh: float = 0.5,
        trip_thresh: float = 0.8,
    ) -> dict:
        w = self.workers.get(motor_id)
        if w is not None and len(w.severity_history) >= 5:
            return w.get_prognosis(derate_thresh, trip_thresh)
        if db is not None:
            from app.db.models import Diagnosis

            rows = db.scalars(
                select(Diagnosis)
                .where(Diagnosis.motor_id == motor_id)
                .order_by(Diagnosis.ts.desc())
                .limit(120)
            ).all()
            if len(rows) >= 5:
                history = [(r.ts.timestamp(), r.severity_score) for r in reversed(rows)]
                from app.diagnostics.prognosis import estimate_time_to_threshold

                return estimate_time_to_threshold(history, derate_thresh, trip_thresh)
        if w is not None:
            return w.get_prognosis(derate_thresh, trip_thresh)
        from app.diagnostics.prognosis import estimate_time_to_threshold

        return estimate_time_to_threshold([], derate_thresh, trip_thresh)

    def get_recommendation(self, motor_id: int, db: Session | None = None) -> dict:
        w = self.workers.get(motor_id)
        if w is not None and w._last_fault is not None:
            return w.get_recommendation()
        from app.diagnostics.recommendations import get_recommendation

        if db is not None:
            from app.db.models import Diagnosis

            latest = db.scalar(
                select(Diagnosis)
                .where(Diagnosis.motor_id == motor_id)
                .order_by(Diagnosis.ts.desc())
                .limit(1)
            )
            if latest is not None:
                mhi = latest.health_index if latest.health_index is not None else 100.0
                zone = "D" if mhi < 50 else ("C" if mhi < 70 else ("B" if mhi < 85 else "A"))
                return get_recommendation(motor_id, latest.fault_type, zone, mhi)
        return get_recommendation(motor_id, "healthy", "A", 100.0)
