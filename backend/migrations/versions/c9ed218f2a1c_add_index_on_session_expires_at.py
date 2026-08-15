"""Add index on session expires_at

Revision ID: c9ed218f2a1c
Revises: 2026_add_session_revoked_column
Create Date: 2026-08-14 14:37:53.207305
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9ed218f2a1c'
down_revision: Union[str, None] = '2026_add_session_revoked_column'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_sessions_expires_at', 'sessions', ['expires_at'])


def downgrade() -> None:
    op.drop_index('ix_sessions_expires_at', 'sessions')
