"""A ban says why.

`users.ban_reason` and `users.banned_at` — nullable, so existing rows are
untouched and no backfill is needed. Both are null whenever `is_active` is true.

The actor is deliberately *not* stored here: the admin audit trail already
records who did it, with IP and user agent, and two places holding "who banned
this" is two places to disagree.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f1c2d3e4a5b6"
down_revision: Union[str, None] = "e91b7d4c6a02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("ban_reason", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column("banned_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Indexed because "who is banned and when" is a query an admin runs, and
    # "most recent bans first" is the one they run it as.
    op.create_index("ix_users_banned_at", "users", ["banned_at"])


def downgrade() -> None:
    op.drop_index("ix_users_banned_at", table_name="users")
    op.drop_column("users", "banned_at")
    op.drop_column("users", "ban_reason")
