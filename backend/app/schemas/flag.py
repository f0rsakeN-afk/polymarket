from datetime import datetime

from pydantic import BaseModel, Field


class FlagCreateRequest(BaseModel):
    market_id: str
    reason: str = Field(..., min_length=5, max_length=1000)


class FlagResponse(BaseModel):
    id: str
    market_id: str
    user_id: str
    reason: str
    status: str
    created_at: datetime


class ResolveFlagRequest(BaseModel):
    status: str = Field(..., pattern="^(resolved|dismissed)$")