"""`refresh_tokens.device_info` — the user agent the token was issued to.

## Why

`POST /auth/refresh` binds a token to the device it was created on: a token
presented from a different user agent is replay, not refresh, and inside the
reuse-grace window the same comparison is what tells a duplicate from theft.
Both checks read `RefreshToken.device_info`, but the model and the schema never
carried the column — so `RefreshToken(device_info=...)` raised
TypeError at login and every refresh fell over with it.

## Nullable, so no backfill

Existing rows were issued before the binding existed; a NULL stored user agent
would compare unequal to any presented one and log everyone out on upgrade.
Instead the check treats NULL conservatively: the equality test reads both
sides through `or ""`, and the issue path stamps new rows from today.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d7e5f3a8b916"
down_revision: Union[str, None] = "c8d4e2f7a915"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "refresh_tokens",
        sa.Column("device_info", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("refresh_tokens", "device_info")
