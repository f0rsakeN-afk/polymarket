"""add blockchain tx fields and treasury singleton

Revision ID: 0ccfc38683a8
Revises: 9b4f2a71c3d8
Create Date: 2026-10-02 18:36:48.256177

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0ccfc38683a8'
down_revision: Union[str, None] = '9b4f2a71c3d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server defaults so the ALTER works on non-empty tables; the ORM supplies
    # the same values on insert.
    op.add_column('transactions', sa.Column('blockchain_tx_hash', sa.String(length=66), nullable=True))
    op.add_column('transactions', sa.Column('confirmations', sa.Integer(), nullable=False, server_default='0'))
    op.create_index(op.f('ix_transactions_blockchain_tx_hash'), 'transactions', ['blockchain_tx_hash'], unique=False)
    op.add_column('treasury', sa.Column('singleton', sa.Boolean(), nullable=False, server_default='true'))
    op.create_unique_constraint('uq_treasury_singleton', 'treasury', ['singleton'])
    op.create_check_constraint('ck_treasury_singleton_true', 'treasury', 'singleton = true')
    # set explicitly to match the ORM default (server_default is only for the ALTER)
    op.alter_column('treasury', 'singleton', server_default=None)


def downgrade() -> None:
    op.drop_constraint('ck_treasury_singleton_true', 'treasury', type_='check')
    op.drop_constraint('uq_treasury_singleton', 'treasury', type_='unique')
    op.drop_column('treasury', 'singleton')
    op.drop_index(op.f('ix_transactions_blockchain_tx_hash'), table_name='transactions')
    op.drop_column('transactions', 'confirmations')
    op.drop_column('transactions', 'blockchain_tx_hash')
