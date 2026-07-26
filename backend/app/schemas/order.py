from datetime import datetime
from pydantic import BaseModel, Field


class OrderRequest(BaseModel):
    market_id: str
    outcome: str = Field(...)  # Accepts "yes", "no", or outcome name for multi-outcome markets
    side: str = Field(..., pattern="^(buy|sell)$")
    order_type: str = Field(default="market", pattern="^(market|limit|fill_or_kill)$")
    amount: float = Field(..., gt=0)
    price: float | None = Field(None, ge=0, le=1)  # required for limit
    expires_at: datetime | None = None  # for limit orders
    post_only: bool = False  # if True, reject if would execute immediately
    client_order_id: str | None = None


class OrderResponse(BaseModel):
    id: str
    market_id: str
    outcome: str
    side: str
    order_type: str
    amount: float
    price: float
    status: str
    shares_bought: float | None
    shares_sold: float | None
    fee: float | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PositionResponse(BaseModel):
    id: str
    market_id: str
    market_question: str | None
    outcome: str
    shares_held: float
    average_price: float
    realized_pnl: float
    unrealized_pnl: float

    model_config = {"from_attributes": True}
