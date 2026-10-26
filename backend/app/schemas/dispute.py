from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.auth import StepUpRequest


class CreateDisputeRequest(BaseModel):
    market_id: str = Field(..., min_length=1, max_length=64)
    evidence: str = Field(..., min_length=10, max_length=5000)
    evidence_url: str | None = Field(default=None, max_length=1000)


class ProposeResolutionRequest(BaseModel):
    market_id: str = Field(..., min_length=1, max_length=64)
    outcome_id: str = Field(..., min_length=1, max_length=64)
    resolution_source: str = Field(..., min_length=10, max_length=1000)


class AdjudicateDisputeRequest(StepUpRequest):
    """A ruling, plus the credentials that prove the admin is present.

    Inherits the step-up fields rather than repeating them, because an upheld
    ruling resolves a market and pays out: it is the most consequential
    privileged action in the product, and an admin session is a bearer token.
    `code` is required only when the admin has 2FA enabled, and the server
    decides that - a client that omitted it cannot quietly downgrade the ruling
    to password-only.
    """

    ruling: str = Field(..., pattern="^(upheld|dismissed)$")
    admin_note: str | None = Field(default=None, max_length=2000)


class DisputeResponse(BaseModel):
    id: str
    market_id: str
    user_id: str
    evidence: str
    evidence_url: str | None = None
    status: str
    created_at: datetime
