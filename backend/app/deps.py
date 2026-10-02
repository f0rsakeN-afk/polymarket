import logging
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import Depends, Request, Response
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import ForbiddenError, UnauthorizedError
from app.config import settings
from app.database import get_db
from app.models.user import Session, User
from app.redis import get_redis, redis_cb

logger = logging.getLogger("polymarket")

ALGORITHM = "HS256"

# ── Response cache helpers ────────────────────────────────────────────────────


async def cache_get(key: str) -> dict | list | None:
    r = await get_redis()
    data = await redis_cb.call(lambda: r.get(f"cache:{key}"))
    if data:
        import json
        return json.loads(data)
    return None


async def cache_set(key: str, data: dict | list, ttl: int = 30):
    r = await get_redis()
    import json
    def json_dumps(obj):
        return json.dumps(obj, default=str)
    await redis_cb.call(lambda: r.set(f"cache:{key}", json_dumps(data), ex=ttl))


async def cache_invalidate(key: str):
    r = await get_redis()
    await redis_cb.call(lambda: r.delete(f"cache:{key}"))


async def cache_invalidate_pattern(pattern: str):
    """Delete all keys matching pattern (uses SCAN to avoid blocking)."""
    r = await get_redis()
    cursor = 0
    while True:
        cursor, keys = await redis_cb.call(lambda: r.scan(cursor, match=f"cache:{pattern}", count=100))
        if keys:
            await redis_cb.call(lambda: r.delete(*keys))
        if cursor == 0:
            break


def _bcrypt_input(password: str) -> bytes:
    """Normalise a password to ≤72 bytes for bcrypt.

    bcrypt only reads the first 72 bytes of input: longer input used to raise
    (`ValueError: password cannot be longer than 72 bytes`) — which made
    registration with a long password a 500, and made *first-ever settlement*
    crash, because the system treasury account derives its password hash from
    `jwt_secret + 32 random bytes` (well over 72 bytes). Pre-hashing keeps the
    full entropy of long secrets while staying inside the limit; silently
    truncating instead would make every long password sharing its first 72
    bytes collide. Passwords ≤72 bytes are untouched, so every existing hash
    still verifies.
    """
    raw = password.encode()
    if len(raw) <= 72:
        return raw
    import hashlib

    return hashlib.sha256(raw).hexdigest().encode()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_bcrypt_input(password), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    if not hashed:
        return False
    return bcrypt.checkpw(_bcrypt_input(plain), hashed.encode())


_DUMMY_PASSWORD_HASH: str | None = None


def dummy_password_hash() -> str:
    """Cached bcrypt hash of a throwaway secret, generated on first use.

    Used when an email is not registered so that an unknown-user login costs
    the same ~100 ms of bcrypt work as a known-user login. Without it, a
    fast response means "no such account" — a reliable user-enumeration
    oracle. Generated lazily (never at import) and cached: the value is
    meaningless, it only exists to be slow.
    """
    global _DUMMY_PASSWORD_HASH
    if _DUMMY_PASSWORD_HASH is None:
        import secrets as _secrets

        _DUMMY_PASSWORD_HASH = hash_password(_secrets.token_urlsafe(32))
    return _DUMMY_PASSWORD_HASH


def create_access_token(
    user_id: str,
    expires_delta: timedelta | None = None,
    session_id: str | None = None,
) -> tuple[str, str]:
    """
    Create a JWT access token with a unique jti.
    `session_id` binds the token to its DB session row so callers can tell
    which of the user's sessions issued a request (optional for old tokens).
    Returns (token, jti).
    """
    jti = str(uuid.uuid4())
    expire = datetime.now(UTC) + (expires_delta or timedelta(seconds=settings.jwt_access_expire))
    to_encode = {"sub": user_id, "exp": expire, "type": "access", "jti": jti}
    if session_id:
        to_encode["sid"] = session_id
    token = jwt.encode(to_encode, settings.jwt_secret, algorithm=ALGORITHM)
    return token, jti


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        raise UnauthorizedError(f"Invalid token: {e}")


# ── Blacklist settings (read once at import so it can be overridden) ──────────────
_BLACKLIST_FAIL_OPEN = settings.app_env == "development"


async def is_token_blacklisted(jti: str) -> bool:
    try:
        r = await get_redis()
        result = await redis_cb.call(lambda: r.get(f"blacklist:{jti}"))
        return result is not None
    except Exception:
        if _BLACKLIST_FAIL_OPEN:
            # Fail-open: allow the token during Redis outage.
            # Token still rejected at natural expiry (JWT `exp`, max 15 min).
            logger.warning(f"Redis unavailable for blacklist check — failing open (jti={jti})")
            return False
        # Fail-closed: deny the token when Redis is unavailable.
        # Safer for production where a Redis outage should not admit revoked tokens.
        logger.error(f"Redis unavailable for blacklist check — failing closed (jti={jti})")
        return True


