from datetime import datetime
from pydantic import BaseModel, Field
from decimal import Decimal


class OutcomeResponse(BaseModel):
    id: str
    name: str
    outcome_index: int

    model_config = {"from_attributes": True}


class MarketResponse(BaseModel):
    id: str
    slug: str
    question: str
    description: str | None
    category: str | None
    status: str
    total_liquidity: float
    total_volume: float
    yes_price: float
    no_price: float
    closes_at: datetime
    winning_outcome_id: str | None = None
    winning_outcome_name: str | None = None
    outcomes: list[OutcomeResponse] | None = None

    model_config = {"from_attributes": True}


class MarketDetailResponse(MarketResponse):
    outcomes: list[OutcomeResponse]
    spread: float
    created_at: datetime


class CreateMarketRequest(BaseModel):
    question: str = Field(..., min_length=5, max_length=1000)
    description: str | None = Field(None, max_length=5000)
    category: str | None = Field(None, max_length=100)
    slug: str = Field(..., min_length=3, max_length=255)
    closes_at: datetime
    initial_liquidity: float = Field(default=0, ge=0)


class MarketListResponse(BaseModel):
    success: bool = True
    data: list[MarketResponse]
    page: int
    page_size: int
    has_more: bool


class ResolveMarketRequest(BaseModel):
    winning_outcome_id: str
