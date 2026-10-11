from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.base import MoneyField, NonNegativeMoney, PositiveMoney


class OrderRequest(BaseModel):
    market_id: str = Field(..., max_length=64)
    outcome: str = Field(..., max_length=100)  # Accepts "yes", "no", or outcome name for multi-outcome markets
    side: str = Field(..., pattern="^(buy|sell)$")
    order_type: str = Field(default="market", pattern="^(market|limit|fill_or_kill)$")
    amount: PositiveMoney
    price: NonNegativeMoney | None = Field(None, le=1)  # required for limit
    expires_at: datetime | None = None  # for limit orders
    post_only: bool = False  # if True, reject if would execute immediately
    client_order_id: str | None = Field(None, max_length=64)
    max_slippage: NonNegativeMoney | None = Field(None, ge=0, le=0.10)  # cap at 10% slippage server-side
    min_shares_out: PositiveMoney | None = None  # minimum shares to receive
    # The price the user is agreeing to - normally the size-aware figure the form
    # was displaying, driven live off the socket. It is the reference
    # `max_slippage` is measured against.
    #
    # This exists because the only other candidate, the pool's price before the
    # order, scores the fill against something the user never saw and never
    # agreed to: it excludes their own price impact, and it is the AMM's price
    # even for the portion that matched against resting limit orders. Scoring
    # against it makes an ordinary order look like massive slippage and gets it
    # refused for the cost of the trade itself.
    #
    # Without it the bound is not enforced - `min_shares_out` still applies, so
    # the order cannot go against the user. A guarantee that cannot be evaluated
    # against what was actually promised is worse than none.
    expected_price: NonNegativeMoney | None = Field(None, gt=0, le=1)
    # Optional extra assertion: "and it is still exactly this price". A snapshot
    # with a TTL, so it fails on elapsed time alone - see order_service for why
    # it is not what protects the user.
    quote_id: str | None = Field(None, max_length=64)  # bind to a specific quote


class QuoteRequest(BaseModel):
    market_id: str = Field(..., max_length=64)
    outcome: str = Field(..., max_length=100)
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
    market_slug: str
    market_question: str | None
    outcome: str
    shares_held: MoneyField
    average_price: MoneyField
    realized_pnl: MoneyField
    unrealized_pnl: MoneyField
    # The position's own current price. On a parimutuel market this is that
    # outcome's share of the market, not a yes/no value derived from a pool it
    # has nothing to do with.
    current_price: MoneyField | None = None

    model_config = {"from_attributes": True}
