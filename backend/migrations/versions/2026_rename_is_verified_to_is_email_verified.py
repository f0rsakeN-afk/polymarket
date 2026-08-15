"""Rename is_verified to is_email_verified on users table.

Revision ID: 2026_rename_is_verified_to_is_email_verified
Revises:
Create Date: 2026-08-03
"""
from alembic import op

revision = "2026_rename_is_verified_to_is_email_verified"
down_revision = "5db9e3f360f7"  # current DB head
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE users RENAME COLUMN is_verified TO is_email_verified")


def downgrade():
    op.execute("ALTER TABLE users RENAME COLUMN is_email_verified TO is_verified")
