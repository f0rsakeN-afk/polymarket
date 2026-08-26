"""Add settled_at to positions

Revision ID: 2026_add_settled_at_to_positions
Revises:
Create Date: 2026-08-26
"""

from alembic import op
import sqlalchemy as sa


revision = "2026_add_settled_at_to_positions"
down_revision = "c9ed218f2a1c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("positions", sa.Column("settled_at", sa.Numeric(20, 8), nullable=True))


def downgrade() -> None:
    op.drop_column("positions", "settled_at")
