from decimal import Decimal

from sqlalchemy import Column, ForeignKey, Index, Numeric, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class EscrowShortfallError(RuntimeError):
    """The pool escrow cannot fund a payout it is obligated to make.

    This is an *invariant violation*, never a normal condition: every inflow
    credits the escrow and every outflow debits it, so an obligation larger
    than the balance means money was created or destroyed somewhere upstream.

    Raised rather than absorbed on purpose. A caller that catches it and pays
    a partial amount has silently converted "owed $100" into "paid $60, owed
    nothing" • the remainder is unreachable, because nothing records it as
    still owed and nothing retries it. Failing the transaction keeps the
    obligation intact and leaves it claimable.
    """


def _decimal(value) -> Decimal:
    """Coerce to Decimal without float binary noise (Decimal(str(x)) for floats)."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


class LiquidityPool(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "liquidity_pools"
    __table_args__ = (
        Index("ix_liquidity_pools_market_id", "market_id"),
        # One row per (market, outcome). outcome_id is NULL for the binary pool.
        Index("ix_liquidity_pools_market_outcome", "market_id", "outcome_id", unique=True),
        # Exactly one binary pool per market. A plain UNIQUE(market_id) cannot
        # express this: NULLs do not conflict in Postgres, so without this a
        # second binary pool for the same market would be insertable and every
        # `scalar_one_or_none()` pool lookup would raise MultipleResultsFound.
        Index(
            "uq_liquidity_pools_market_binary",
            "market_id",
            unique=True,
            postgresql_where=text("outcome_id IS NULL"),
        ),
    )

    market_id = Column(
        UUID(as_uuid=True), ForeignKey("markets.id", ondelete="CASCADE"), nullable=False
    )
    # NULL = the market's single binary pool (2 outcomes: Yes/No).
    # Set    = this outcome's parimutuel pool (3+ mutually exclusive outcomes).
    #
    # Parimutuel pricing: price_i = shares_i / SUM(shares over the market's
    # outcome pools), so the outcome prices sum to 1 and buying one outcome
    # raises its price while lowering the others. BinaryAMM is reused unchanged,
    # constructed per outcome with yes_shares=shares_i and
    # no_shares=total-shares_i.
    outcome_id = Column(
        UUID(as_uuid=True), ForeignKey("outcomes.id", ondelete="CASCADE"), nullable=True
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
    # inside it* • dollars recorded as owed to the treasury, not extra money.
    #
    # Invariant (asserted by tests/test_ledger.py):
    #     sum of user claims the pool owes  <=  collateral  (+ fees recorded)
    # Every wallet credit funded by the pool MUST go through debit_collateral
    # and every wallet credit INTO the pool MUST go through credit_collateral.
    # That makes the system single-entry at the pool boundary: dollars are
    # never conjured at settlement, on AMM sells, on merges or on LP exits.

    def credit_collateral(self, amount) -> Decimal:
        """Move USDC *into* the escrow (AMM buy, split, book-fee withhold, deposit).

        Returns the amount credited. Rejects negatives • money only ever
        enters through an explicit debit of a wallet elsewhere.
        """
        amount = _decimal(amount)
        if amount < 0:
            raise ValueError(f"credit_collateral requires a non-negative amount, got {amount}")
        self.collateral = _decimal(self.collateral or 0) + amount
        return amount

    def debit_collateral(self, amount) -> Decimal:
        """Move USDC *out* of the escrow (AMM sell, merge, LP exit, fee sweep,
        settlement payouts). Returns the amount actually removed.

        There is deliberately no "pay what you can" mode. A caller that debits
        less than it is about to record as paid destroys the difference: nothing
        marks it unpaid and nothing retries it. An obligation smaller than the
        balance is the only case worth supporting, and it is expressed by the
        caller computing `min(owed, available)` *before* calling this • so the
        unpaid remainder stays visible in whatever ledger the caller owns.

        `collateral` is never driven below zero. Too little money raises
        `EscrowShortfallError`, and because callers do this inside their own
        transaction the whole operation rolls back with nothing marked done.
        """
        amount = _decimal(amount)
        if amount <= 0:
            return Decimal(0)
        available = _decimal(self.collateral or 0)
        if amount > available:
            raise EscrowShortfallError(
                f"pool {self.id}: collateral shortfall • owe {amount}, hold {available}"
            )
        self.collateral = available - amount
        return amount

    def can_cover(self, amount) -> bool:
        """True if the escrow can fund `amount` in full. A read-only probe •
        callers that need to branch on it must not debit in the same breath."""
        return _decimal(amount) <= _decimal(self.collateral or 0)


class LPShare(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "lp_shares"
    __table_args__ = (UniqueConstraint("pool_id", "user_id"),)

    pool_id = Column(UUID(as_uuid=True), ForeignKey("liquidity_pools.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    lp_tokens = Column(Numeric(20, 8), default=0, nullable=False)
    collateral_deposited = Column(Numeric(20, 8), default=0, nullable=False)

    pool = relationship("LiquidityPool", back_populates="lp_shares")
    user = relationship("User")
