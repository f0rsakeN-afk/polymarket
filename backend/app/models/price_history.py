from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Numeric
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, UUIDMixin


class PriceHistory(Base, UUIDMixin):
    __tablename__ = "price_history"

    market_id = Column(UUID(as_uuid=True), ForeignKey("markets.id", ondelete="CASCADE"), nullable=False)
    outcome_id = Column(UUID(as_uuid=True), ForeignKey("outcomes.id", ondelete="CASCADE"), nullable=False)
    price = Column(Numeric(10, 6), nullable=False)
    total_volume = Column(Numeric(20, 8), default=0)
    snapshot_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    __table_args__ = (
        Index("ix_price_history_outcome_snapshot", "outcome_id", "snapshot_at"),
        Index("ix_price_history_market_snapshot", "market_id", "snapshot_at"),
    )
