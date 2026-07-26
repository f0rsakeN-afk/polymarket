"""Extend trades.outcome column to varchar(100) for multi-outcome markets"""
from alembic import op

revision = "2024_extend_trades_outcome"
down_revision = "83ff3dfd8ae2_merge_comments_trades_referrals_with_is_"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("trades", "outcome", existing_type=op.sqlalchemy.Column("outcome", op.sqlalchemy.String(length=10)), new_type_op=op.sqlalchemy.String(length=100))


def downgrade() -> None:
    op.alter_column("trades", "outcome", new_type_op=op.sqlalchemy.String(length=10))
