import uuid
from sqlalchemy import Column, Numeric, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, UUIDMixin, TimestampMixin


class Position(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("user_id", "market_id", "outcome_id"),
        Index("ix_positions_user_id", "user_id"),
        Index("ix_positions_created_at", "created_at"),
        Index("ix_positions_user_market", "user_id", "market_id"),
    )

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    market_id = Column(UUID(as_uuid=True), ForeignKey("markets.id", ondelete="CASCADE"), nullable=False)
    outcome_id = Column(UUID(as_uuid=True), ForeignKey("outcomes.id", ondelete="CASCADE"), nullable=False)

    shares_held = Column(Numeric(20, 8), default=0, nullable=False)
    average_price = Column(Numeric(10, 6), default=0, nullable=False)  # avg cost basis
    realized_pnl = Column(Numeric(20, 8), default=0, nullable=False)

    user = relationship("User")
    market = relationship("Market", back_populates="positions")
    outcome = relationship("Outcome", back_populates="positions")