async def blacklist_token(jti: str, ttl_seconds: int):
    """Add a token's jti to the blacklist for its remaining TTL."""
    try:
        r = await get_redis()
        await redis_cb.call(lambda: r.set(f"blacklist:{jti}", "1", ex=ttl_seconds))
    except Exception:
        if _BLACKLIST_FAIL_OPEN:
            logger.warning(f"Redis unavailable to blacklist token (jti={jti}) — allowing logout")
            return
        # Fail-closed: re-raise so the caller knows the blacklist write failed.
        # Logout is aborted but the token is not blacklisted — it expires naturally in 15 min.
        logger.error(f"Redis unavailable to blacklist token (jti={jti}) — failing closed")
        raise


async def _validate_session(db: AsyncSession, payload: dict, user: User) -> None:
    """Reject the token unless its session is alive.

    An access token is only valid for the session it was minted for: the `sid`
    claim names that row. This is what makes revocation exact — `logout` and
    `DELETE /auth/sessions/{id}` kill that device's tokens immediately, and
    `logout-all` kills every device's, instead of the token surviving as long
    as some other session of the same user is still alive. Expiry is checked
    against the session too, not just against the 15-minute JWT.
    """
    sid = payload.get("sid")
    if not sid:
        raise UnauthorizedError("Token is not bound to a session")

    session = await db.get(Session, sid)
    if session is None or session.user_id != user.id:
        raise UnauthorizedError("Session not found")
    if session.revoked:
        raise UnauthorizedError("Session has been revoked")
    if session.expires_at <= datetime.now(UTC):
        raise UnauthorizedError("Session expired")


async def _load_user(db: AsyncSession, payload: dict) -> User:
    """Shared token → user resolution for both required and optional auth.

    Raises UnauthorizedError / ForbiddenError; callers decide whether to
    propagate (required auth) or treat as anonymous (optional auth).
    """
    sub = payload.get("sub")
    if not sub:
        raise UnauthorizedError("Invalid token")
    if payload.get("type") != "access":
        raise UnauthorizedError("Invalid token type")

    jti = payload.get("jti")
    if jti and await is_token_blacklisted(jti):
        raise UnauthorizedError("Token has been revoked")

    user = await db.get(User, sub)
    if not user:
        raise UnauthorizedError("User not found")
    if not user.is_active:
        raise ForbiddenError("Account is inactive")

    await _validate_session(db, payload, user)
    return user


async def authenticate_token(db: AsyncSession, token: str) -> User:
    """Decode + fully validate a raw token string.

    Identical to the HTTP auth path: JWT decode, token type, jti blacklist,
    user active, session binding. Websocket routes call this so that a
    revoked/blacklisted/logged-out token is rejected on the upgrade handshake
    too, instead of only at issue time.
    """
    return await _load_user(db, decode_token(token))


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    token = request.cookies.get("access_token")
    auth_header = request.headers.get("Authorization", "")
    if not token and auth_header.startswith("Bearer "):
        token = auth_header[7:]

    if not token:
        raise UnauthorizedError("No access token provided")

    return await _load_user(db, decode_token(token))


async def get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    token = request.cookies.get("access_token")
    auth_header = request.headers.get("Authorization", "")
    if not token and auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if not token:
        return None

    try:
        return await _load_user(db, decode_token(token))
    except (UnauthorizedError, ForbiddenError):
        # Optional auth: a bad/expired/revoked token is anonymous, not an error.
        return None


def set_auth_cookies(response: Response, access_token: str, refresh_token: str | None = None):
    """
    Set HttpOnly, Secure (prod-only), SameSite=Lax cookies for auth tokens.
    - secure: True when DEBUG=false (HTTPS required in prod)
    - httponly: True (never accessible to JavaScript)
    - samesite=lax: sent on same-origin requests and safe top-level navigations
    """
    # Secure cookie only when actually in production (HTTPS). Localhost and dev
    # environments must use non-secure cookies even when DEBUG=false.
    is_prod = settings.app_env == "production"
    # Domain=localhost allows the cookie to work across frontend (:3000) and
    # backend (:8000) on different ports during local development.
    cookie_domain = "localhost" if not is_prod else None

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=is_prod,
        samesite="lax",
        max_age=settings.jwt_access_expire,
        path="/",
        domain=cookie_domain,
    )
    if refresh_token:
        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,
            secure=is_prod,
            samesite="lax",
            max_age=settings.jwt_refresh_expire,
            path="/",
            domain=cookie_domain,
        )


def clear_auth_cookies(response: Response):
    is_prod = settings.app_env == "production"
    cookie_domain = "localhost" if not is_prod else None
    response.delete_cookie("access_token", path="/", secure=is_prod, domain=cookie_domain)
    response.delete_cookie("refresh_token", path="/", secure=is_prod, domain=cookie_domain)
