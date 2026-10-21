from datetime import datetime

from pydantic import BaseModel

from app.schemas.auth import StepUpRequest
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


class TreasuryDistributeRequest(StepUpRequest):
    """Credentials for a manual treasury withdrawal.

    Inherits the step-up fields rather than repeating them: this endpoint moves
    money, and an admin session is a bearer token. Spelling the fields out again
    here would be how it came to be a password-less withdrawal in the first place.
    """
