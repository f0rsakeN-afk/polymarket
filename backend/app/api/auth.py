import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.exceptions import (
    ConflictError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
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
from app.models.user import RefreshToken, Session, User
from app.models.wallet import Wallet
from app.redis import get_redis, redis_cb
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MagicLinkRequest,
    MagicUrl2FARequest,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    SetPasswordRequest,
    TwoFactorDisableRequest,
    TwoFactorEnableRequest,
    TwoFactorSetupResponse,
    VerifyEmailRequest,
    VerifyMagicRequest,
)
from app.services.audit_service import AuthAuditService
from app.services.email_service import EmailService
from app.services.otp_service import OTPService
from app.services.password_strength_service import PasswordStrengthService
from app.services.rate_limit_service import RateLimitService
from app.services.totp_service import TOTPService

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/auth", tags=["auth"])

# OTP key prefixes — match the values in OTPService
_OTP_VERIFY = "verify"
_OTP_MAGIC = "magic"
_OTP_RESET = "resetpwd"


def _issue_tokens(
    response: Response,
    user_id: str,
    db: AsyncSession,
    ip: str | None = None,
    ua: str | None = None,
):
    """Create access + refresh token + session record, set cookies. Caller commits."""
    access_token, jti = create_access_token(str(user_id))
    refresh_token_id = str(uuid.uuid4())
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.jwt_refresh_expire)

    token_record = RefreshToken(
        id=refresh_token_id,
        user_id=user_id,
        token_hash=refresh_token_id,
        expires_at=expires_at,
        device_info=ua,
    )
    db.add(token_record)

    session = Session(
        user_id=user_id,
        refresh_token_id=refresh_token_id,
        ip_address=ip,
        user_agent=ua,
        expires_at=expires_at,
    )
    db.add(session)

    return access_token, jti, refresh_token_id, token_record


async def _revoke_all_refresh_tokens(db: AsyncSession, user_id: str, keep_token_hash: str | None = None):
    """
    Revoke all non-revoked refresh tokens for a user in a single UPDATE.
    Optionally keep one token (used by change-password to preserve current session).
    """
    from sqlalchemy import update
    stmt = (
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked.is_(False),
            # Conditionally exclude the token to keep (handled in Python for the hash check)
        )
    )
    if keep_token_hash:
        # We still fetch to filter in Python since we only have the hash, not the token value
        result = await db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked.is_(False),
            )
        )
        for token in result.scalars().all():
            if token.token_hash != keep_token_hash:
                token.revoked = True
    else:
        await db.execute(stmt.values(revoked=True))


