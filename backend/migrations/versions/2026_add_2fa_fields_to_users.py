"""Add 2FA fields to users table.

Revision ID: 2026_add_2fa_fields_to_users
Revises: 2026_rename_is_verified_to_is_email_verified
Branch labels: None
Depends on: None
Create Date: 2026-08-03
"""
from alembic import op
import sqlalchemy as sa

revision = "2026_add_2fa_fields_to_users"
down_revision = "2026_rename_is_verified_to_is_email_verified"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("totp_secret_encrypted", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("is_2fa_enabled", sa.Boolean, nullable=False, server_default="false"))
    op.add_column("users", sa.Column("is_2fa_pending", sa.Boolean, nullable=False, server_default="false"))


def downgrade():
    op.drop_column("users", "is_2fa_pending")
    op.drop_column("users", "is_2fa_enabled")
    op.drop_column("users", "totp_secret_encrypted")
