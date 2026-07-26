"""Fix price_history to be per-outcome

Revision ID: 2026_fix_price_history_per_outcome
Revises: 2026_add_price_history
Create Date: 2026-07-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "1e3a5b7c9d0f"
down_revision: Union[str, None] = "2026_add_price_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("price_history")
    op.create_table(
        "price_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("market_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outcome_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("price", sa.Numeric(10, 6), nullable=False),
        sa.Column("total_volume", sa.Numeric(20, 8), default=0),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["outcome_id"], ["outcomes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_price_history_outcome_snapshot", "price_history", ["outcome_id", "snapshot_at"])
    op.create_index("ix_price_history_market_snapshot", "price_history", ["market_id", "snapshot_at"])


def downgrade() -> None:
    op.drop_table("price_history")
    op.create_table(
        "price_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("market_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("yes_price", sa.Numeric(10, 6), nullable=False),
        sa.Column("no_price", sa.Numeric(10, 6), nullable=False),
        sa.Column("total_volume", sa.Numeric(20, 8), default=0),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_price_history_market_snapshot", "price_history", ["market_id", "snapshot_at"])
