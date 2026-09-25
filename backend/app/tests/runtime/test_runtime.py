import asyncio
import os
from datetime import timedelta

import pytest

from app.runtime.broker import InMemoryBroker, RedisBroker


def test_inmemory_broker_fanout_and_slow_consumer_drop():
    async def main():
        b = InMemoryBroker(queue_size=2)
        async with b.subscribe("t") as s1, b.subscribe("t") as s2:
            for i in range(5):
                await b.publish("t", {"i": i})
            it1, it2 = s1.__aiter__(), s2.__aiter__()
            got1 = [(await it1.__anext__())["i"] for _ in range(2)]
            got2 = [(await it2.__anext__())["i"] for _ in range(2)]
        assert got1 == got2 == [3, 4]  # oldest dropped for slow consumers
        await b.set_latest(1, {"x": 1})
        assert await b.get_latest(1) == {"x": 1}

    asyncio.run(main())


@pytest.mark.skipif(not os.environ.get("TEST_REDIS_URL"), reason="TEST_REDIS_URL not set")
def test_redis_broker_pubsub_and_ownership():
    async def main():
        a, b = RedisBroker(os.environ["TEST_REDIS_URL"]), RedisBroker(os.environ["TEST_REDIS_URL"])
        await a.r.flushdb()
        assert await a.acquire(7) is True
        assert await b.acquire(7) is False  # only one replica owns a motor
        assert await a.acquire(7) is True   # renewal
        await a.release(7)
        assert await b.acquire(7) is True
        async with b.subscribe("motor:7") as stream:
            await asyncio.sleep(0.1)
            await a.publish("motor:7", {"hello": 1})
            msg = await asyncio.wait_for(stream.__aiter__().__anext__(), 5)
        assert msg == {"hello": 1}
        await a.set_latest(7, {"t": 1.0})
        assert await b.get_latest(7) == {"t": 1.0}
        await a.close()
        await b.close()

    asyncio.run(main())


@pytest.fixture
def sqlite_db(tmp_path, monkeypatch):
    from app.config import get_settings
    from app.db import session
    from app.db.models import Base

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/r.db")
    get_settings.cache_clear()
    eng = session.init_engine()
    Base.metadata.create_all(eng)
    yield eng
    get_settings.cache_clear()


def test_writer_flushes_on_shutdown(sqlite_db):
    from sqlalchemy import func, select

    from app.db.models import Alert, Motor
    from app.db.session import session_factory
    from app.runtime.writer import DBWriter

    with session_factory()() as db:
        db.add(Motor(id=1, name="m", rated_power=1, rated_speed=1, rated_torque=1, params_json={}))
        db.commit()

    async def main():
        w = DBWriter()
        w.start()
        for i in range(50):
            w.put(Alert(motor_id=1, severity="info", message=f"a{i}"))
        await w.flush()

    asyncio.run(main())
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(Alert)) == 50


def test_retention_purges_old_rows_only(sqlite_db):
    from sqlalchemy import func, select

    from app.db.models import Diagnosis, Motor, utcnow
    from app.db.session import session_factory
    from app.runtime.retention import purge_old

    with session_factory()() as db:
        db.add(Motor(id=1, name="m", rated_power=1, rated_speed=1, rated_torque=1, params_json={}))
        db.commit()
        for age in (40, 35, 1):
            db.add(Diagnosis(motor_id=1, ts=utcnow() - timedelta(days=age), fault_type="healthy", confidence=1,
                             severity_score=0, per_sensor_scores_json={}))
        db.commit()
    assert purge_old(30)["diagnoses"] == 2
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(Diagnosis)) == 1


def test_supervisor_restarts_crashed_worker(sqlite_db, monkeypatch):
    import dataclasses

    from app.api.routes.motors import create_motor_row
    from app.config import Settings
    from app.db.session import session_factory
    from app.runtime import manager as mgr
    from app.simulation.params import DEFAULT_MOTOR

    with session_factory()() as db:
        create_motor_row(db, "m1", dataclasses.asdict(DEFAULT_MOTOR), 5.0)
    calls = {"n": 0}
    orig_run = mgr.MotorWorker.run

    async def flaky_run(self):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated crash")
        await orig_run(self)

    monkeypatch.setattr(mgr.MotorWorker, "run", flaky_run)

    async def main():
        m = mgr.WorkerManager(Settings(use_ml=False, realtime_factor=4.0), InMemoryBroker(), None)
        await m.start_all_from_db()
        for _ in range(100):
            await asyncio.sleep(0.05)
            if calls["n"] >= 2 and m.workers:
                break
        h = m.health()
        await m.stop_all()
        return h

    health = asyncio.run(main())
    assert calls["n"] >= 2
    assert list(health.values())[0]["restarts"] == 1
