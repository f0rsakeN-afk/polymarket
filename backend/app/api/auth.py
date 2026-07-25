import uuid
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Response, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.deps import hash_password, verify_password, create_access_token, get_current_user, set_auth_cookies, clear_auth_cookies
from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.auth import RegisterRequest, LoginRequest, UserResponse
from app.api.responses import success_response
from app.api.exceptions import ConflictError, UnauthorizedError, ValidationError
from app.config import settings

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", summary="Register a new user", description="Create a new account. Password must be at least 8 characters, username at least 3 characters.")
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Validate
    if len(data.password) < 8:
        raise ValidationError("Password must be at least 8 characters")
    if len(data.username) < 3:
        raise ValidationError("Username must be at least 3 characters")

    # Check duplicate
    result = await db.execute(
        select(User).where((User.email == data.email) | (User.username == data.username))
    )
    if result.scalar_one_or_none():
        raise ConflictError("User with this email or username already exists")

    # Resolve referral if provided
    referrer = None
    if data.referral_code:
        ref_result = await db.execute(
            select(User).where(User.referral_code == data.referral_code)
        )
        referrer = ref_result.scalar_one_or_none()

    # Create user
    user = User(
        email=data.email,
        username=data.username,
        password_hash=hash_password(data.password),
    )
    db.add(user)
    await db.flush()

    # Create wallet
    wallet = Wallet(user_id=user.id, balance=0, locked_balance=0, currency="USDC")
    db.add(wallet)

    # Create referral record if code was valid
    if referrer:
        from app.models.referral import Referral
        ref = Referral(
            id=uuid.uuid4(),
            referrer_id=referrer.id,
            referred_id=user.id,
            referral_code=data.referral_code,
            status="pending",
        )
        db.add(ref)

    await db.commit()

    logger.info(f"User registered: {data.email} ({user.id}), referred_by={referrer.id if referrer else None}")
    return success_response({"id": str(user.id), "email": user.email, "username": user.username})


@router.post("/login", summary="Login", description="Authenticate with email and password. Sets HTTP-only JWT cookies (access token + refresh token).")
async def login(data: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.password_hash):
        raise UnauthorizedError("Invalid email or password")

    if not user.is_active:
        raise UnauthorizedError("Account is inactive")

    access_token = create_access_token(str(user.id))
    refresh_token = str(uuid.uuid4())

    # Store refresh token
    from app.models.user import RefreshToken
    token_record = RefreshToken(
        id=refresh_token,
        user_id=user.id,
        token_hash=refresh_token,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.jwt_refresh_expire),
    )
    db.add(token_record)
    await db.commit()

    set_auth_cookies(response, access_token, refresh_token)
    logger.info(f"User logged in: {data.email}")
    return success_response({"id": str(user.id), "email": user.email, "username": user.username})


@router.post("/logout", summary="Logout", description="Logout and revoke refresh token. Clears auth cookies.")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        from app.models.user import RefreshToken
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == refresh_token)
        )
        token_record = result.scalar_one_or_none()
        if token_record:
            token_record.revoked = True
            await db.commit()
            logger.info(f"User logged out, token revoked")

    clear_auth_cookies(response)
    return success_response({"status": "logged_out"})


@router.post("/refresh", summary="Refresh access token", description="Rotate both access and refresh tokens. Old refresh token is revoked.")
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise UnauthorizedError("No refresh token")

    from app.models.user import RefreshToken
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == refresh_token,
            RefreshToken.revoked == False,
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
    )
    token_record = result.scalar_one_or_none()
    if not token_record:
        raise UnauthorizedError("Invalid or expired refresh token")

    user_id = str(token_record.user_id)

    # Revoke old refresh token
    token_record.revoked = True

    # Issue new refresh token
    new_refresh = str(uuid.uuid4())
    new_record = RefreshToken(
        id=new_refresh,
        user_id=token_record.user_id,
        token_hash=new_refresh,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.jwt_refresh_expire),
    )
    db.add(new_record)

    access_token = create_access_token(user_id)
    set_auth_cookies(response, access_token, new_refresh)
    await db.commit()
    return success_response({"status": "refreshed"})


@router.get("/me", summary="Get current user", description="Get the currently authenticated user's profile.")
async def me(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    return success_response({
        "id": str(user.id),
        "email": user.email,
        "username": user.username,
        "is_verified": user.is_verified,
        "referral_code": user.referral_code,
    })
