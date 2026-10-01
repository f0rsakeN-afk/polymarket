from pydantic import BaseModel, Field

from app.schemas.base import PositiveMoney


class SplitMergeRequest(BaseModel):
    """Body for POST /split-merge/split and POST /split-merge/merge.

    Both endpoints take a JSON body (like the liquidity endpoints) rather
    than query parameters — the amounts are Decimal money values and must
    not travel in the query string.
    """

    market_id: str = Field(..., max_length=64)
    amount: PositiveMoney
