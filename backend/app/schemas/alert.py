from pydantic import BaseModel, Field


class AlertCreate(BaseModel):
    market_id: str
    outcome: str | None = None  # "yes", "no", or None for either
    condition: str = Field(..., pattern="^(above|below)$")
    trigger_price: float = Field(..., gt=0, lt=1)


class AlertResponse(BaseModel):
    id: str
    market_id: str
    outcome: str | None
    condition: str
    trigger_price: float
    triggered: bool
    triggered_at: str | None

    model_config = {"from_attributes": True}
