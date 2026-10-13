"""admin audit events

Revision ID: b7c1e4a92d10
Revises: 2d546069962c
Create Date: 2026-10-13 23:41:07.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b7c1e4a92d10"
down_revision: Union[str, None] = "2d546069962c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="SET NULL: deleting an admin must not delete the record that they acted",
        ),
        sa.Column("actor_email", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("success", sa.String(length=10), nullable=False, server_default="success"),
        sa.Column("failure_reason", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_admin_audit_events_actor_id", "admin_audit_events", ["actor_id"])
    op.create_index("ix_admin_audit_events_actor_email", "admin_audit_events", ["actor_email"])
    op.create_index("ix_admin_audit_events_action", "admin_audit_events", ["action"])
    op.create_index("ix_admin_audit_events_target_type", "admin_audit_events", ["target_type"])
    op.create_index("ix_admin_audit_events_target_id", "admin_audit_events", ["target_id"])
    op.create_index("ix_admin_audit_events_ip_address", "admin_audit_events", ["ip_address"])
    op.create_index("ix_admin_audit_actor_created", "admin_audit_events", ["actor_id", "created_at"])
    op.create_index("ix_admin_audit_action_created", "admin_audit_events", ["action", "created_at"])
    op.create_index("ix_admin_audit_target", "admin_audit_events", ["target_type", "target_id"])


def downgrade() -> None:
    # Drops the table and its indexes with it. Nothing else references it, and the
    # audit trail is not something a downgrade should try to preserve in place.
    op.drop_table("admin_audit_events")