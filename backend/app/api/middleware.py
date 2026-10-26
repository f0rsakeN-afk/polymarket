import json
import logging
import os
import time
from collections.abc import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config import settings
from app.services.rate_limit_service import LimitType, RateLimitService

logger = logging.getLogger("PredictX")

# Trusted proxy chain • only honour X-Forwarded-For when the request came from one of these.
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
    arbitrary source addresses. This is deliberately fail-closed • set
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
            "TRUSTED_PROXY_IPS is empty but X-Forwarded-For was presented • "
            "header ignored (fail-closed). Set TRUSTED_PROXY_IPS to the proxy "
            "address so per-user rate limiting works behind nginx."
        )

    return RateLimitService._normalize_ip(direct_ip or "unknown")


def _get_auth_limit_type(path: str) -> LimitType:
    """Map auth path to its limit type."""
    # Silent token rotation is its own bucket, not AUTH_FAST. AUTH_FAST is 3/min
    # because every endpoint in it sends an email or reveals whether an account
    # exists • the tight cap is the point. `/auth/refresh` does neither: it is a
    # cookie-to-cookie rotation that a signed-in client performs silently, and
    # 3/min meant a burst of 401s (a flaky network, a laptop waking from sleep
    # with an expired access token, several components refetching at once) got
    # the client 429'd and locked out of recovering its own live session. It
    # still gets its own generous-but-bounded budget, keyed per IP.
    if path == "/api/v1/auth/refresh":
        return LimitType.AUTH_REFRESH
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
# chars) or dispute evidence (5000 chars) • 256 KiB leaves a wide margin.
_MAX_BODY_BYTES = 256 * 1024

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",          # Prevent MIME sniffing
    "X-Frame-Options": "DENY",                      # Disable iframe embedding
    "X-XSS-Protection": "1; mode=block",            # XSS filter (legacy but still sent)
    "Referrer-Policy": "strict-origin-when-cross-origin",  # Don't leak referrer cross-origin
    "Permissions-Policy": "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()",  # Disable dangerous APIs
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; form-action 'none'",  # Prevent XSS and data injection
}

# The CSP above is right for JSON API responses but breaks the interactive docs:
# they are HTML pages that pull Swagger UI's CSS/JS from jsdelivr and fetch
# /openapi.json at runtime. Under `default-src 'none'` the browser blocks all
# three, `SwaggerUIBundle` never gets defined, and /docs renders as a blank
# page (HTML still returns 200, so it looks like a server problem).
# These routes get a CSP naming exactly what Swagger UI needs and nothing more.
# Unreachable in production anyway • app.py sets docs_url/redoc_url to None there.
_DOCS_CSP = (
    "default-src 'none'; "
    "script-src 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'none'"
)

_DOCS_PATHS = ("/docs", "/redoc", "/docs/oauth2-redirect")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        headers = SECURITY_HEADERS
        if request.url.path.startswith(_DOCS_PATHS):
            headers = {**SECURITY_HEADERS, "Content-Security-Policy": _DOCS_CSP}
        for header, value in headers.items():
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
            # Removed: `"trace_id"`, which was a byte-for-byte copy of this line's
            # own `request_id`. No W3C trace context is parsed or propagated
            # anywhere in this service, so there is no second identifier — and a
            # field named `trace_id` that duplicates `request_id` is worse than
            # an absent one: someone searching logs for `trace_id` finds a value
            # and concludes tracing is wired.
            #
            # If real distributed tracing is added later it should arrive as
            # `traceparent`, honoured on the way in and emitted on the way out,
            # and be joined to `request_id` rather than renamed as one.
            "request_id": getattr(request.state, "request_id", None),
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

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # No origin check here any more. It used to sit above this guard, which
        # made a CSRF defence depend on a rate-limiting feature flag: with
        # `RATE_LIMIT_ENABLED=false` — what the test suite runs, and a thing a
        # deployment can set — cross-origin state changes were simply not checked.
        # It now lives in `app.api.origin_check.OriginCheckMiddleware`, which no
        # flag can switch off.
        if not self.enabled:
            return await call_next(request)

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
        #
        # OPTIONS is included for CORS preflight, and that exclusion is load-
        # bearing rather than cosmetic.
        #
        # A browser attaches a preflight to every cross-origin call that isn't a
        # simple request - which, for a JSON API, is all of them. The user never
        # issued it, cannot avoid it, and it says nothing about intent: it is
        # cacheable, idempotent, and generated by the browser before the real
        # request is even attempted.
        #
        # Counting them means a page making N calls spends 2N budget, and a
        # genuine burst of normal browsing can exhaust a client's allowance and
        # return 429 on the *preflight* - so the actual request the user wanted
        # never leaves the browser at all. The symptom is a page that silently
        # stops updating with no error on the client and no obvious cause on the
        # server: every failing request is an OPTIONS nobody meant to send.
        #
        # Preflights are also the cheapest requests the API serves, so spending
        # abuse budget on them protects nothing and costs correctness.
        # Prefixed, not an exact-match list. The health surface has grown a
        # `/health/live`, `/health/startup` and `/health/details`, and an exact
        # list meant every new probe path silently fell *into* rate limiting -
        # so an orchestrator polling liveness would eventually get 429 and restart
        # a perfectly healthy container. The failure is invisible until it happens
        # and looks exactly like an application problem.
        #
        # `/health*` is exempt as a prefix: probes are infrastructure talking to
        # the process, not a user, and are exactly the traffic that must never be
        # throttled - least of all during the incident the limiter is reacting to.
        if method in ("GET", "OPTIONS") or path.startswith("/health") or path in (
            "/", "/docs", "/openapi.json", "/redoc"
        ):
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
                        f"Too many requests • try again in {retry_after}s"
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
