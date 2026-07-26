import logging
import time
from collections.abc import Callable

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.redis import get_redis, redis_cb

logger = logging.getLogger("polymarket")

RATE_LIMIT_DEFAULTS: dict[str, tuple[int, int]] = {
    "global": (60, 60),       # 60 requests per 60s
    "auth": (10, 60),         # 10 requests per 60s (login/register)
    "orders": (30, 60),       # 30 orders per 60s
    "markets_write": (10, 60), # 10 market mutations per 60s
}

def _bucket_key(identifier: str, bucket: str) -> str:
    return f"ratelimit:{bucket}:{identifier}"

async def _check_rate_limit(
    identifier: str,
    bucket: str,
    limit: int,
    window: int,
) -> tuple[bool, int, int]:
    key = _bucket_key(identifier, bucket)
    now = int(time.time())
    window_start = now - (now % window)

    try:
        r = get_redis()
        current_key = f"{key}:{window_start}"

        async def _incr():
            pipe = r.pipeline()
            pipe.incr(current_key)
            pipe.expire(current_key, window * 2)
            return await pipe.execute()

        count, _ = await redis_cb.call(_incr)
        remaining = max(0, limit - count)
        return count <= limit, remaining, limit
    except Exception:
        return True, limit, limit


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        method = request.method
        path = request.url.path
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(f"{method} {path} | status={response.status_code} duration={duration_ms:.1f}ms")
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, enabled: bool = True):
        super().__init__(app)
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self.enabled:
            return await call_next(request)

        path = request.url.path
        method = request.method

        identifier = request.client.host if request.client else "unknown"
        user_id = getattr(request.state, "user_id", None)
        if user_id:
            identifier = str(user_id)

        bucket = "global"
        if path.startswith("/api/v1/auth"):
            bucket = "auth"
        elif path.startswith("/api/v1/orders") and method != "GET":
            bucket = "orders"
        elif path.startswith("/api/v1/markets/") and method in ("POST", "PATCH", "DELETE", "PUT"):
            bucket = "markets_write"

        limit, window = RATE_LIMIT_DEFAULTS.get(bucket, RATE_LIMIT_DEFAULTS["global"])
        allowed, remaining, _ = await _check_rate_limit(identifier, bucket, limit, window)

        if not allowed:
            raise HTTPException(
                status_code=429,
                detail={
                    "message": f"Rate limit exceeded. {bucket} bucket: {limit} per {window}s.",
                    "error_code": "RATE_LIMIT_EXCEEDED",
                    "retry_after": window,
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
