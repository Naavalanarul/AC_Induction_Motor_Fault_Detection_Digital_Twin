"""core/ratelimit.py — in-memory token-bucket rate limiter (per process).

With several backend replicas each replica enforces its own budget; a shared
(Redis-backed) limiter is not implemented yet.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from fastapi import HTTPException, Request, status


class TokenBucket:
    def __init__(self, rate_per_min: int):
        self.capacity = max(1, rate_per_min)
        self.rate = rate_per_min / 60.0
        self.buckets: dict[str, tuple[float, float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        tokens, last = self.buckets.get(key, (float(self.capacity), now))
        tokens = min(self.capacity, tokens + (now - last) * self.rate)
        if tokens < 1.0:
            self.buckets[key] = (tokens, now)
            return False
        self.buckets[key] = (tokens - 1.0, now)
        return True


def rate_limit(name: str, rate_getter: Callable[[], int]) -> Callable:
    buckets: dict[int, TokenBucket] = {}

    async def dependency(request: Request) -> None:
        rate = rate_getter()
        bucket = buckets.setdefault(rate, TokenBucket(rate))
        client = request.client.host if request.client else "unknown"
        if not bucket.allow(f"{name}:{client}"):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate limit exceeded", headers={"Retry-After": "60"})

    return dependency
