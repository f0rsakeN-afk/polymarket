from datetime import datetime

from pydantic import BaseModel

from app.schemas.base import MoneyField


class TradeResponse(BaseModel):
    id: str
    market_id: str
    market_slug: str
    market_question: str
    outcome: str
    side: str
    price: MoneyField
    amount: MoneyField
    executed_at: datetime

    model_config = {"from_attributes": True}
