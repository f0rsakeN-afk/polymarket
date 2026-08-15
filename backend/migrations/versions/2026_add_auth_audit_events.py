"""Add auth_audit_events table.

Revision ID: 2026_add_auth_audit_events
Revises: 2026_add_2fa_fields_to_users
Create Date: 2026-08-03
"""
from alembic import op
import sqlalchemy as sa

revision = "2026_add_auth_audit_events"
down_revision = "2026_add_2fa_fields_to_users"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auth_audit_events",
        sa.Column("id", sa.dialects.postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.dialects.postgresql.UUID(), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("metadata", sa.Text(), nullable=True),
        sa.Column("success", sa.String(10), nullable=False),
        sa.Column("failure_reason", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_auth_audit_user_event", "auth_audit_events", ["user_id", "event"])
    op.create_index("ix_auth_audit_email_event", "auth_audit_events", ["email", "event"])
    op.create_index("ix_auth_audit_created_at", "auth_audit_events", ["created_at"])


def downgrade():
    op.drop_table("auth_audit_events")
