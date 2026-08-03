import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import ConflictError, UnauthorizedError, ValidationError
from app.api.responses import success_response
from app.config import settings
from app.database import get_db
from app.deps import (
    blacklist_token,
    clear_auth_cookies,
    create_access_token,
    decode_token,
    get_current_user,
    hash_password,
    set_auth_cookies,
    verify_password,
)
from app.redis import get_redis, redis_cb
from app.models.user import RefreshToken, User
from app.models.wallet import Wallet
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MagicLinkRequest,
    MagicUrl2FARequest,
    RegisterRequest,
    ResetPasswordRequest,
    ResendVerificationRequest,
    SetPasswordRequest,
    TwoFactorDisableRequest,
    TwoFactorEnableRequest,
    TwoFactorSetupResponse,
    VerifyEmailRequest,
    VerifyMagicRequest,
)
from app.services.email_service import EmailService
from app.services.otp_service import OTPService
from app.services.totp_service import TOTPService

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/auth", tags=["auth"])

# OTP key prefixes — match the values in OTPService
_OTP_VERIFY = "verify"
_OTP_MAGIC = "magic"
_OTP_RESET = "resetpwd"


def _issue_tokens(response: Response, user_id: str):
    """Create access + refresh token records, set cookies. Caller commits."""
    access_token, jti = create_access_token(str(user_id))
    refresh_token = str(uuid.uuid4())
    token_record = RefreshToken(
        id=refresh_token,
        user_id=user_id,
        token_hash=refresh_token,
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.jwt_refresh_expire),
    )
    return access_token, jti, refresh_token, token_record


def _revoke_all_refresh_tokens(db: AsyncSession, user_id: str, keep_token_hash: str | None = None):
    """
    Revoke all non-revoked refresh tokens for a user.
    Optionally keep one token (used by change-password to preserve current session).
    """
    query = select(RefreshToken).where(
        RefreshToken.user_id == user_id,
        RefreshToken.revoked.is_(False),
    )
    result = db.execute(query)
    for token in result.scalars().all():
        if keep_token_hash and token.token_hash == keep_token_hash:
            continue
        token.revoked = True


def _blacklist_access_token(request: Request):
    """Blacklist the access token from the request cookie if present."""
    access_token = request.cookies.get("access_token")
    if not access_token:
        return
    try:
        payload = decode_token(access_token)
        jti = payload.get("jti")
        if jti:
            ttl = int(payload["exp"] - datetime.now(UTC).timestamp())
            if ttl > 0:
                blacklist_token(jti, ttl)
    except Exception:
        pass


# ─── Registration ──────────────────────────────────────────────────────────────


@router.post("/register", summary="Register")
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    if len(data.username) < 3:
        raise ValidationError("Username must be at least 3 characters")

    # Duplicate check
    result = await db.execute(
        select(User).where((User.email == data.email) | (User.username == data.username))
    )
    if result.scalar_one_or_none():
        raise ConflictError("User with this email or username already exists")

    user = User(email=data.email, username=data.username, password_hash="", is_email_verified=False)
    db.add(user)
    await db.flush()

    wallet = Wallet(user_id=user.id, balance=0, locked_balance=0, currency="USDC")
    db.add(wallet)

    if data.referral_code:
        from app.models.referral import Referral

        ref_result = await db.execute(select(User).where(User.referral_code == data.referral_code))
        referrer = ref_result.scalar_one_or_none()
        if referrer:
            ref = Referral(
                id=uuid.uuid4(), referrer_id=referrer.id, referred_id=user.id,
                referral_code=data.referral_code, status="pending",
            )
            db.add(ref)

    await db.commit()

    # Issue OTP and enqueue email via Celery (fire-and-forget)
    code = await OTPService.send_code(data.email, _OTP_VERIFY)
    EmailService.send_verification_code(data.email, code)

    logger.info(f"User registered (unverified): {data.email} ({user.id})")
    return success_response({"id": str(user.id), "email": user.email, "username": user.username})


