import asyncio
import time

import redis.asyncio as redis

from app.config import settings

# ─── Shared Redis client (one connection pool per worker process) ────────────
# Creating a new Redis client per call creates a new connection pool each time,
# exhausting Redis file descriptors under load. A module-level singleton reuses
# the pool safely within a single event loop.
_redis_client: redis.Redis | None = None
_redis_lock = asyncio.Lock()


async def get_redis() -> redis.Redis:
    """Return the shared Redis client, creating it on first call."""
    global _redis_client
    if _redis_client is None:
        async with _redis_lock:
            if _redis_client is None:  # double-check under lock
                _redis_client = redis.Redis.from_url(
                    settings.redis_url,
                    decode_responses=True,
                    max_connections=settings.redis_max_connections,
                )
    return _redis_client


def get_redis_sync() -> redis.Redis:
    """Sync version for Celery tasks and non-async contexts."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=settings.celery_worker_redis_max_connections,
        )
    return _redis_client


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
