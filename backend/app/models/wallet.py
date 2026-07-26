import uuid
from sqlalchemy import Column, String, Numeric, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base, UUIDMixin, TimestampMixin


class Wallet(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "wallets"
    __table_args__ = (UniqueConstraint("user_id", "currency"),)

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    balance = Column(Numeric(20, 8), default=0, nullable=False)
    locked_balance = Column(Numeric(20, 8), default=0, nullable=False)
    currency = Column(String(20), default="USDC", nullable=False)

    user = relationship("User")
    transactions = relationship("Transaction", back_populates="wallet", cascade="all, delete-orphan")


class Transaction(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "transactions"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    wallet_id = Column(UUID(as_uuid=True), ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False)

    type = Column(
        String(30), nullable=False
    )  # deposit, withdrawal, trade_buy, trade_sell, fee, liquidity_add, liquidity_remove, settlement_win, settlement_loss, refund, split, merge
    amount = Column(Numeric(20, 8), nullable=False)  # positive = credit, negative = debit
    balance_after = Column(Numeric(20, 8), nullable=False)

    reference_id = Column(String(255), nullable=True)
    reference_type = Column(String(50), nullable=True)  # order, withdrawal, liquidity_pool

    status = Column(String(20), default="completed", nullable=False)  # pending, completed, failed
    extra_data = Column(JSONB, default={})

    wallet = relationship("Wallet", back_populates="transactions")
