import asyncio
import logging
import time

import redis.asyncio as redis
from redis.asyncio.sentinel import Sentinel

from app.config import settings

logger = logging.getLogger("polymarket")

# ─── Shared Redis client (one connection pool per worker process) ────────────
# Sentinel-backed: if REDIS_SENTINEL_URLS is set, clients connect via Sentinel
# for automatic failover. Falls back to direct URL otherwise.
_redis_client: redis.Redis | None = None
_redis_client_sync: redis.Redis | None = None
_redis_client_loop: asyncio.AbstractEventLoop | None = None


async def get_redis() -> redis.Redis:
    """Return the shared Redis client, recreating if the event loop has changed."""
    global _redis_client, _redis_client_loop
    current_loop = asyncio.get_running_loop()
    if _redis_client is None or _redis_client_loop is not current_loop:
        if _redis_client is not None:
            try:
                await _redis_client.aclose()
            except Exception:
                pass
        _redis_client = await _create_redis_client()
        _redis_client_loop = current_loop
    return _redis_client


async def _create_redis_client() -> redis.Redis:
    sentinel_urls = _parse_sentinel_urls()
    if sentinel_urls:
        logger.info(f"Connecting to Redis via Sentinel: service={settings.redis_sentinel_service_name}")
        sentinel = Sentinel(
            sentinel_urls,
            sentinel_kwargs={"socket_connect_timeout": 2},
            decode_responses=True,
        )
        # Master-for-read gives us the current primary; Sentinel manages failover
        client = sentinel.master_for(
            settings.redis_sentinel_service_name,
            redis_class=redis.Redis,
            connection_kwargs={"max_connections": settings.redis_max_connections},
        )
    else:
        logger.info(f"Connecting to Redis directly: {settings.redis_url}")
        client = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=settings.redis_max_connections,
            socket_connect_timeout=5,
        )
    return client


def _parse_sentinel_urls() -> list[str]:
    """Parse REDIS_SENTINEL_URLS env var (comma-separated) into a list of sentinel URLs."""
    raw = settings.redis_sentinel_urls
    if not raw:
        return []
    return [url.strip() for url in raw.split(",") if url.strip()]


def get_redis_sync() -> redis.Redis:
    """Sync Redis client for Celery tasks and non-async contexts. Sentinel-aware."""
    global _redis_client_sync
    if _redis_client_sync is None:
        sentinel_urls = _parse_sentinel_urls()
        if sentinel_urls:
            import redis as sync_redis
            sentinel = sync_redis.Sentinel(
                sentinel_urls,
                socket_connect_timeout=2,
            )
            _redis_client_sync = sentinel.master_for(
                settings.redis_sentinel_service_name,
                redis_class=sync_redis.Redis,
                connection_kwargs={
                    "max_connections": settings.celery_worker_redis_max_connections,
                    "socket_timeout": 5,
                },
            )
        else:
            _redis_client_sync = redis.Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                max_connections=settings.celery_worker_redis_max_connections,
            )
    return _redis_client_sync


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
        self._half_open_sem = asyncio.Semaphore(1)

    async def call(self, op):
        """Call an async op with circuit breaker protection. Lock is NOT held during I/O."""
        half_open_acquired = False
        async with self._lock:
            if self._state == "open":
                if time.time() - self._last_failure >= self.recovery_timeout:
                    self._state = "half_open"
                else:
                    raise redis.RedisError("Redis circuit breaker open")
            elif self._state == "half_open":
                await self._half_open_sem.acquire()
                half_open_acquired = True

        if half_open_acquired:
            # We already hold the semaphore — if we return/raise early the finally
            # releases it.  No need to track half_open_acquired separately for that case.
            pass

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
            # Re-raise AFTER state is persisted so a subsequent call in the
            # same event-loop iteration sees the breaker as open immediately.
            raise e
        finally:
            if half_open_acquired:
                self._half_open_sem.release()


redis_cb = RedisCircuitBreaker()
