from datetime import datetime

from pydantic import BaseModel, Field


class CreateDisputeRequest(BaseModel):
    market_id: str = Field(..., min_length=1)
    evidence: str = Field(..., min_length=10, max_length=5000)
    evidence_url: str | None = Field(default=None, max_length=1000)


class ProposeResolutionRequest(BaseModel):
    market_id: str = Field(..., min_length=1)
    outcome_id: str = Field(..., min_length=1)
    resolution_source: str = Field(..., min_length=10, max_length=1000)


class AdjudicateDisputeRequest(BaseModel):
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
