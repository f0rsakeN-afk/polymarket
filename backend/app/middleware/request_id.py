import logging
import uuid
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("polymarket")


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Use inbound ID if present, otherwise generate a new one
        inbound_id = request.headers.get("X-Request-ID") or request.headers.get("X-Trace-ID")
        request_id = inbound_id if inbound_id else str(uuid.uuid4())
        request.state.request_id = request_id

        logger.debug(f"request_id={request_id} method={request.method} path={request.url.path} started")

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
