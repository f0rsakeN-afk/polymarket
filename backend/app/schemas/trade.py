from datetime import datetime

from pydantic import BaseModel


class TradeResponse(BaseModel):
    id: str
    market_id: str
    market_slug: str
    market_question: str
    outcome: str
    side: str
    price: float
    amount: float
    executed_at: datetime

    model_config = {"from_attributes": True}
