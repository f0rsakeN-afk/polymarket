"""Extend trades.outcome column to varchar(100) for multi-outcome markets"""
from alembic import op
import sqlalchemy as sa

revision = "2024_extend_trades_outcome"
down_revision = "83ff3dfd8ae2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("trades", "outcome", type_=sa.String(100))


def downgrade() -> None:
    op.alter_column("trades", "outcome", type_=sa.String(10))
