"""add trades table

Revision ID: 3da7b1990350
Revises: eb92b1990350
Create Date: 2026-07-25 12:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '3da7b1990350'
down_revision: Union[str, None] = 'eb92b1990350'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'trades',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('market_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('outcome', sa.String(10), nullable=False),
        sa.Column('side', sa.String(10), nullable=False),
        sa.Column('price', sa.Numeric(10, 8), nullable=False),
        sa.Column('amount', sa.Numeric(20, 8), nullable=False),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['market_id'], ['markets.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_trades_market_executed', 'trades', ['market_id', 'executed_at'])
    op.create_index('ix_trades_executed', 'trades', ['executed_at'])


def downgrade() -> None:
    op.drop_index('ix_trades_executed')
    op.drop_index('ix_trades_market_executed')
    op.drop_table('trades')
