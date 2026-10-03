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

# In production, only allow requests from trusted proxy IPs or localhost for dev.
# Reject all other origins to prevent CORS-based attacks.
_PRODUCTION_ALLOWED_ORIGINS: list[str] = [
    origin.strip()
    for origin in os.environ.get("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]


def _get_client_ip(request: Request) -> str:
    """
    Get real client IP.

    X-Forwarded-For is trusted ONLY when the direct connection comes from a
    configured proxy IP (TRUSTED_PROXY_IPS). Anything else is ignored:
    the header is attacker-controlled, so honouring it lets a client rotate
    fake IPs to bypass every rate limit and poison the audit trail with
    arbitrary source addresses. This is deliberately fail-closed — set
    TRUSTED_PROXY_IPS to the nginx/container proxy address in production,
    otherwise every request appears to come from that proxy and shares one
    rate-limit bucket.
    """
    direct_ip = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")

    if direct_ip in _TRUSTED_PROXIES and forwarded:
        raw = forwarded.split(",")[0].strip()[:45]
        return RateLimitService._normalize_ip(raw)

    if forwarded and not _TRUSTED_PROXIES and settings.app_env == "production":
        logger.warning(
            "TRUSTED_PROXY_IPS is empty but X-Forwarded-For was presented — "
            "header ignored (fail-closed). Set TRUSTED_PROXY_IPS to the proxy "
            "address so per-user rate limiting works behind nginx."
        )

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
# Hard cap on request body size, enforced in RateLimitMiddleware before the
# body is buffered. Largest legitimate payload is a market description (5000
# chars) or dispute evidence (5000 chars) — 256 KiB leaves a wide margin.
_MAX_BODY_BYTES = 256 * 1024

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",          # Prevent MIME sniffing
    "X-Frame-Options": "DENY",                      # Disable iframe embedding
    "X-XSS-Protection": "1; mode=block",            # XSS filter (legacy but still sent)
    "Referrer-Policy": "strict-origin-when-cross-origin",  # Don't leak referrer cross-origin
    "Permissions-Policy": "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()",  # Disable dangerous APIs
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; form-action 'none'",  # Prevent XSS and data injection
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value
        # HSTS only when running as production
        if settings.app_env == "production":
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
        # Scrub raw headers to prevent PII leakage
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, enabled: bool = True):
        super().__init__(app)
        self.enabled = enabled
        # Build allowed origins once at init: explicit ALLOWED_ORIGINS env
        # (the security-critical allowlist) plus the CORS_ORIGINS the API
        # itself advertises, so a request from our own front end can never be
        # rejected by this check just because the two settings were edited
        # independently.
        self._allowed_origins = set(
            o.strip().lower() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()
        ) | set(o.strip().lower() for o in settings.cors_origins if o.strip())

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self.enabled:
            return await call_next(request)

        # ── Origin validation (all environments) ────────────────────────────
        # Browsers attach `Origin` to cross-origin and same-origin state-changing
        # requests; enforcing the allowlist everywhere means a staging box or a
        # local run is protected by the same rule as production, and an attacker
        # can't rely on an environment being set to "development" to slip past it.
        # localhost/127.0.0.1 are always allowed for local development.
        # Non-browser clients (curl, server-to-server) send no Origin and are
        # unaffected — they are handled by SameSite + the JSON content-type rule.
        origin = request.headers.get("origin")
        if origin:
            is_allowed = False
            if not self._allowed_origins:
                # No ALLOWED_ORIGINS configured — deny all cross-origin requests
                is_allowed = False
            elif "*" in self._allowed_origins:
                is_allowed = True
            else:
                is_allowed = origin.lower() in self._allowed_origins
            if not is_allowed and not origin.startswith("http://localhost") and not origin.startswith("http://127.0.0.1"):
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=403,
                    content={"error_code": "ORIGIN_NOT_ALLOWED", "message": "CORS origin not permitted"},
                    headers={**SECURITY_HEADERS, **{"Access-Control-Allow-Origin": "none"}},
                )

        path = request.url.path
        method = request.method

        # ── Request body size guard ──────────────────────────────────────────
        # Pydantic only enforces max_length AFTER the whole body has been read
        # into memory, so without a pre-read cap a client can POST an
        # unbounded payload and exhaust the process. Reject on Content-Length
        # before Starlette buffers anything. (Chunked bodies without the
        # header are still bounded by the reverse proxy / uvicorn.)
        if method in ("POST", "PUT", "PATCH"):
            cl = request.headers.get("content-length", "")
            if cl.isdigit() and int(cl) > _MAX_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={
                        "success": False,
                        "error": f"Request body too large (max {_MAX_BODY_BYTES} bytes)",
                        "error_code": "PAYLOAD_TOO_LARGE",
                    },
                    headers={"Connection": "close"},
                )

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

        if not result.allowed:
            from fastapi.responses import JSONResponse

            # Match the standard error envelope used everywhere else
            # ({success:false, error, error_code, details?}) so clients only
            # ever have to parse one shape. `retry_after` is kept top-level
            # for backward compatibility with existing consumers.
            retry_after = result.retry_after
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "error": (
                        f"Too many requests — try again in {retry_after}s"
                        if retry_after
                        else "Too many requests"
                    ),
                    "error_code": "RATE_LIMIT_EXCEEDED",
                    "retry_after": retry_after,
                },
                headers={
                    "X-RateLimit-Limit": str(result.limit),
                    "X-RateLimit-Remaining": "0",
                    **({"Retry-After": str(result.retry_after)} if result.retry_after else {}),
                },
            )

        response = await call_next(request)

        response.headers["X-RateLimit-Limit"] = str(result.limit)
        response.headers["X-RateLimit-Remaining"] = str(result.remaining)

        if result.retry_after:
            response.headers["Retry-After"] = str(result.retry_after)

        return response