@router.post("/verify-email", summary="Verify email")
async def verify_email(data: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    # Check already-verified first to avoid unnecessary OTP verification
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user:
        raise UnauthorizedError("User not found")
    if user.is_email_verified:
        return success_response({"id": str(user.id), "email": user.email, "verified": True})

    if not await OTPService.verify_code(data.email, _OTP_VERIFY, data.code):
        raise UnauthorizedError("Invalid or expired code")

    user.is_email_verified = True
    await db.commit()

    logger.info(f"Email verified: {data.email}")
    return success_response({"id": str(user.id), "email": user.email, "verified": True})


@router.post("/resend-verification", summary="Resend verification code")
async def resend_verification(data: ResendVerificationRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user:
        return success_response({"message": "If that email exists, a code was sent"})

    if user.is_email_verified:
        return success_response({"message": "Email already verified"})

    # Invalidate previous code then issue new one
    await OTPService.invalidate(data.email, _OTP_VERIFY)
    code = await OTPService.send_code(data.email, _OTP_VERIFY)
    EmailService.send_verification_code(data.email, code)

    return success_response({"message": "Verification code sent"})


@router.post("/set-password", summary="Set password (requires email verification)")
async def set_password(data: SetPasswordRequest, request: Request, db: AsyncSession = Depends(get_db)):
    if len(data.password) < 8:
        raise ValidationError("Password must be at least 8 characters")

    user = await get_current_user(request, db)
    user.password_hash = hash_password(data.password)
    await db.commit()
    logger.info(f"Password set for user {user.id}")
    return success_response({"status": "password_set"})


# ─── Magic link ───────────────────────────────────────────────────────────────


@router.post("/magic-link", summary="Request magic link code via email")
async def magic_link(data: MagicLinkRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user:
        return success_response({"message": "If that email is registered, a code was sent"})

    if not user.is_email_verified:
        raise UnauthorizedError("Email not verified. Please register first.")

    code = await OTPService.send_code(data.email, _OTP_MAGIC)
    EmailService.send_magic_code(data.email, code)
    logger.info(f"Magic link code requested: {data.email}")
    return success_response({"message": "Login code sent"})


@router.post("/magic-link/url", summary="Request one-click magic link URL via email")
async def magic_link_url(data: MagicLinkRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user:
        return success_response({"message": "If that email is registered, a link was sent"})

    if not user.is_email_verified:
        raise UnauthorizedError("Email not verified. Please register first.")

    token = str(uuid.uuid4())
    r = get_redis()
    await redis_cb.call(lambda: r.setex(f"magicurl:{token}", 900, str(user.id)))

    magic_url = f"{settings.frontend_url}/auth/magic-url?token={token}"
    EmailService.send_magic_url(data.email, magic_url)
    logger.info(f"Magic URL requested: {data.email}")
    return success_response({"message": "Login link sent"})


@router.get("/verify-magic-url", summary="Verify magic link URL token (GET — for browser redirect)")
async def verify_magic_url(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    token = request.query_params.get("token")
    if not token:
        raise UnauthorizedError("Missing token")

    r = get_redis()
    user_id = await redis_cb.call(lambda: r.get(f"magicurl:{token}"))
    if not user_id:
        raise UnauthorizedError("Invalid or expired link")

    await redis_cb.call(lambda: r.delete(f"magicurl:{token}"))

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise UnauthorizedError("Account not found or inactive")

    if user.is_2fa_enabled:
        # Issue partial token, require 2FA completion
        partial = str(uuid.uuid4())
        await redis_cb.call(lambda: r.setex(f"partial:{partial}", 300, user_id))
        return success_response({"requires_2fa": True, "partial_token": partial})

    access_token, jti, refresh_token, token_record = _issue_tokens(response, str(user.id))
    db.add(token_record)
    await db.commit()
    set_auth_cookies(response, access_token, refresh_token)

    logger.info(f"Magic URL login: {user.email}")
    return success_response({"id": str(user.id), "email": user.email, "username": user.username})


@router.post("/verify-magic-url-2fa", summary="Complete magic URL login with 2FA")
async def verify_magic_url_2fa(
    data: MagicUrl2FARequest, response: Response, db: AsyncSession = Depends(get_db),
):
    """Complete magic URL login when 2FA is enabled."""
    r = get_redis()
    user_id = await redis_cb.call(lambda: r.get(f"partial:{data.partial_token}"))
    if not user_id:
        raise UnauthorizedError("Session expired or invalid")

    await redis_cb.call(lambda: r.delete(f"partial:{data.partial_token}"))

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise UnauthorizedError("Account not found or inactive")

    if not (user.is_2fa_enabled and user.totp_secret_encrypted):
        raise UnauthorizedError("2FA not enabled for this account")

    secret = TOTPService.decrypt_secret(user.totp_secret_encrypted)
    if not TOTPService.verify_code(secret, data.totp_code):
        raise UnauthorizedError("Invalid 2FA code")

    access_token, jti, refresh_token, token_record = _issue_tokens(response, str(user.id))
    db.add(token_record)
    await db.commit()
    set_auth_cookies(response, access_token, refresh_token)

    logger.info(f"Magic URL + 2FA login: {user.email}")
    return success_response({"id": str(user.id), "email": user.email, "username": user.username})


@router.post("/verify-magic", summary="Verify magic link code")
async def verify_magic(data: VerifyMagicRequest, response: Response, db: AsyncSession = Depends(get_db)):
    if not await OTPService.verify_code(data.email, _OTP_MAGIC, data.code):
        raise UnauthorizedError("Invalid or expired code")

    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise UnauthorizedError("Account not found or inactive")

    if user.is_2fa_enabled:
        if not data.totp_code:
            raise UnauthorizedError("2FA code required")
        secret = TOTPService.decrypt_secret(user.totp_secret_encrypted)
        if not TOTPService.verify_code(secret, data.totp_code):
            raise UnauthorizedError("Invalid 2FA code")

    access_token, jti, refresh_token, token_record = _issue_tokens(response, str(user.id))
    db.add(token_record)
    await db.commit()
    set_auth_cookies(response, access_token, refresh_token)

    logger.info(f"Magic login: {data.email}")
    return success_response({"id": str(user.id), "email": user.email, "username": user.username})


# ─── 2FA (TOTP) ───────────────────────────────────────────────────────────────


@router.get("/2fa/setup", summary="Start 2FA setup — generate secret + QR URI")
async def setup_2fa(request: Request, db: AsyncSession = Depends(get_db)):
    """Generate TOTP secret and provisioning URI. 2FA is pending until confirmed with /2fa/enable."""
    user = await get_current_user(request, db)

    if user.is_2fa_enabled:
        return success_response({"already_enabled": True})

    # Clear any stale pending state from a previous incomplete setup
    if user.is_2fa_pending:
        user.is_2fa_pending = False

    secret = TOTPService.generate_secret()
    uri = TOTPService.get_totp_uri(secret, user.email)
    encrypted = TOTPService.encrypt_secret(secret)

    user.totp_secret_encrypted = encrypted
    user.is_2fa_pending = True
    await db.commit()

    # Redis TTL — if user never confirms, pending state is effectively expired after this window
    r = get_redis()
    await redis_cb.call(
        lambda: r.setex(f"2fa_pending:{user.id}", settings.totp_setup_expire_seconds, "1")
    )

    logger.info(f"2FA setup initiated: {user.email}")
    return success_response(TwoFactorSetupResponse(
        secret=secret,
        uri=uri,
        base32=secret,
    ).model_dump())


@router.post("/2fa/enable", summary="Confirm and enable 2FA")
async def enable_2fa(
    data: TwoFactorEnableRequest, request: Request, db: AsyncSession = Depends(get_db),
):
    """Verify TOTP code to activate 2FA. Setup must be fresh (< TOTP_SETUP_EXPIRE_SECONDS old)."""
    user = await get_current_user(request, db)

    if not (user.totp_secret_encrypted and user.is_2fa_pending):
        raise ValidationError("No active 2FA setup. Call /2fa/setup first.")

    # Redis TTL check — stale if key expired
    r = get_redis()
    pending = await redis_cb.call(lambda: r.get(f"2fa_pending:{user.id}"))
    if not pending:
        user.is_2fa_pending = False
        user.totp_secret_encrypted = None
        await db.commit()
        raise ValidationError("2FA setup expired. Call /2fa/setup again.")

    secret = TOTPService.decrypt_secret(user.totp_secret_encrypted)
    if not TOTPService.verify_code(secret, data.code):
        raise UnauthorizedError("Invalid code")

    user.is_2fa_enabled = True
    user.is_2fa_pending = False
    await db.commit()

    await redis_cb.call(lambda: r.delete(f"2fa_pending:{user.id}"))

    logger.info(f"2FA enabled: {user.email}")
    return success_response({"status": "2fa_enabled"})


@router.post("/2fa/disable", summary="Disable 2FA")
async def disable_2fa(
    data: TwoFactorDisableRequest, request: Request, db: AsyncSession = Depends(get_db),
):
    """Disable 2FA — requires correct password AND current TOTP code."""
    user = await get_current_user(request, db)

    if not user.is_2fa_enabled:
        raise ValidationError("2FA is not enabled")

    if not verify_password(data.password, user.password_hash):
        raise UnauthorizedError("Incorrect password")

    secret = TOTPService.decrypt_secret(user.totp_secret_encrypted)
    if not TOTPService.verify_code(secret, data.code):
        raise UnauthorizedError("Invalid 2FA code")

    user.is_2fa_enabled = False
    user.totp_secret_encrypted = None
    user.is_2fa_pending = False
    await db.commit()

    r = get_redis()
    await redis_cb.call(lambda: r.delete(f"2fa_pending:{user.id}"))

    logger.info(f"2FA disabled: {user.email}")
    return success_response({"status": "2fa_disabled"})


@router.get("/2fa/status", summary="Get 2FA status")
async def two_factor_status(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    return success_response({
        "is_2fa_enabled": user.is_2fa_enabled,
        "is_2fa_pending": user.is_2fa_pending,
    })


# ─── Password reset ────────────────────────────────────────────────────────────


@router.post("/forgot-password", summary="Request password reset code")
async def forgot_password(data: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user:
        return success_response({"message": "If that email is registered, a code was sent"})

    code = await OTPService.send_code(data.email, _OTP_RESET)
    EmailService.send_password_reset_code(data.email, code)
    logger.info(f"Password reset requested: {data.email}")
    return success_response({"message": "Reset code sent"})


@router.post("/reset-password", summary="Reset password with code")
async def reset_password(data: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    if len(data.new_password) < 8:
        raise ValidationError("New password must be at least 8 characters")

    if not await OTPService.verify_code(data.email, _OTP_RESET, data.code):
        raise UnauthorizedError("Invalid or expired code")

    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user:
        raise UnauthorizedError("User not found")

    user.password_hash = hash_password(data.new_password)
    # Invalidate all existing sessions — password reset is a security event
    _revoke_all_refresh_tokens(db, str(user.id))
    await db.commit()

    logger.info(f"Password reset: {data.email}")
    return success_response({"status": "password_reset"})


# ─── Login / Logout ───────────────────────────────────────────────────────────


@router.post("/login", summary="Login with email + password")
async def login(data: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user:
        raise UnauthorizedError("Invalid email or password")

    # Don't leak whether email exists based on password check timing
    if not verify_password(data.password, user.password_hash):
        raise UnauthorizedError("Invalid email or password")

    if not user.is_active:
        raise UnauthorizedError("Account is inactive")

    # Magic-link-only accounts have empty password_hash
    if not user.password_hash:
        raise UnauthorizedError("No password set for this account. Use magic link login.")

    if user.is_2fa_enabled:
        if not data.totp_code:
            raise UnauthorizedError("2FA code required")
        secret = TOTPService.decrypt_secret(user.totp_secret_encrypted)
        if not TOTPService.verify_code(secret, data.totp_code):
            raise UnauthorizedError("Invalid 2FA code")

    access_token, jti, refresh_token, token_record = _issue_tokens(response, str(user.id))
    db.add(token_record)
    await db.commit()
    set_auth_cookies(response, access_token, refresh_token)

    logger.info(f"Login: {data.email}")
    return success_response({"id": str(user.id), "email": user.email, "username": user.username})


@router.post("/logout", summary="Logout (current device)")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    _blacklist_access_token(request)

    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == refresh_token)
        )
        token_record = result.scalar_one_or_none()
        if token_record:
            token_record.revoked = True
            await db.commit()

    clear_auth_cookies(response)
    return success_response({"status": "logged_out"})


@router.post("/logout-all", summary="Logout all devices")
async def logout_all(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)

    _blacklist_access_token(request)
    _revoke_all_refresh_tokens(db, str(user.id))
    await db.commit()

    clear_auth_cookies(response)
    logger.info(f"Logout all: {user.id}")
    return success_response({"status": "logged_out_all_devices"})


@router.post("/change-password", summary="Change password")
async def change_password(
    data: ChangePasswordRequest, request: Request, response: Response,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)

    if not verify_password(data.old_password, user.password_hash):
        raise UnauthorizedError("Current password is incorrect")

    if len(data.new_password) < 8:
        raise ValidationError("New password must be at least 8 characters")

    user.password_hash = hash_password(data.new_password)

    _blacklist_access_token(request)
    # Revoke all OTHER refresh tokens; keep current so the re-login is seamless
    current_refresh = request.cookies.get("refresh_token")
    _revoke_all_refresh_tokens(db, str(user.id), keep_token_hash=current_refresh)
    await db.commit()

    new_access, new_jti, new_refresh, new_record = _issue_tokens(response, str(user.id))
    db.add(new_record)
    await db.commit()
    set_auth_cookies(response, new_access, new_refresh)

    logger.info(f"Password changed: {user.id}")
    return success_response({"status": "password_changed"})


@router.post("/refresh", summary="Refresh access token")
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise UnauthorizedError("No refresh token")

    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == refresh_token,
            RefreshToken.revoked.is_(False),
            RefreshToken.expires_at > datetime.now(UTC),
        )
    )
    token_record = result.scalar_one_or_none()
    if not token_record:
        raise UnauthorizedError("Invalid or expired refresh token")

    user_id = str(token_record.user_id)
    token_record.revoked = True

    new_refresh = str(uuid.uuid4())
    new_record = RefreshToken(
        id=new_refresh,
        user_id=token_record.user_id,
        token_hash=new_refresh,
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.jwt_refresh_expire),
    )
    db.add(new_record)

    access_token, jti = create_access_token(user_id)
    set_auth_cookies(response, access_token, new_refresh)
    await db.commit()
    return success_response({"status": "refreshed"})


@router.get("/me", summary="Get current user")
async def me(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    return success_response({
        "id": str(user.id),
        "email": user.email,
        "username": user.username,
        "is_email_verified": user.is_email_verified,
        "referral_code": user.referral_code,
    })
