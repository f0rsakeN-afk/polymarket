from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Market(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "markets"
    __table_args__ = (
        CheckConstraint("total_liquidity >= 0"),
        CheckConstraint("total_volume >= 0"),
    )

    slug = Column(String(255), unique=True, nullable=False, index=True)
    question = Column(String(1000), nullable=False)
    description = Column(String(5000))
    category = Column(String(100), index=True)
    subcategory = Column(String(100))
    image_url = Column(String(500))

    # Creator (admin or system)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Resolution
    status = Column(String(20), default="active", nullable=False, index=True)
    # status: active, closed, resolved, cancelled
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolution_criteria = Column(String(2000))
    resolution_source = Column(String(1000))  # URL or data feed for resolution
    winning_outcome_id = Column(UUID(as_uuid=True), nullable=True)

    # Composite indexes for hot queries
    __table_args__ = (
        Index("ix_markets_status_closes_at", "status", "closes_at"),
    )

    # Dispute window
    proposed_outcome_id = Column(UUID(as_uuid=True), nullable=True)
    dispute_deadline = Column(DateTime(timezone=True), nullable=True)
    resolution_proposed_at = Column(DateTime(timezone=True), nullable=True)

    # Timing
    opens_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    closes_at = Column(DateTime(timezone=True), nullable=False)

    # Stats
    total_liquidity = Column(Numeric(20, 8), default=0, nullable=False)
    total_volume = Column(Numeric(20, 8), default=0, nullable=False)
    num_trades = Column(Integer, default=0, nullable=False)

    # Relations
    outcomes = relationship("Outcome", back_populates="market", cascade="all, delete-orphan")
    pool = relationship("LiquidityPool", back_populates="market", uselist=False, cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="market", cascade="all, delete-orphan")
    positions = relationship("Position", back_populates="market", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="market", cascade="all, delete-orphan")
    trades = relationship("Trade", back_populates="market", cascade="all, delete-orphan")
    faqs = relationship("MarketFAQ", back_populates="market", cascade="all, delete-orphan")
    disputes = relationship("Dispute", back_populates="market", cascade="all, delete-orphan")
    flags = relationship("MarketFlag", back_populates="market", cascade="all, delete-orphan")


class Outcome(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "outcomes"
    __table_args__ = (
        CheckConstraint("outcome_index >= 0"),
        Index("ix_outcomes_market_id", "market_id"),
    )

    market_id = Column(UUID(as_uuid=True), ForeignKey("markets.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    outcome_index = Column(Integer, nullable=False)  # 0 = YES, 1 = NO for binary
    image_url = Column(String(500))

    market = relationship("Market", back_populates="outcomes")
    orders = relationship("Order", back_populates="outcome")
    positions = relationship("Position", back_populates="outcome")
