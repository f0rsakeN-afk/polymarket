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
    UniqueConstraint,
    func,
    literal_column,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

# ── Market lifecycle statuses ────────────────────────────────────────────────────
# `markets.status` is a plain VARCHAR with no DB check constraint, so these
# values are a contract enforced by the API/service layer.
STATUS_ACTIVE = "active"            # live and tradable
STATUS_CLOSED = "closed"            # no new orders, awaiting resolution
STATUS_RESOLVING = "resolving"      # resolution proposed, in dispute window
STATUS_RESOLVED = "resolved"        # final
STATUS_DISPUTE_WINDOW = "dispute_window"
STATUS_PENDING_REVIEW = "pending_review"  # submitted by a regular user, not yet approved
STATUS_REJECTED = "rejected"              # admin declined the submission

# Visible in the public catalogue (and therefore in GET /markets/ without a status filter).
PUBLIC_STATUSES = (
    STATUS_ACTIVE,
    STATUS_CLOSED,
    STATUS_RESOLVING,
    STATUS_RESOLVED,
    STATUS_DISPUTE_WINDOW,
)
# Hidden from the public catalogue until an admin approves (pending) or the
# admin rejects it. Only the creator and admins can read these markets.
UNPUBLISHED_STATUSES = (STATUS_PENDING_REVIEW, STATUS_REJECTED)


class Market(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "markets"

    slug = Column(String(255), unique=True, nullable=False, index=True)
    question = Column(String(1000), nullable=False)
    description = Column(String(5000))
    category = Column(String(100), index=True)
    subcategory = Column(String(100))
    image_url = Column(String(500))

    # Creator (admin or system)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Resolution
    status = Column(String(20), default=STATUS_ACTIVE, nullable=False, index=True)
    # status: see STATUS_* above — active, closed, resolving, resolved,
    # dispute_window, pending_review, rejected
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolution_criteria = Column(String(2000))
    resolution_source = Column(String(1000))  # URL or data feed for resolution
    winning_outcome_id = Column(UUID(as_uuid=True), nullable=True)

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

    # Constraints and indexes — declared after the columns so the full-text
    # expression index can reference `question` directly.
    __table_args__ = (
        CheckConstraint("total_liquidity >= 0", name="ck_markets_liquidity_nonneg"),
        CheckConstraint("total_volume >= 0", name="ck_markets_volume_nonneg"),
        Index("ix_markets_status_closes_at", "status", "closes_at"),
        # Full-text search index backing `list_markets`:
        #     plainto_tsquery('english', q) @@ to_tsvector('english', question)
        # PostgreSQL has no default GIN opclass for varchar/text, so a plain
        # GIN index on `question` cannot be created — the index must be on the
        # exact same to_tsvector() expression the query uses ('english' as a
        # literal, not a bind param, so the planner can match it).
        Index(
            "ix_markets_question_fts",
            func.to_tsvector(literal_column("'english'"), question),
            postgresql_using="gin",
        ),
    )


class Outcome(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "outcomes"
    __table_args__ = (
        CheckConstraint("outcome_index >= 0"),
        Index("ix_outcomes_market_id", "market_id"),
        UniqueConstraint("market_id", "outcome_index", name="uq_outcome_market_index"),
    )

    market_id = Column(UUID(as_uuid=True), ForeignKey("markets.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    outcome_index = Column(Integer, nullable=False)  # 0 = YES, 1 = NO for binary
    image_url = Column(String(500))

    market = relationship("Market", back_populates="outcomes")
    orders = relationship("Order", back_populates="outcome")
    positions = relationship("Position", back_populates="outcome")
