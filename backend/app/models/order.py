from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Order(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("amount > 0"),
        CheckConstraint("price >= 0"),
        CheckConstraint("price <= 1"),
        UniqueConstraint("user_id", "client_order_id", name="uq_orders_user_client_order"),
        Index("ix_orders_user_created", "user_id", "created_at"),
        Index("ix_orders_market_status", "market_id", "status"),
        Index("ix_orders_market_status_type", "market_id", "status", "order_type"),
    )

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    market_id = Column(UUID(as_uuid=True), ForeignKey("markets.id", ondelete="CASCADE"), nullable=False)
    outcome_id = Column(UUID(as_uuid=True), ForeignKey("outcomes.id", ondelete="CASCADE"), nullable=False)

    # Order spec
    side = Column(String(10), nullable=False)  # buy, sell
    order_type = Column(String(20), nullable=False)  # market, limit, fill_or_kill
    amount = Column(Numeric(20, 8), nullable=False)  # quantity of shares
    price = Column(Numeric(10, 6), nullable=False)  # price per share (0-1)

    # Limit order tracking
    remaining_amount = Column(Numeric(20, 8), nullable=True)
    status = Column(
        String(20), default="pending", nullable=False, index=True
    )  # pending, partial, filled, cancelled, expired
    expires_at = Column(DateTime(timezone=True), nullable=True)

    # Execution results
    shares_bought = Column(Numeric(20, 8), nullable=True)
    shares_sold = Column(Numeric(20, 8), nullable=True)
    fees_paid = Column(Numeric(20, 8), nullable=True)
    slippage = Column(Numeric(10, 6), nullable=True)
    executed_at = Column(DateTime(timezone=True), nullable=True)

    # Idempotency
    client_order_id = Column(String(100), nullable=True, index=True)

    # Relations
    user = relationship("User")
    market = relationship("Market", back_populates="orders")
    outcome = relationship("Outcome", back_populates="orders")
