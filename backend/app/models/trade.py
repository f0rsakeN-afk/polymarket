from app.models.base import Base, UUIDMixin
from sqlalchemy import Column, String, Numeric, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime, timezone


class Trade(Base, UUIDMixin):
    __tablename__ = "trades"

    market_id = Column(UUID(as_uuid=True), ForeignKey("markets.id", ondelete="CASCADE"), nullable=False)
    outcome = Column(String(10), nullable=False)
    side = Column(String(10), nullable=False)
    price = Column(Numeric(10, 8), nullable=False)
    amount = Column(Numeric(20, 8), nullable=False)
    executed_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    market = relationship("Market", back_populates="trades")
