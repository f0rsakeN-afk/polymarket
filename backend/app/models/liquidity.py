from decimal import Decimal

from sqlalchemy import Column, ForeignKey, Index, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


def _decimal(value) -> Decimal:
    """Coerce to Decimal without float binary noise (Decimal(str(x)) for floats)."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


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

    # ── Escrow ledger ─────────────────────────────────────────────────────
    # `collateral` is the pool's USDC escrow: the single source of truth for
    # how much money this pool can pay out. `protocol_fees` is a *sub-ledger
    # inside it* — dollars recorded as owed to the treasury, not extra money.
    #
    # Invariant (asserted by tests/test_ledger.py):
    #     sum of user claims the pool owes  <=  collateral  (+ fees recorded)
    # Every wallet credit funded by the pool MUST go through debit_collateral
    # and every wallet credit INTO the pool MUST go through credit_collateral.
    # That makes the system single-entry at the pool boundary: dollars are
    # never conjured at settlement, on AMM sells, on merges or on LP exits.

    def credit_collateral(self, amount) -> Decimal:
        """Move USDC *into* the escrow (AMM buy, split, book-fee withhold, deposit).

        Returns the amount credited. Rejects negatives — money only ever
        enters through an explicit debit of a wallet elsewhere.
        """
        amount = _decimal(amount)
        if amount < 0:
            raise ValueError(f"credit_collateral requires a non-negative amount, got {amount}")
        self.collateral = _decimal(self.collateral or 0) + amount
        return amount

    def debit_collateral(self, amount, *, allow_shortfall: bool = False) -> Decimal:
        """Move USDC *out* of the escrow (AMM sell, merge, LP exit, fee sweep,
        settlement payouts). Returns the amount actually removed.

        `collateral` is never driven below zero: the escrow is a hard bound on
        what the pool can pay. Trading paths use the default strict mode — a
        shortfall raises (and therefore rolls the trade back) because it means
        the ledger is broken. Settlers pass allow_shortfall=True so a shortfall
        degrades to a partial payment plus a loud log instead of leaving a
        market un-settleable or minting money.
        """
        amount = _decimal(amount)
        if amount <= 0:
            return Decimal(0)
        available = _decimal(self.collateral or 0)
        if amount > available:
            if not allow_shortfall:
                raise ValueError(
                    f"pool {self.id}: collateral shortfall — owe {amount}, hold {available}"
                )
            amount = available
        self.collateral = available - amount
        return amount


class LPShare(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "lp_shares"
    __table_args__ = (UniqueConstraint("pool_id", "user_id"),)

    pool_id = Column(UUID(as_uuid=True), ForeignKey("liquidity_pools.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    lp_tokens = Column(Numeric(20, 8), default=0, nullable=False)
    collateral_deposited = Column(Numeric(20, 8), default=0, nullable=False)

    pool = relationship("LiquidityPool", back_populates="lp_shares")
    user = relationship("User")
