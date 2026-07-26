from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str
    password: str
    referral_code: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    pass


class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    is_verified: bool

    model_config = {"from_attributes": True}
