from datetime import datetime

from pydantic import BaseModel, Field

from decimal import Decimal

from app.schemas.base import MoneyField, NonNegativeMoney


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
    total_liquidity: MoneyField
    total_volume: MoneyField
    yes_price: MoneyField
    no_price: MoneyField
    closes_at: datetime
    winning_outcome_id: str | None = None
    winning_outcome_name: str | None = None
    outcomes: list[OutcomeResponse] | None = None

    model_config = {"from_attributes": True}


class MarketDetailResponse(MarketResponse):
    outcomes: list[OutcomeResponse]
    spread: MoneyField
    created_at: datetime


class MarketOutcomeCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    outcome_index: int = Field(..., ge=0)


class CreateMarketRequest(BaseModel):
    question: str = Field(..., min_length=5, max_length=1000)
    description: str | None = Field(None, max_length=5000)
    category: str | None = Field(None, max_length=100)
    slug: str = Field(..., min_length=3, max_length=255)
    closes_at: datetime
    initial_liquidity: NonNegativeMoney = Field(default=Decimal("0"))
    initial_probability: NonNegativeMoney | None = Field(default=None, ge=0.01, le=0.99)
    outcomes_create: list[MarketOutcomeCreate] | None = None


class MarketListResponse(BaseModel):
    success: bool = True
    data: list[MarketResponse]
    page: int
    page_size: int
    has_more: bool


class ResolveMarketRequest(BaseModel):
    winning_outcome_id: str
