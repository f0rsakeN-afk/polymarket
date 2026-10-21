"""`refresh_tokens.revoked_at` — when, not just that.

## Why

The reuse grace window in `POST /auth/refresh` has to tell a *stolen* refresh
token from a *duplicate* one, and the only evidence it has is when the token was
revoked. `revoked` alone is a boolean: it cannot distinguish "revoked a second
ago because another page refreshed" from "revoked a week ago because somebody
stole it", which are opposite events.

## Nullable, so no backfill

Existing rows are untouched. A NULL on an already-revoked token is read as "not
recently revoked" — the conservative direction, so an upgrade cannot widen the
grace window for anything revoked before it.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c8d4e2f7a915"
down_revision: Union[str, None] = "b2e4c7a9d310"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "refresh_tokens",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Queried on every refresh of a revoked token, which is the reuse path.
    op.create_index("ix_refresh_tokens_revoked_at", "refresh_tokens", ["revoked_at"])


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_revoked_at", table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "revoked_at")