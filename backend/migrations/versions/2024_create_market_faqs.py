"""Add market_faqs table

Revision ID: 2024_add_market_faqs
Revises: c1794894c63a
Create Date: 2024-07-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2024_add_market_faqs'
down_revision: Union[str, None] = 'c1794894c63a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'market_faqs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('market_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('markets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('answer', sa.Text(), nullable=False),
        sa.Column('display_order', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_market_faqs_market_id', 'market_faqs', ['market_id'])


def downgrade() -> None:
    op.drop_index('ix_market_faqs_market_id', table_name='market_faqs')
    op.drop_table('market_faqs')
