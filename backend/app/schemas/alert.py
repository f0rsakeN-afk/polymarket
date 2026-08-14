from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_serializer


class AlertCreate(BaseModel):
    market_id: str
    outcome: str | None = None  # "yes", "no", or None for either
    condition: str = Field(..., pattern="^(above|below)$")
    trigger_price: float = Field(..., gt=0, lt=1)


class AlertResponse(BaseModel):
    id: str | UUID
    market_id: str | UUID
    outcome: str | None
    condition: str
    trigger_price: float
    triggered: bool
    triggered_at: datetime | None

    @field_serializer("id", "market_id")
    def serialize_uuid(self, v: str | UUID) -> str:
        return str(v)

    @field_serializer("triggered_at")
    def serialize_datetime(self, v: datetime | None) -> str | None:
        return v.isoformat() if v else None

    model_config = {"from_attributes": True}
