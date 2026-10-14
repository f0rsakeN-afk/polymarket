"""user erasure tombstone

Revision ID: c4d9e2f17a83
Revises: b7c1e4a92d10
Create Date: 2026-10-14 10:12:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d9e2f17a83"
down_revision: Union[str, None] = "b7c1e4a92d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A deleted account is a tombstone row, not a removed one: nearly every table
    # referencing a user cascades on delete, so removing the row would take the
    # public trade tape, settled positions and the transaction ledger with it.
    op.add_column(
        "users",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            # server_default, not just a Python default: on a table that already
            # holds real accounts, adding a NOT NULL column with no default
            # fails outright rather than backfilling. Every existing row is, by
            # definition, not deleted.
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Indexed because "is this address still an account" is now a question the
    # login and email paths ask on every attempt.
    op.create_index("ix_users_is_deleted", "users", ["is_deleted"])


def downgrade() -> None:
    # Drops the index first - the column drop takes it with it otherwise, but
    # naming it keeps the reverse path readable.
    op.drop_index("ix_users_is_deleted", table_name="users")
    op.drop_column("users", "deleted_at")
    op.drop_column("users", "is_deleted")