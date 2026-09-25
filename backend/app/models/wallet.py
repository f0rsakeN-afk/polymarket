from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Wallet(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "wallets"
    __table_args__ = (
        UniqueConstraint("user_id", "currency"),
        CheckConstraint("balance >= 0", name="ck_wallets_balance_nonneg"),
        CheckConstraint("locked_balance >= 0", name="ck_wallets_locked_nonneg"),
        CheckConstraint("locked_balance <= balance", name="ck_wallets_locked_lte_balance"),
    )

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    balance = Column(Numeric(20, 8), default=0, nullable=False)
    locked_balance = Column(Numeric(20, 8), default=0, nullable=False)
    currency = Column(String(20), default="USDC", nullable=False)

    user = relationship("User")
    transactions = relationship("Transaction", back_populates="wallet", cascade="all, delete-orphan")


class Transaction(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_user_id", "user_id"),
        Index("ix_transactions_user_created", "user_id", "created_at"),
        Index("ix_transactions_wallet_id", "wallet_id"),
        # Idempotency guards (partial unique indexes — NULL reference_ids ignored):
        # - one withdrawal per idempotency key (concurrent double-submit safe)
        # - one deposit per Stripe payment_intent_id (webhook double-delivery safe)
        Index(
            "uq_transactions_withdrawal_ref",
            "reference_id",
            unique=True,
            postgresql_where=text("type = 'withdrawal' AND reference_id IS NOT NULL"),
        ),
        Index(
            "uq_transactions_deposit_ref",
            "reference_id",
            unique=True,
            postgresql_where=text("type = 'deposit' AND reference_id IS NOT NULL"),
        ),
    )

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
    # blockchain_tx_hash is populated when the on-chain transaction is broadcast.
    # Used to track withdrawal confirmation status on the blockchain.
    blockchain_tx_hash = Column(String(66), nullable=True, index=True)  # 0x-prefixed 64-char hash
    confirmations = Column(Integer, default=0, nullable=False)  # number of blockchain confirmations
    extra_data = Column(JSONB, default={})

    wallet = relationship("Wallet", back_populates="transactions")
