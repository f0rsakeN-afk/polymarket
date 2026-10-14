"""Step-up authentication for actions that need more than a live session.

Shared rather than duplicated, because the thing that must not be duplicated
incorrectly is the *protection*, not the endpoint. A session is a bearer token:
stolen cookie, XSS, an unattended laptop. For an action that moves money or
erases an account, "is this really you?" is a different question from "is this
session valid?", and a second hand-rolled copy of this check is a second chance
to forget the rate limiting.

The friction limiter in particular is not optional decoration. Adding a password
check to an endpoint turns it into a password oracle unless it is throttled, and
a per-IP limit alone is not enough - an attacker rotating source addresses gets a
fresh allowance each time. So failures feed the same progressive friction the
login path already uses, keyed on the account. Otherwise the account's password
would be guarded strictly at sign-in and not at all at the endpoints that most
need it.
"""

from fastapi import HTTPException, Request

from app.api.exceptions import UnauthorizedError, ValidationError
from app.api.middleware import _get_client_ip
from app.deps import verify_password
from app.models.user import User
from app.schemas.auth import StepUpRequest
from app.services.rate_limit_service import RateLimitService
from app.services.totp_service import TOTPService


async def require_step_up(request: Request, user: User, data: StepUpRequest) -> None:
    """Prove the caller is present, not merely holding a session.

    Requires the password always, and a TOTP code when the account has 2FA
    enabled - so the bar is *the strongest factor available* rather than a fixed
    one that happens to suit whoever is calling.

    **The server decides the required factor, not the client.** A client that
    simply omitted `code` would otherwise quietly downgrade a protected action to
    password-only, which is exactly the shape of attack step-up exists to stop -
    and it would be a downgrade nobody had to work for.
    """
    ip = _get_client_ip(request)

    # The same password the login path guards, so it gets the same protection.
    rl_result, is_slowed = await RateLimitService.check_with_friction(user.email, ip)
    if is_slowed and rl_result.retry_after:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Slow down.",
            headers={"Retry-After": str(int(rl_result.retry_after))},
        )
    if not rl_result.allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(rl_result.retry_after)},
        )

    if not verify_password(data.password, user.password_hash):
        await RateLimitService.record_failure(user.email, ip)
        raise UnauthorizedError("Incorrect password", error_code="STEP_UP_PASSWORD_INVALID")

    if user.is_2fa_enabled:
        if not data.code:
            raise ValidationError(
                "2FA is enabled for this account - a current code is required",
                error_code="STEP_UP_2FA_REQUIRED",
            )
        secret = TOTPService.decrypt_secret(user.totp_secret_encrypted)
        if not TOTPService.verify_code(secret, data.code):
            await RateLimitService.record_failure(user.email, ip)
            raise UnauthorizedError("Invalid 2FA code", error_code="STEP_UP_2FA_INVALID")

    # Proven present. Clear the friction so a legitimate user who fat-fingered the
    # code is not left in a penalty box for their next attempt.
    await RateLimitService.reset_friction(user.email, ip)