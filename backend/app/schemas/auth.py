from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=30, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(..., min_length=8, max_length=128)
    referral_code: str | None = None


class SetPasswordRequest(BaseModel):
    password: str = Field(..., min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6)


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class VerifyMagicUrlRequest(BaseModel):
    token: str


class MagicLinkRequest(BaseModel):
    email: EmailStr


class VerifyMagicRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6)
    totp_code: str | None = None  # optional 2FA after magic login


class MagicUrl2FARequest(BaseModel):
    partial_token: str = Field(..., min_length=1)
    totp_code: str = Field(..., min_length=6, max_length=6)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)
    totp_code: str | None = None  # required if 2FA enabled


class RefreshRequest(BaseModel):
    pass


class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    is_email_verified: bool

    model_config = {"from_attributes": True}


# ─── 2FA schemas ─────────────────────────────────────────────────────────────

class TwoFactorSetupResponse(BaseModel):
    uri: str  # Only return URI — QR code handles provisioning; manual entry key shown once on confirm screen


class TwoFactorEnableRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class TwoFactorDisableRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)
    password: str = Field(..., min_length=1)
