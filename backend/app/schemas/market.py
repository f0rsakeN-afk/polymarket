from datetime import datetime
from decimal import Decimal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.base import MoneyField, NonNegativeMoney


class OutcomeResponse(BaseModel):
    id: str
    name: str
    outcome_index: int
    # This outcome's own price.
    #
    # The API used to expose only a single yes_price/no_price pair per market,
    # which is meaningless for a market with more than two outcomes - the front
    # end had nothing to show but that one pair, and mapped it onto outcomes
    # that had nothing to do with it. On a binary market this is 1 - the other
    # outcome's price.
    price: float | None = None

    model_config = {"from_attributes": True}


class MarketResponse(BaseModel):
    id: str
    slug: str
    question: str
    description: str | None
    category: str | None
    subcategory: str | None = None
    image_url: str | None = None
    # How the market settles, and against what.
    #
    # Returned to everyone, not just the author. The submitter wrote it as a
    # public promise about when this market closes, so traders are entitled to
    # read it before taking a position — a criteria the author can see and the
    # participants cannot would be worse than none.
    resolution_criteria: str | None = None
    resolution_source: str | None = None
    status: str
    total_liquidity: MoneyField
    total_volume: MoneyField
    yes_price: MoneyField
    no_price: MoneyField
    closes_at: datetime
    winning_outcome_id: str | None = None
    winning_outcome_name: str | None = None
    outcomes: list[OutcomeResponse] | None = None
    # Why a submission was declined, if it was.
    #
    # Only the author and admins can read an unpublished market, and the author
    # keeps read access to their own rejected submission — so this is the only
    # channel through which they learn anything. Null in every other state.
    rejection_reason: str | None = None
    rejected_at: datetime | None = None

    model_config = {"from_attributes": True}


class MarketDetailResponse(MarketResponse):
    outcomes: list[OutcomeResponse]
    spread: MoneyField
    created_at: datetime


class MarketOutcomeCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    outcome_index: int = Field(..., ge=0, le=1)  # binary markets only support 0 (Yes) and 1 (No)


class CreateMarketRequest(BaseModel):
    # Trimmed before the length checks, for the same reason as the ban reason:
    # "   "  is not five characters of question, and a validation rule that counts
    # whitespace is measuring the wrong thing.
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(..., min_length=5, max_length=1000)
    description: str | None = Field(None, max_length=5000)
    category: str | None = Field(None, max_length=100)
    subcategory: str | None = Field(None, max_length=100)
    image_url: str | None = Field(
        None,
        max_length=500,
        description="Absolute http(s) URL of an illustration. Must be a URL, not markup.",
    )
    slug: str = Field(..., min_length=3, max_length=255, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    closes_at: datetime

    # How this market will be settled, and against what.
    #
    # Optional on the request, but the single most useful thing a submitter can
    # supply. A market with no resolution criteria is a market nobody can fairly
    # declare a winner on, and the dispute path is expensive and slow for
    # everyone — so it is asked for prominently in the form and stored when given.
    resolution_criteria: str | None = Field(
        None,
        max_length=2000,
        description="How this market resolves: the event, the source, the cutoff.",
    )
    resolution_source: str | None = Field(
        None,
        max_length=1000,
        description="The specific source — a URL or named data feed — used to settle.",
    )

    initial_liquidity: NonNegativeMoney = Field(default=Decimal(0))
    initial_probability: NonNegativeMoney | None = Field(default=None, ge=0.01, le=0.99)
    outcomes_create: list[MarketOutcomeCreate] | None = None

    @field_validator("image_url")
    @classmethod
    def _image_url_must_be_a_url(cls, v: str | None) -> str | None:
        """Reject anything that is not an http(s) URL.

        This is rendered as an `<img src>`, so the value is attacker-controlled
        and reaches a browser. Scheme-checking it here is the difference between
        an image and a `javascript:` URL or a `data:` payload — and it fails the
        submission with a clear message instead of silently rendering nothing.
        """
        if v is None:
            return None
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("image_url must be an absolute http:// or https:// URL")
        return v


class MarketListResponse(BaseModel):
    success: bool = True
    data: list[MarketResponse]
    page: int
    page_size: int
    has_more: bool


class ResolveMarketRequest(BaseModel):
    winning_outcome_id: str = Field(..., max_length=64)
