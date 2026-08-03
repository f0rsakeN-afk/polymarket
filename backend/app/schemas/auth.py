from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str
    referral_code: str | None = None


class SetPasswordRequest(BaseModel):
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    code: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class MagicLinkRequest(BaseModel):
    email: EmailStr


class VerifyMagicRequest(BaseModel):
    email: EmailStr
    code: str
    totp_code: str | None = None  # optional 2FA after magic login


class MagicUrl2FARequest(BaseModel):
    partial_token: str
    totp_code: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str
    new_password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    totp_code: str | None = None  # required if 2FA enabled


class RefreshRequest(BaseModel):
    pass


class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    is_email_verified: bool

    model_config = {"from_attributes": True}


# ─── 2FA schemas ───────────────────────────────────────────────────────────────

class TwoFactorSetupResponse(BaseModel):
    secret: str
    uri: str
    base32: str


class TwoFactorEnableRequest(BaseModel):
    code: str


class TwoFactorDisableRequest(BaseModel):
    code: str
    password: str
