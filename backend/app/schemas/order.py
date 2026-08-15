from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.base import MoneyField, NonNegativeMoney, PositiveMoney


class OrderRequest(BaseModel):
    market_id: str
    outcome: str = Field(...)  # Accepts "yes", "no", or outcome name for multi-outcome markets
    side: str = Field(..., pattern="^(buy|sell)$")
    order_type: str = Field(default="market", pattern="^(market|limit|fill_or_kill)$")
    amount: PositiveMoney
    price: NonNegativeMoney | None = Field(None, le=1)  # required for limit
    expires_at: datetime | None = None  # for limit orders
    post_only: bool = False  # if True, reject if would execute immediately
    client_order_id: str | None = None
    max_slippage: NonNegativeMoney | None = Field(None, le=1)  # e.g. 0.005 = 0.5%
    min_shares_out: PositiveMoney | None = None  # minimum shares to receive
    quote_id: str | None = None  # bind to a specific quote


class QuoteRequest(BaseModel):
    market_id: str
    outcome: str = Field(...)
    side: str = Field(..., pattern="^(buy|sell)$")
    amount: PositiveMoney


class QuoteResponse(BaseModel):
    quote_id: str
    market_id: str
    outcome: str
    side: str
    amount: MoneyField
    price: MoneyField
    slippage: MoneyField
    yes_price: MoneyField
    no_price: MoneyField
    expires_at: float  # unix timestamp


class OrderResponse(BaseModel):
    id: str
    market_id: str
    outcome: str
    side: str
    order_type: str
    amount: MoneyField
    price: MoneyField
    status: str
    shares_bought: MoneyField | None
    shares_sold: MoneyField | None
    fee: MoneyField | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PositionResponse(BaseModel):
    id: str
    market_id: str
    market_question: str | None
    outcome: str
    shares_held: MoneyField
    average_price: MoneyField
    realized_pnl: MoneyField
    unrealized_pnl: MoneyField

    model_config = {"from_attributes": True}
