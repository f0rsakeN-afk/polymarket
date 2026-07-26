"""Add alerts and market_flags tables

Revision ID: 5db9e3f360f7
Revises: 2026_add_dispute_notification_treasury
Create Date: 2026-07-26 23:29:55.118963
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = '5db9e3f360f7'
down_revision: Union[str, None] = '2026_add_dispute_notification_treasury'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Alerts table
    op.create_table(
        'alerts',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('market_id', UUID(as_uuid=True), sa.ForeignKey('markets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('outcome', sa.String(10), nullable=True),
        sa.Column('condition', sa.String(10), nullable=False),
        sa.Column('trigger_price', sa.Float, nullable=False),
        sa.Column('triggered', sa.Boolean, default=False, nullable=False),
        sa.Column('triggered_at', sa.String, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Market flags table
    op.create_table(
        'market_flags',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('market_id', UUID(as_uuid=True), sa.ForeignKey('markets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('reason', sa.Text, nullable=False),
        sa.Column('status', sa.String(20), default='open', nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('alerts')
    op.drop_table('market_flags')
