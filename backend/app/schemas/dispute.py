from datetime import datetime

from pydantic import BaseModel


class CreateDisputeRequest(BaseModel):
    market_id: str
    evidence: str
    evidence_url: str | None = None


class ProposeResolutionRequest(BaseModel):
    market_id: str
    outcome_id: str
    resolution_source: str


class AdjudicateDisputeRequest(BaseModel):
    ruling: str
    admin_note: str | None = None


class DisputeResponse(BaseModel):
    id: str
    market_id: str
    user_id: str
    evidence: str
    evidence_url: str | None = None
    status: str
    created_at: datetime
