"""Add user_id to trades"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "2024_add_user_id_to_trades"
down_revision = "2024_extend_trades_outcome"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trades", sa.Column("user_id", postgresql.UUID(), nullable=False, server_default=sa.text("'00000000-0000-0000-0000-000000000000'")))


def downgrade() -> None:
    op.drop_column("trades", "user_id")
