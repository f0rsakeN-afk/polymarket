"""
Origin checking for state-changing requests.

## Why this is its own middleware

It used to live inside `RateLimitMiddleware`, which meant a **security control
gated behind a feature flag**: `if not self.enabled: return await call_next(...)`
sat above it, so turning off rate limiting silently turned off the CSRF defence
too. The test suite turns rate limiting off. A deployment could.

Three other things were wrong with it there:

- `ALLOWED_ORIGINS="*"` was honoured as "allow every origin", which is the same
  wildcard that `app.py` refuses in `CORS_ORIGINS` — a second, easier way to
  disable the check entirely.
- A hardcoded `http://localhost` / `http://127.0.0.1` bypass applied in **every**
  environment, including production.
- `ALLOWED_ORIGINS` was read straight from `os.environ` rather than settings, so
  it was not in `.env.example` and nobody knew it existed.

## Why the defence exists at all

`SameSite=Lax` was the CSRF defence, and it was the whole of it. `COOKIE_SAMESITE`
is now configurable, because the correct value is deployment topology — an API at
`api.example.com` serving an admin app at `admin.example.com` **cannot** use
`lax`, because the browser would never send the cookie. Setting `none` fixes the
authentication and removes this defence in the same breath.

So it is asserted here, where it does not depend on a cookie attribute a
deployment is obliged to change, and where no feature flag can switch it off.

## Why this cannot break a legitimate client

The allowlist is `ALLOWED_ORIGINS ∪ CORS_ORIGINS` — the same set the middleware
used before, from the same two settings. A browser only sends `Origin` on a
credentialed cross-origin request if that origin is in `CORS_ORIGINS`, because
`CORSMiddleware` would block the response otherwise. So every `Origin` a real
client can successfully use is already permitted here; this turns a case that
would have been rejected later into a clear 403 at the front door.

`Origin` absent is allowed through. That is not a hole: every current browser
sends `Origin` on non-GET requests, including cross-site form posts, and a missing
one means a non-browser client — the WebSocket `?token=` fallback, a
server-to-server call, curl. Blocking it would break those with no security gain
against the browsers this defends against.
"""

from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.api.middleware import SECURITY_HEADERS
from app.config import settings

# Methods that can change state. `GET`/`HEAD`/`OPTIONS` are excluded deliberately:
# there are no GET mutations in this API, so a cross-site GET has nothing to change
# and refusing it would break prefetch and link previews for no benefit.
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Development conveniences, not a production hole: a browser-based CSRF attack is
# served from the attacker's own origin, so an attacker cannot forge `Origin:
# http://localhost`. Scoped to non-production anyway, because in production there
# is no reason for a request to claim it is from localhost.
_LOCAL_ORIGIN_PREFIXES = ("http://localhost", "http://127.0.0.1")


def normalize_origin(origin: str) -> str:
    """Reduce an origin to the form the spec says identifies it.

    Two differences have to be erased or the comparison becomes a browser-dependent
    coin flip:

    - **Case and a trailing slash.** `HTTPS://Example.com/` and
      `https://example.com` are the same origin. The trailing slash is easy to
      type into `.env` by accident.
    - **The default port.** `https://example.com` and `https://example.com:443`
      are the same origin, and browsers disagree about which they send. A raw
      comparison therefore refuses a legitimate request from one browser and
      accepts it from another — a bug that presents as a user-agent problem and is
      not one.
    """
    value = origin.strip().rstrip("/").lower()
    if value.startswith("https://") and value.endswith(":443"):
        return value[: -len(":443")]
    if value.startswith("http://") and value.endswith(":80"):
        return value[: -len(":80")]
    return value


def allowed_origins() -> set[str]:
    """`ALLOWED_ORIGINS ∪ CORS_ORIGINS`, normalised.

    The union is deliberate: `ALLOWED_ORIGINS` is the wider security allowlist and
    `CORS_ORIGINS` is what the API advertises, so editing one cannot silently
    break a request from our own front end.

    `*` is **not** honoured. `app.py` already refuses it in `CORS_ORIGINS`
    because `allow_credentials=True` cannot use a wildcard, and honouring it here
    would be a second, easier way to switch the CSRF defence off entirely.
    """
    raw = f"{settings.allowed_origins},{settings.cors_origins}"
    return {
        normalize_origin(origin)
        for origin in raw.split(",")
        if origin.strip() and origin.strip() != "*"
    }


def is_allowed_origin(origin: str) -> bool:
    if normalize_origin(origin) in allowed_origins():
        return True
    # A wildcard is an explicit opt-out request; refusing it is louder than
    # honouring it, because "my requests are all 403" gets investigated and
    # "CSRF protection silently disabled" does not.
    if "*" in {
        value.strip()
        for value in f"{settings.allowed_origins},{settings.cors_origins}".split(",")
    }:
        return False
    return (
        settings.app_env != "production"
        and origin.startswith(_LOCAL_ORIGIN_PREFIXES)
    )


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """Reject a state-changing request whose `Origin` is not an allowed origin."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable]
    ) -> JSONResponse:
        if request.method.upper() not in UNSAFE_METHODS:
            return await call_next(request)

        origin = request.headers.get("origin")
        # No `Origin` header: a non-browser client. See the module docstring.
        if not origin or is_allowed_origin(origin):
            return await call_next(request)

        # `Access-Control-Allow-Origin: none` stops the browser handing the body of
        # a refused response to the attacking page's script.
        return JSONResponse(
            status_code=403,
            content={
                "error_code": "ORIGIN_NOT_ALLOWED",
                "message": "CORS origin not permitted",
            },
            headers={**SECURITY_HEADERS, **{"Access-Control-Allow-Origin": "none"}},
        )