"""A rejection says why.

`markets.rejection_reason` and `markets.rejected_at` — nullable, so existing rows
are untouched and no backfill is needed. Both are null unless `status` is
`rejected`.

The reason lives on the market because the author keeps read access to their own
submission: it is the only channel through which they can learn why it was
declined. The actor is deliberately *not* stored here — the admin audit trail
already records who did it, with IP and user agent, and two places holding
"who rejected this" is two places to disagree.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b2e4c7a9d310"
down_revision: Union[str, None] = "f1c2d3e4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "markets", sa.Column("rejection_reason", sa.String(length=1000), nullable=True)
    )
    op.add_column(
        "markets",
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("markets", "rejected_at")
    op.drop_column("markets", "rejection_reason")