from sqlalchemy import Column, ForeignKey, Index, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class LiquidityPool(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "liquidity_pools"
    __table_args__ = (Index("ix_liquidity_pools_market_id", "market_id"),)

    market_id = Column(
        UUID(as_uuid=True), ForeignKey("markets.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    yes_shares = Column(Numeric(20, 8), default=0, nullable=False)
    no_shares = Column(Numeric(20, 8), default=0, nullable=False)
    collateral = Column(Numeric(20, 8), default=0, nullable=False)
    fee_rate = Column(Numeric(5, 4), default=0.02, nullable=False)  # 2%
    lp_token_supply = Column(Numeric(20, 8), default=0, nullable=False)
    protocol_fees = Column(Numeric(20, 8), default=0, nullable=False)  # accumulated protocol fees (1% of trades)

    market = relationship("Market", back_populates="pool")
    lp_shares = relationship("LPShare", back_populates="pool", cascade="all, delete-orphan")


class LPShare(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "lp_shares"
    __table_args__ = (UniqueConstraint("pool_id", "user_id"),)

    pool_id = Column(UUID(as_uuid=True), ForeignKey("liquidity_pools.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    lp_tokens = Column(Numeric(20, 8), default=0, nullable=False)
    collateral_deposited = Column(Numeric(20, 8), default=0, nullable=False)

    pool = relationship("LiquidityPool", back_populates="lp_shares")
    user = relationship("User")
