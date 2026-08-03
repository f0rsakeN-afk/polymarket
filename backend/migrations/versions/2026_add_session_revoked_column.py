"""Add revoked column to sessions table.

Revision ID: 2026_add_session_revoked_column
Revises: 2026_add_auth_audit_events
Create Date: 2026-08-03
"""
from alembic import op
import sqlalchemy as sa

revision = "2026_add_session_revoked_column"
down_revision = "2026_add_auth_audit_events"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sessions", sa.Column("revoked", sa.Boolean, nullable=False, server_default="false"))


def downgrade():
    op.drop_column("sessions", "revoked")
