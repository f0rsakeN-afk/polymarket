import logging
import time
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config import settings
from app.services.rate_limit_service import LimitType, RateLimitService

logger = logging.getLogger("polymarket")


def _get_client_ip(request: Request) -> str:
    """
    Get real client IP, accounting for proxies.
    X-Forwarded-For format: <client>, <proxy1>, <proxy2>
    Leftmost is the original client (unless trust proxy is configured).
    Falls back to request.client.host.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Leftmost IP is the original client
        client_ip = forwarded.split(",")[0].strip()
        return RateLimitService._normalize_ip(client_ip)
    if request.client:
        return RateLimitService._normalize_ip(request.client.host)
    return "unknown"


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
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            f"{method} {path} | status={response.status_code} duration={duration_ms:.1f}ms"
        )
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
        if method == "GET" or path in ("/health", "/", "/docs", "/openapi.json", "/redoc"):
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
            response.status_code = 429
            response.body = b""
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=429,
                content={"error_code": "RATE_LIMIT_EXCEEDED", "retry_after": result.retry_after},
                headers=dict(response.headers),
            )

        return response
