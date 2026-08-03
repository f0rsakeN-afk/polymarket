import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import Depends, HTTPException, Request, Response
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import ForbiddenError, UnauthorizedError
from app.config import settings
from app.database import get_db
from app.models.user import User
from app.redis import get_redis, redis_cb

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: str, expires_delta: timedelta | None = None) -> tuple[str, str]:
    """
    Create a JWT access token with a unique jti.
    Returns (token, jti).
    """
    jti = str(uuid.uuid4())
    expire = datetime.now(UTC) + (expires_delta or timedelta(seconds=settings.jwt_access_expire))
    to_encode = {"sub": user_id, "exp": expire, "type": "access", "jti": jti}
    token = jwt.encode(to_encode, settings.jwt_secret, algorithm=ALGORITHM)
    return token, jti


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        raise UnauthorizedError(f"Invalid token: {e}")


async def is_token_blacklisted(jti: str) -> bool:
    r = get_redis()
    result = await redis_cb.call(lambda: r.get(f"blacklist:{jti}"))
    return result is not None


async def blacklist_token(jti: str, ttl_seconds: int):
    """Add a token's jti to the blacklist for its remaining TTL."""
    r = get_redis()
    await redis_cb.call(lambda: r.setex(f"blacklist:{jti}", ttl_seconds, "1"))


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

    payload = decode_token(token)
    if payload.get("type") != "access":
        raise UnauthorizedError("Invalid token type")

    jti = payload.get("jti")
    if jti and await is_token_blacklisted(jti):
        raise UnauthorizedError("Token has been revoked")

    user = await db.get(User, payload["sub"])
    if not user:
        raise UnauthorizedError("User not found")
    if not user.is_active:
        raise ForbiddenError("Account is inactive")
    return user


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
        payload = decode_token(token)
        if payload.get("type") != "access":
            return None
        jti = payload.get("jti")
        if jti and await is_token_blacklisted(jti):
            return None
        user = await db.get(User, payload["sub"])
        if user and user.is_active:
            return user
    except HTTPException:
        pass
    return None


def set_auth_cookies(response: Response, access_token: str, refresh_token: str | None = None):
    """
    Set HttpOnly, Secure (prod-only), SameSite=Lax cookies for auth tokens.
    - secure: True when DEBUG=false (HTTPS required in prod)
    - httponly: True (never accessible to JavaScript)
    - samesite=lax: sent on same-origin requests and safe top-level navigations
    """
    is_prod = not settings.debug

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=is_prod,
        samesite="lax",
        max_age=settings.jwt_access_expire,
        path="/",
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
        )


def clear_auth_cookies(response: Response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
