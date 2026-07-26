from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class NotificationPreference(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "notification_preferences"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)

    email_alerts = Column(Boolean, default=True)
    email_order_fills = Column(Boolean, default=True)
    email_market_resolution = Column(Boolean, default=True)
    email_weekly_digest = Column(Boolean, default=False)

    push_alerts = Column(Boolean, default=True)
    push_order_fills = Column(Boolean, default=True)
    push_market_resolution = Column(Boolean, default=True)

    user = relationship("User")


class Notification(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "notifications"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(50), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    body = Column(Text)
    data = Column(JSON, default={})
    read_at = Column(DateTime(timezone=True), nullable=True)
    channel = Column(String(20), default="in_app")  # in_app, email, push

    user = relationship("User")
