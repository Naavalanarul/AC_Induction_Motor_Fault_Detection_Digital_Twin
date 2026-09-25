"""runtime/broker.py — pub/sub fan-out + latest-state cache + worker ownership.

`InMemoryBroker` serves a single backend process. `RedisBroker` lets several
backend replicas share live events: any replica can publish, every replica's
WebSocket clients receive, and a per-motor lock makes sure only one replica runs
each motor's simulation worker.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator

log = logging.getLogger(__name__)


class Broker:
    async def publish(self, topic: str, msg: dict) -> None: ...
    def subscribe(self, topic: str) -> contextlib.AbstractAsyncContextManager[AsyncIterator[dict]]: ...
    async def set_latest(self, motor_id: int, msg: dict) -> None: ...
    async def get_latest(self, motor_id: int) -> dict | None: ...
    async def acquire(self, motor_id: int) -> bool: ...
    async def release(self, motor_id: int) -> None: ...
    async def close(self) -> None: ...


class InMemoryBroker(Broker):
    def __init__(self, queue_size: int = 64):
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._latest: dict[int, dict] = {}
        self._queue_size = queue_size

    async def publish(self, topic: str, msg: dict) -> None:
        for q in list(self._subs.get(topic, ())):
            if q.full():  # slow consumer: drop its oldest message rather than block the publisher
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
            q.put_nowait(msg)

    @contextlib.asynccontextmanager
    async def subscribe(self, topic: str):
        q: asyncio.Queue = asyncio.Queue(self._queue_size)
        self._subs[topic].add(q)

        async def gen():
            while True:
                yield await q.get()

        try:
            yield gen()
        finally:
            self._subs[topic].discard(q)

    async def set_latest(self, motor_id: int, msg: dict) -> None:
        self._latest[motor_id] = msg

    async def get_latest(self, motor_id: int) -> dict | None:
        return self._latest.get(motor_id)

    async def acquire(self, motor_id: int) -> bool:
        return True

    async def release(self, motor_id: int) -> None:
        return None

    async def close(self) -> None:
        self._subs.clear()


class RedisBroker(Broker):
    LOCK_TTL_MS = 15000

    def __init__(self, url: str | None = None, client=None):
        if client is None:
            import redis.asyncio as redis

            client = redis.from_url(url, decode_responses=True)
        self.r = client
        self.node_id = uuid.uuid4().hex

    async def publish(self, topic: str, msg: dict) -> None:
        await self.r.publish(topic, json.dumps(msg, default=float))

    @contextlib.asynccontextmanager
    async def subscribe(self, topic: str):
        pubsub = self.r.pubsub()
        await pubsub.subscribe(topic)

        async def gen():
            async for m in pubsub.listen():
                if m.get("type") == "message":
                    yield json.loads(m["data"])

        try:
            yield gen()
        finally:
            await pubsub.unsubscribe(topic)
            await pubsub.aclose()

    async def set_latest(self, motor_id: int, msg: dict) -> None:
        await self.r.set(f"latest:{motor_id}", json.dumps(msg, default=float), ex=10)

    async def get_latest(self, motor_id: int) -> dict | None:
        raw = await self.r.get(f"latest:{motor_id}")
        return json.loads(raw) if raw else None

    async def acquire(self, motor_id: int) -> bool:
        key = f"owner:{motor_id}"
        if await self.r.set(key, self.node_id, nx=True, px=self.LOCK_TTL_MS):
            return True
        if await self.r.get(key) == self.node_id:  # renew our own lock
            await self.r.pexpire(key, self.LOCK_TTL_MS)
            return True
        return False

    async def release(self, motor_id: int) -> None:
        key = f"owner:{motor_id}"
        if await self.r.get(key) == self.node_id:
            await self.r.delete(key)

    async def close(self) -> None:
        await self.r.aclose()


def make_broker(redis_url: str | None) -> Broker:
    if redis_url:
        log.info("using Redis broker")
        return RedisBroker(redis_url)
    return InMemoryBroker()
