import time
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("polymarket")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        method = request.method
        path = request.url.path

        response = await call_next(request)

        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            f"{method} {path} | status={response.status_code} duration={duration_ms:.1f}ms"
        )
        return response
