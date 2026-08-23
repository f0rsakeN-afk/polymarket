import json
import logging
import os
import time
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config import settings
from app.services.rate_limit_service import LimitType, RateLimitService

logger = logging.getLogger("polymarket")

# Trusted proxy chain — only honour X-Forwarded-For when the request came from one of these.
# In Docker/K8s: set TRUSTED_PROXY_IPS="10.0.0.0/8,172.16.0.0/12" etc.
_TRUSTED_PROXIES: list[str] = [
    ip.strip()
    for ip in os.environ.get("TRUSTED_PROXY_IPS", "").split(",")
    if ip.strip()
]


def _get_client_ip(request: Request) -> str:
    """
    Get real client IP.  X-Forwarded-For is only trusted when the direct
    connection is from a known proxy IP — spoofing is otherwise trivially easy.
    """
    # If request came from a trusted proxy, use X-Forwarded-For; otherwise ignore it.
    direct_ip = request.client.host if request.client else None

    if direct_ip in _TRUSTED_PROXIES:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Cap at 45 chars to prevent logging/storage abuse
            raw = forwarded.split(",")[0].strip()[:45]
            return RateLimitService._normalize_ip(raw)

    # Fall back to direct connection IP (or "unknown" for Unix sockets)
    return RateLimitService._normalize_ip(direct_ip or "unknown")


def _get_auth_limit_type(path: str) -> LimitType:
    """Map auth path to its limit type."""
    # High-cost decisions: verify code, login, reset password
    if path in (
        "/api/v1/auth/login",
        "/api/v1/auth/verify-email",
        "/api/v1/auth/verify-magic",
        "/api/v1/auth/verify-magic-url-2fa",
        "/api/v1/auth/reset-password",
    ):
        return LimitType.AUTH_DECISION
    # Low-cost actions: resend, forgot, register
    return LimitType.AUTH_FAST


# Security headers applied to every response
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",          # Prevent MIME sniffing
    "X-Frame-Options": "DENY",                     # Disable iframe embedding
    "X-XSS-Protection": "1; mode=block",           # XSS filter (legacy but still sent)
    "Referrer-Policy": "strict-origin-when-cross-origin",  # Don't leak referrer cross-origin
    "Permissions-Policy": "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()",  # Disable dangerous APIs
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value
        # HSTS only on HTTPS (prod)
        if not settings.debug:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.perf_counter()
        method = request.method
        path = request.url.path
        client_ip = _get_client_ip(request)
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        log_data = {
            "request_id": getattr(request.state, "request_id", None),
            "trace_id": getattr(request.state, "request_id", None),
            "user_id": getattr(request.state, "user_id", None),
            "method": method,
            "path": path,
            "status_code": response.status_code,
            "latency_ms": round(duration_ms, 2),
            "client_ip": client_ip,
        }
        logger.info(json.dumps(log_data, default=str))
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

        # Skip rate limiting for health/read-only endpoints
        if method == "GET" or path in ("/health", "/health/ready", "/", "/docs", "/openapi.json", "/redoc"):
            return await call_next(request)

        ip = _get_client_ip(request)
        limit_type: LimitType

        if path.startswith("/api/v1/auth"):
            limit_type = _get_auth_limit_type(path)
        elif method not in ("GET", "HEAD", "OPTIONS"):
            limit_type = LimitType.STRICT
        else:
            limit_type = LimitType.GENERAL

        # Use user ID if authenticated, otherwise IP
        identifier = getattr(request.state, "user_id", None) or ip

        result = await RateLimitService.check(limit_type, identifier, ip)

        response = await call_next(request)

        response.headers["X-RateLimit-Limit"] = str(result.limit)
        response.headers["X-RateLimit-Remaining"] = str(result.remaining)

        if result.retry_after:
            response.headers["Retry-After"] = str(result.retry_after)

        if not result.allowed:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=429,
                content={"error_code": "RATE_LIMIT_EXCEEDED", "retry_after": result.retry_after},
                headers=dict(response.headers),
            )

        return response
