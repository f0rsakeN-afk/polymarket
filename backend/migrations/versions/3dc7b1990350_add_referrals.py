"""add referrals table and user referral_code

Revision ID: 3dc7b1990350
Revises: 3da7b1990350
Create Date: 2026-07-25 12:02:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '3dc7b1990350'
down_revision: Union[str, None] = '3da7b1990350'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('referral_code', sa.String(32), nullable=True))
    op.create_index('ix_users_referral_code', 'users', ['referral_code'], unique=True)

    op.create_table(
        'referrals',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('referrer_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('referred_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('referral_code', sa.String(32), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('reward_amount', sa.Numeric(20, 8), nullable=False, server_default='0'),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['referrer_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['referred_id'], ['users.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_referrals_referral_code', 'referrals', ['referral_code'])


def downgrade() -> None:
    op.drop_index('ix_referrals_referral_code')
    op.drop_table('referrals')
    op.drop_index('ix_users_referral_code')
    op.drop_column('users', 'referral_code')
