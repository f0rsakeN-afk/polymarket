"""Add price_history table

Revision ID: 2026_add_price_history
Revises: 917e8c721e9f, 2024_add_market_faqs, 2024_add_user_id_to_trades
Create Date: 2026-07-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "2026_add_price_history"
down_revision: Union[str, None] = ("917e8c721e9f", "2024_add_market_faqs", "2024_add_user_id_to_trades")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_index("ix_price_history_market_snapshot")
    op.drop_table("price_history")
