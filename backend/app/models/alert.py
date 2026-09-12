from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Alert(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "alerts"
    __table_args__ = (
        # Covers the fallback scan (market_id + pending) and per-user listing.
        Index("ix_alerts_market_pending", "market_id", postgresql_where=text("triggered = false")),
        Index("ix_alerts_user_pending", "user_id", postgresql_where=text("triggered = false")),
    )

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    market_id = Column(UUID(as_uuid=True), ForeignKey("markets.id", ondelete="CASCADE"), nullable=False)
    outcome = Column(String(10), nullable=True)  # "yes", "no", or null for either
    condition = Column(String(10), nullable=False)  # "above" or "below"
    trigger_price = Column(Numeric(10, 8), nullable=False)
    triggered = Column(Boolean, default=False, nullable=False)
    triggered_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User")
    market = relationship("Market")
