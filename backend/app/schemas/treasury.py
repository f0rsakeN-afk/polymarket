from datetime import datetime

from pydantic import BaseModel

from app.schemas.base import MoneyField


class TreasuryResponse(BaseModel):
    id: str
    balance: MoneyField
    total_fees_collected: MoneyField
    total_fees_distributed: MoneyField


class TreasuryLogResponse(BaseModel):
    id: str
    event: str
    amount: MoneyField
    reference_type: str | None = None
    reference_id: str | None = None
    created_at: datetime
