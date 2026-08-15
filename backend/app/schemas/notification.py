from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationPreferenceResponse(BaseModel):
    email_alerts: bool
    email_order_fills: bool
    email_market_resolution: bool
    email_weekly_digest: bool
    push_alerts: bool
    push_order_fills: bool
    push_market_resolution: bool


class UpdateNotificationPreferencesRequest(BaseModel):
    email_alerts: bool | None = None
    email_order_fills: bool | None = None
    email_market_resolution: bool | None = None
    email_weekly_digest: bool | None = None
    push_alerts: bool | None = None
    push_order_fills: bool | None = None
    push_market_resolution: bool | None = None


class NotificationResponse(BaseModel):
    id: str
    type: str
    title: str
    body: str | None = None
    data: dict | None = None
    read_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
