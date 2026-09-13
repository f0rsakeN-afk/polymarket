import logging
import re
import uuid
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("polymarket")

# Inbound IDs are echoed into responses and logs: accept only a safe charset
# and length so callers can't inject log lines or oversized values.
_SAFE_ID = re.compile(r"^[A-Za-z0-9\-_]{1,64}$")


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Use inbound ID if present and safe, otherwise generate a new one
        inbound_id = request.headers.get("X-Request-ID") or request.headers.get("X-Trace-ID")
        if inbound_id and not _SAFE_ID.match(inbound_id):
            inbound_id = None
        request_id = inbound_id or str(uuid.uuid4())
        request.state.request_id = request_id

        logger.debug(f"request_id={request_id} method={request.method} path={request.url.path} started")

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