def _get_client_ip(request: Request) -> str:
    """Get real client IP, accounting for X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _blacklist_access_token(request: Request):
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
                await blacklist_token(jti, ttl)
    except Exception:
        pass


# ─── Registration ──────────────────────────────────────────────────────────────


@router.post("/register", summary="Register")
async def register(data: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    if len(data.username) < 3:
        raise ValidationError("Username must be at least 3 characters")

    strong, reason = PasswordStrengthService.check(data.password)
    if not strong:
        raise ValidationError(reason)

    ip = _get_client_ip(request)
    ua = request.headers.get("user-agent")

    # Check email — if verified, tell them to login; if not, resend code silently
    email_result = await db.execute(select(User).where(User.email == data.email))
    existing_user = email_result.scalar_one_or_none()
    if existing_user:
        if existing_user.is_email_verified:
            raise ConflictError("An account with this email already exists. Please sign in.")
        # Unverified — resend code so they can complete verification
        code = await OTPService.send_code(data.email, _OTP_VERIFY)
        EmailService.send_verification_code(data.email, code)
        await AuthAuditService.log_register(db, data.email, str(existing_user.id), ip, ua)
        return success_response({
            "id": str(existing_user.id),
            "email": existing_user.email,
            "username": existing_user.username,
            "email_resent": True,
        })

    user = User(email=data.email, username=data.username, password_hash=hash_password(data.password), is_email_verified=False)
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

    code = await OTPService.send_code(data.email, _OTP_VERIFY)
    EmailService.send_verification_code(data.email, code)
    await AuthAuditService.log_register(db, data.email, str(user.id), ip, ua)

    logger.info(f"User registered (unverified): {data.email} ({user.id})")
    return success_response({"id": str(user.id), "email": user.email, "username": user.username})


@router.post("/verify-email", summary="Verify email")
async def verify_email(data: VerifyEmailRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user_result = await db.execute(select(User).where(User.email == data.email))
    user = user_result.scalar_one_or_none()
    if not user:
        raise UnauthorizedError("User not found")
    if user.is_email_verified:
        return success_response({"id": str(user.id), "email": user.email, "verified": True})

    ip = _get_client_ip(request)
    rl_result, is_slowed = await RateLimitService.check_with_friction(data.email, ip)
    if is_slowed and rl_result.retry_after:
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="Too many attempts. Slow down.", headers={"Retry-After": str(int(rl_result.retry_after))})
    if not rl_result.allowed:
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="Rate limit exceeded", headers={"Retry-After": str(rl_result.retry_after)})

    if not await OTPService.verify_code(data.email, _OTP_VERIFY, data.code):
        await RateLimitService.record_failure(data.email, ip)
        raise UnauthorizedError("Invalid or expired code")

    await RateLimitService.reset_friction(data.email, ip)
    user.is_email_verified = True
    await db.commit()

    ua = request.headers.get("user-agent")
    await AuthAuditService.log_email_verified(db, data.email, str(user.id), ip, ua)
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
    strong, reason = PasswordStrengthService.check(data.password)
    if not strong:
        raise ValidationError(reason)

    user = await get_current_user(request, db)
    ip = _get_client_ip(request)
    ua = request.headers.get("user-agent")

    user.password_hash = hash_password(data.password)
    await db.commit()

    await AuthAuditService.log_password_change(db, str(user.id), ip, ua)
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
    r = await get_redis()
    await redis_cb.call(lambda: r.set(f"magicurl:{token}", str(user.id), ex=900))

    magic_url = f"{settings.frontend_url}/auth/magic-url?token={token}"
    EmailService.send_magic_url(data.email, magic_url)
    logger.info(f"Magic URL requested: {data.email}")
    return success_response({"message": "Login link sent"})


@router.get("/verify-magic-url", summary="Verify magic link URL token (GET — for browser redirect)")
async def verify_magic_url(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    token = request.query_params.get("token")
    if not token:
        raise UnauthorizedError("Missing token")

    r = await get_redis()
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
        await redis_cb.call(lambda: r.set(f"partial:{partial}", user_id, ex=300))
        return success_response({"requires_2fa": True, "partial_token": partial})

    ip = _get_client_ip(request)
    access_token, jti, refresh_token, token_record = _issue_tokens(response, str(user.id), db, ip, request.headers.get("user-agent"))
    await db.commit()
    set_auth_cookies(response, access_token, refresh_token)

    logger.info(f"Magic URL login: {user.email}")
    return success_response({"id": str(user.id), "email": user.email, "username": user.username})


@router.post("/verify-magic-url-2fa", summary="Complete magic URL login with 2FA")
async def verify_magic_url_2fa(
    data: MagicUrl2FARequest, request: Request, response: Response, db: AsyncSession = Depends(get_db),
):
    """Complete magic URL login when 2FA is enabled. Friction tracked by partial token + IP."""
    r = await get_redis()
    user_id = await redis_cb.call(lambda: r.get(f"partial:{data.partial_token}"))
    if not user_id:
        raise UnauthorizedError("Session expired or invalid")

    ip = _get_client_ip(request)
    ua = request.headers.get("user-agent")
    # Friction key = partial_token since we don't have email until after we resolve user
    friction_key = f"partial:{data.partial_token}"

    rl_result, is_slowed = await RateLimitService.check_with_friction(friction_key, ip)
    if is_slowed and rl_result.retry_after:
        await redis_cb.call(lambda: r.delete(f"partial:{data.partial_token}"))
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="Too many attempts. Slow down.", headers={"Retry-After": str(int(rl_result.retry_after))})
    if not rl_result.allowed:
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="Rate limit exceeded", headers={"Retry-After": str(rl_result.retry_after)})

    user_result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        raise UnauthorizedError("Account not found or inactive")

    if not (user.is_2fa_enabled and user.totp_secret_encrypted):
        raise UnauthorizedError("2FA not enabled for this account")

    secret = TOTPService.decrypt_secret(user.totp_secret_encrypted)
    if not TOTPService.verify_code(secret, data.totp_code):
        await redis_cb.call(lambda: r.delete(f"partial:{data.partial_token}"))
        await RateLimitService.record_failure(user.email, ip)
        raise UnauthorizedError("Invalid 2FA code")

    # Delete partial token only after successful 2FA — allows retry on TOTP failure
    await redis_cb.call(lambda: r.delete(f"partial:{data.partial_token}"))

    access_token, jti, refresh_token, token_record = _issue_tokens(response, str(user.id), db, ip, ua)
    await db.commit()
    set_auth_cookies(response, access_token, refresh_token)

    logger.info(f"Magic URL + 2FA login: {user.email}")
    return success_response({"id": str(user.id), "email": user.email, "username": user.username})


@router.post("/verify-magic", summary="Verify magic link code")
async def verify_magic(data: VerifyMagicRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    ip = _get_client_ip(request)

    rl_result, is_slowed = await RateLimitService.check_with_friction(data.email, ip)
    if is_slowed and rl_result.retry_after:
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="Too many attempts. Slow down.", headers={"Retry-After": str(int(rl_result.retry_after))})
    if not rl_result.allowed:
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="Rate limit exceeded", headers={"Retry-After": str(rl_result.retry_after)})

    if not await OTPService.verify_code(data.email, _OTP_MAGIC, data.code):
        await RateLimitService.record_failure(data.email, ip)
        raise UnauthorizedError("Invalid or expired code")

    user_result = await db.execute(select(User).where(User.email == data.email))
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        raise UnauthorizedError("Account not found or inactive")

    if user.is_2fa_enabled:
        if not data.totp_code:
            # Issue partial token so frontend can complete with TOTP without re-sending magic code
            r = await get_redis()
            partial = str(uuid.uuid4())
            await redis_cb.call(lambda: r.set(f"magic_partial:{partial}", f"{user.id}:{data.email}", ex=300))
            raise UnauthorizedError(f"2FA code required:{partial}")
        secret = TOTPService.decrypt_secret(user.totp_secret_encrypted)
        if not TOTPService.verify_code(secret, data.totp_code):
            await RateLimitService.record_failure(data.email, ip)
            raise UnauthorizedError("Invalid 2FA code")

    await RateLimitService.reset_friction(data.email, ip)
    access_token, jti, refresh_token, token_record = _issue_tokens(response, str(user.id), db, ip, request.headers.get("user-agent"))
    await db.commit()
    set_auth_cookies(response, access_token, refresh_token)

    logger.info(f"Magic login: {data.email}")
    return success_response({"id": str(user.id), "email": user.email, "username": user.username})


@router.post("/verify-magic-2fa", summary="Complete magic link login with 2FA using partial token")
async def verify_magic_2fa(
    data: MagicUrl2FARequest, request: Request, response: Response, db: AsyncSession = Depends(get_db),
):
    """Complete magic link login when 2FA is enabled and magic code was already verified."""
    r = await get_redis()
    stored = await redis_cb.call(lambda: r.get(f"magic_partial:{data.partial_token}"))
    if not stored:
        raise UnauthorizedError("Session expired. Please sign in again.")

    user_id, email = stored.split(":", 1)
    user_result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        raise UnauthorizedError("Account not found or inactive")

    if not (user.is_2fa_enabled and user.totp_secret_encrypted):
        raise UnauthorizedError("2FA not enabled for this account")

    secret = TOTPService.decrypt_secret(user.totp_secret_encrypted)
    if not TOTPService.verify_code(secret, data.totp_code):
        await redis_cb.call(lambda: r.delete(f"magic_partial:{data.partial_token}"))
        await RateLimitService.record_failure(email, _get_client_ip(request))
        raise UnauthorizedError("Invalid 2FA code")

    await redis_cb.call(lambda: r.delete(f"magic_partial:{data.partial_token}"))
    ip = _get_client_ip(request)
    access_token, jti, refresh_token, token_record = _issue_tokens(response, str(user.id), db, ip, request.headers.get("user-agent"))
    await db.commit()
    set_auth_cookies(response, access_token, refresh_token)

    logger.info(f"Magic + 2FA login: {email}")
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

    r = await get_redis()
    await redis_cb.call(
        lambda: r.set(f"2fa_pending:{user.id}", "1", ex=settings.totp_setup_expire_seconds)
    )

    ip = _get_client_ip(request)
    ua = request.headers.get("user-agent")
    await AuthAuditService.log_2fa_setup_requested(db, str(user.id), ip, ua)

    logger.info(f"2FA setup initiated: {user.email}")
    return success_response(TwoFactorSetupResponse(uri=uri).model_dump())


@router.post("/2fa/enable", summary="Confirm and enable 2FA")
async def enable_2fa(
    data: TwoFactorEnableRequest, request: Request, db: AsyncSession = Depends(get_db),
):
    """Verify TOTP code to activate 2FA. Setup must be fresh (< TOTP_SETUP_EXPIRE_SECONDS old)."""
    user = await get_current_user(request, db)
    ip = _get_client_ip(request)
    ua = request.headers.get("user-agent")

    if not (user.totp_secret_encrypted and user.is_2fa_pending):
        raise ValidationError("No active 2FA setup. Call /2fa/setup first.")

    r = await get_redis()
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
    await AuthAuditService.log_2fa_enabled(db, str(user.id), ip, ua)

    logger.info(f"2FA enabled: {user.email}")
    return success_response({"status": "2fa_enabled"})


@router.post("/2fa/disable", summary="Disable 2FA")
async def disable_2fa(
    data: TwoFactorDisableRequest, request: Request, db: AsyncSession = Depends(get_db),
):
    """Disable 2FA — requires correct password AND current TOTP code."""
    user = await get_current_user(request, db)
    ip = _get_client_ip(request)
    ua = request.headers.get("user-agent")

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

    r = await get_redis()
    await redis_cb.call(lambda: r.delete(f"2fa_pending:{user.id}"))
    await AuthAuditService.log_2fa_disabled(db, str(user.id), ip, ua)

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
async def forgot_password(data: ForgotPasswordRequest, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user:
        return success_response({"message": "If that email is registered, a code was sent"})

    ip = _get_client_ip(request)
    ua = request.headers.get("user-agent")
    code = await OTPService.send_code(data.email, _OTP_RESET)
    EmailService.send_password_reset_code(data.email, code)
    await AuthAuditService.log_password_reset_request(db, data.email, ip, ua)
    logger.info(f"Password reset requested: {data.email}")
    return success_response({"message": "Reset code sent"})


@router.post("/reset-password", summary="Reset password with code")
async def reset_password(data: ResetPasswordRequest, request: Request, db: AsyncSession = Depends(get_db)):
    ip = _get_client_ip(request)
    ua = request.headers.get("user-agent")

    # Rate limit before OTP check
    rl_result, is_slowed = await RateLimitService.check_with_friction(data.email, ip)
    if is_slowed and rl_result.retry_after:
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="Too many attempts. Slow down.", headers={"Retry-After": str(int(rl_result.retry_after))})
    if not rl_result.allowed:
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="Rate limit exceeded", headers={"Retry-After": str(rl_result.retry_after)})

    # OTP verification must come BEFORE password strength check —
    # prevents brute-forcing password policy without a valid OTP
    if not await OTPService.verify_code(data.email, _OTP_RESET, data.code):
        await RateLimitService.record_failure(data.email, ip)
        raise UnauthorizedError("Invalid or expired code")

    await RateLimitService.reset_friction(data.email, ip)

    # Password strength check after OTP is verified
    strong, reason = PasswordStrengthService.check(data.new_password)
    if not strong:
        raise ValidationError(reason)

    user_result = await db.execute(select(User).where(User.email == data.email))
    user = user_result.scalar_one_or_none()
    if not user:
        raise UnauthorizedError("User not found")

    user.password_hash = hash_password(data.new_password)
    await _revoke_all_refresh_tokens(db, str(user.id))
    await db.commit()

    await AuthAuditService.log_password_reset_success(db, data.email, str(user.id), ip, ua)
    logger.info(f"Password reset: {data.email}")
    return success_response({"status": "password_reset"})


# ─── Login / Logout ───────────────────────────────────────────────────────────


@router.post("/login", summary="Login with email + password")
async def login(data: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    ip = _get_client_ip(request)
    ua = request.headers.get("user-agent")

    rl_result, is_slowed = await RateLimitService.check_with_friction(data.email, ip)
    if is_slowed and rl_result.retry_after:
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="Too many attempts. Slow down.", headers={"Retry-After": str(int(rl_result.retry_after))})
    if not rl_result.allowed:
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="Rate limit exceeded", headers={"Retry-After": str(rl_result.retry_after)})

    user_result = await db.execute(select(User).where(User.email == data.email))
    user = user_result.scalar_one_or_none()

    if not user:
        await AuthAuditService.log_login_fail(db, data.email, ip, ua, "user_not_found")
        raise UnauthorizedError("Invalid email or password")

    if not verify_password(data.password, user.password_hash):
        await RateLimitService.record_failure(data.email, ip)
        await AuthAuditService.log_login_fail(db, data.email, ip, ua, "wrong_password")
        raise UnauthorizedError("Invalid email or password")

    if not user.is_active:
        raise UnauthorizedError("Account is inactive")

    if not user.password_hash:
        raise UnauthorizedError("No password set for this account. Use magic link login.")

    if user.is_2fa_enabled:
        if not data.totp_code:
            await RateLimitService.record_failure(data.email, ip)
            await AuthAuditService.log_login_fail(db, data.email, ip, ua, "2fa_code_missing")
            raise UnauthorizedError("2FA code required")
        secret = TOTPService.decrypt_secret(user.totp_secret_encrypted)
        if not TOTPService.verify_code(secret, data.totp_code):
            await RateLimitService.record_failure(data.email, ip)
            await AuthAuditService.log_login_fail(db, data.email, ip, ua, "wrong_2fa_code")
            raise UnauthorizedError("Invalid 2FA code")

    await RateLimitService.reset_friction(data.email, ip)
    access_token, jti, refresh_token, token_record = _issue_tokens(response, str(user.id), db, ip, ua)
    await db.commit()
    set_auth_cookies(response, access_token, refresh_token)

    await AuthAuditService.log_login_success(db, data.email, str(user.id), ip, ua)
    logger.info(f"Login: {data.email}")
    return success_response({"id": str(user.id), "email": user.email, "username": user.username})


@router.post("/logout", summary="Logout (current device)")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    ip = _get_client_ip(request)
    ua = request.headers.get("user-agent")

    await _blacklist_access_token(request)

    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == refresh_token)
        )
        token_record = result.scalar_one_or_none()
        if token_record:
            token_record.revoked = True
            # Also revoke the linked session
            session_result = await db.execute(
                select(Session).where(Session.refresh_token_id == token_record.id)
            )
            session = session_result.scalar_one_or_none()
            if session:
                session.revoked = True
            await db.commit()

    clear_auth_cookies(response)
    await AuthAuditService.log_logout(db, str(user.id), ip, ua)
    return success_response({"status": "logged_out"})


@router.post("/logout-all", summary="Logout all devices")
async def logout_all(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    ip = _get_client_ip(request)
    ua = request.headers.get("user-agent")

    await _blacklist_access_token(request)
    _revoke_all_refresh_tokens(db, str(user.id))
    # Also revoke all sessions for this user
    sessions_result = await db.execute(
        select(Session).where(Session.user_id == user.id, not Session.revoked)
    )
    for s in sessions_result.scalars().all():
        s.revoked = True
    await db.commit()

    clear_auth_cookies(response)
    await AuthAuditService.log_logout_all(db, str(user.id), ip, ua)
    logger.info(f"Logout all: {user.id}")
    return success_response({"status": "logged_out_all_devices"})


@router.get("/sessions", summary="List active sessions")
async def list_sessions(request: Request, db: AsyncSession = Depends(get_db)):
    """List all active sessions for the current user."""
    user = await get_current_user(request, db)

    result = await db.execute(
        select(Session).where(
            Session.user_id == user.id,
            not Session.revoked,
        ).order_by(Session.last_active_at.desc())
    )
    sessions = result.scalars().all()

    return success_response([
        {
            "id": str(s.id),
            "ip_address": s.ip_address,
            "user_agent": s.user_agent,
            "created_at": s.created_at,
            "last_active_at": s.last_active_at,
            "expires_at": s.expires_at,
        }
        for s in sessions
    ])


@router.delete("/sessions/{session_id}", summary="Revoke a specific session")
async def revoke_session(session_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Revoke a specific session by ID. Users can only revoke their own sessions."""
    user = await get_current_user(request, db)

    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user.id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise NotFoundError("Session not found")

    session.revoked = True

    # Also revoke the associated refresh token
    refresh_result = await db.execute(
        select(RefreshToken).where(RefreshToken.id == session.refresh_token_id)
    )
    rt = refresh_result.scalar_one_or_none()
    if rt:
        rt.revoked = True

    await db.commit()

    ip = _get_client_ip(request)
    ua = request.headers.get("user-agent")
    await AuthAuditService.log(db, "session_revoked", True, user_id=str(user.id), ip_address=ip, user_agent=ua)

    return success_response({"status": "session_revoked"})


