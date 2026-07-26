from datetime import datetime

from pydantic import BaseModel


class TreasuryResponse(BaseModel):
    id: str
    balance: float
    total_fees_collected: float
    total_fees_distributed: float


class TreasuryLogResponse(BaseModel):
    id: str
    event: str
    amount: float
    reference_type: str | None = None
    reference_id: str | None = None
    created_at: datetime
