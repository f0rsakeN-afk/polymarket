import asyncio
import time
from typing import Optional

import redis.asyncio as redis
from redis.asyncio import ConnectionPool

from app.config import settings


def get_redis() -> redis.Redis:
    """For async FastAPI routes — each call gets a fresh client with its own pool.

    redis.asyncio.Redis.from_url() creates an internal ConnectionPool, so this is
    safe for concurrent use within a single event loop. The per-call pattern avoids
    cross-test contamination since each test's app gets its own client instances.
    """
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


class RedisCircuitBreaker:
    """
    Circuit breaker for Redis operations.
    CLOSED (normal) → OPEN (failing) → HALF-OPEN (testing)
    After 5 consecutive failures, circuit opens for 30s.
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failures = 0
        self._last_failure: float = 0
        self._state = "closed"  # closed | open | half_open
        self._lock = asyncio.Lock()

    async def call(self, op):
        """Call an async op with circuit breaker protection. Lock is NOT held during I/O."""
        async with self._lock:
            if self._state == "open":
                if time.time() - self._last_failure >= self.recovery_timeout:
                    self._state = "half_open"
                else:
                    raise redis.RedisError("Redis circuit breaker open")
            elif self._state == "half_open":
                pass  # allow one test through

        try:
            result = await op()
            async with self._lock:
                self._failures = 0
                self._state = "closed"
            return result
        except Exception as e:
            async with self._lock:
                self._failures += 1
                self._last_failure = time.time()
                if self._failures >= self.failure_threshold:
                    self._state = "open"
            raise e


redis_cb = RedisCircuitBreaker()