@router.post("/change-password", summary="Change password")
async def change_password(
    data: ChangePasswordRequest, request: Request, response: Response,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)
    ip = _get_client_ip(request)
    ua = request.headers.get("user-agent")

    if not verify_password(data.old_password, user.password_hash):
        await AuthAuditService.log_password_change(db, str(user.id), ip, ua, success=False, reason="wrong_old_password")
        raise UnauthorizedError("Current password is incorrect")

    strong, reason = PasswordStrengthService.check(data.new_password)
    if not strong:
        raise ValidationError(reason)

    user.password_hash = hash_password(data.new_password)

    await _blacklist_access_token(request)
    current_refresh = request.cookies.get("refresh_token")
    await _revoke_all_refresh_tokens(db, str(user.id), keep_token_hash=current_refresh)
    await AuthAuditService.log_password_change(db, str(user.id), ip, ua)
    new_access, new_jti, new_refresh, new_record = _issue_tokens(response, str(user.id), db, ip, ua)
    # Single atomic commit: password change + token revocation + new tokens + audit log
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
        select(RefreshToken)
        .where(
            RefreshToken.token_hash == refresh_token,
            RefreshToken.revoked.is_(False),
            RefreshToken.expires_at > datetime.now(UTC),
        )
        .options(selectinload(RefreshToken.current_session))
        .with_for_update()
    )
    token_record = result.scalar_one_or_none()
    if not token_record:
        raise UnauthorizedError("Invalid or expired refresh token")

    user_id = str(token_record.user_id)
    token_record.revoked = True

    # Update last_active_at on the linked session
    if token_record.current_session:
        token_record.current_session.last_active_at = datetime.now(UTC)

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
        "is_admin": user.is_admin,
        "is_2fa_enabled": user.is_2fa_enabled,
        "referral_code": user.referral_code,
    })
