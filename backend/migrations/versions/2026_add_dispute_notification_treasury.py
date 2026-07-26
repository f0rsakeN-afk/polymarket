"""Add dispute, notification, treasury models + dispute fields on market

Revision ID: 2026_add_dispute_notification_treasury
Revises: 2026_add_performance_indexes
Create Date: 2026-07-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "2026_add_dispute_notification_treasury"
down_revision: Union[str, None] = "2026_add_performance_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Disputes
    op.create_table(
        "disputes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("market_id", UUID(as_uuid=True), sa.ForeignKey("markets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("evidence_url", sa.String(1000), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Notification preferences
    op.create_table(
        "notification_preferences",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("email_alerts", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("email_order_fills", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("email_market_resolution", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("email_weekly_digest", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("push_alerts", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("push_order_fills", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("push_market_resolution", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Notifications
    op.create_table(
        "notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("type", sa.String(50), nullable=False, index=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True, server_default="{}"),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("channel", sa.String(20), nullable=False, server_default="in_app"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Treasury
    op.create_table(
        "treasury",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("balance", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("total_fees_collected", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("total_fees_distributed", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("balance >= 0"),
    )

    # Treasury logs
    op.create_table(
        "treasury_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("treasury_id", UUID(as_uuid=True), sa.ForeignKey("treasury.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event", sa.String(50), nullable=False, index=True),
        sa.Column("amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("reference_type", sa.String(50), nullable=True),
        sa.Column("reference_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Market dispute columns
    op.add_column("markets", sa.Column("resolution_source", sa.String(1000), nullable=True))
    op.add_column("markets", sa.Column("proposed_outcome_id", UUID(as_uuid=True), nullable=True))
    op.add_column("markets", sa.Column("dispute_deadline", sa.DateTime(timezone=True), nullable=True))
    op.add_column("markets", sa.Column("resolution_proposed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("markets", "resolution_proposed_at")
    op.drop_column("markets", "dispute_deadline")
    op.drop_column("markets", "proposed_outcome_id")
    op.drop_column("markets", "resolution_source")
    op.drop_table("treasury_logs")
    op.drop_table("treasury")
    op.drop_table("notifications")
    op.drop_table("notification_preferences")
    op.drop_table("disputes")
