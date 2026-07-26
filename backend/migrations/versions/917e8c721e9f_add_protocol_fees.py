"""add protocol_fees to liquidity_pools and is_system to users

Revision ID: 917e8c721e9f
Revises: 83ff3dfd8ae2
Create Date: 2026-07-25 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '917e8c721e9f'
down_revision: Union[str, None] = '83ff3dfd8ae2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('liquidity_pools', sa.Column('protocol_fees', sa.Numeric(20, 8), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('is_system', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('users', 'is_system')
    op.drop_column('liquidity_pools', 'protocol_fees')
