"""referrals survive a participant leaving

Revision ID: e91b7d4c6a02
Revises: c4d9e2f17a83
Create Date: 2026-10-14 12:40:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e91b7d4c6a02"
down_revision: Union[str, None] = "c4d9e2f17a83"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = ("referrer_id", "referred_id")

# The initial migration created these constraints unnamed, so PostgreSQL named
# them `referrals_referrer_id_fkey` and friends - a convention, not a guarantee.
# Looking the real name up by column means this migration keeps working whatever
# the database actually called them, instead of failing on a guessed string.
_SET_NULL = """
DO $$
DECLARE
    col text;
    cname text;
BEGIN
    FOREACH col IN ARRAY ARRAY['referrer_id', 'referred_id']
    LOOP
        SELECT con.conname INTO cname
        FROM pg_constraint con
        JOIN pg_attribute att
          ON att.attrelid = con.conrelid AND att.attnum = con.conkey[1]
        WHERE con.conrelid = 'referrals'::regclass
          AND con.contype = 'f'
          AND att.attname = col;

        IF cname IS NOT NULL THEN
            EXECUTE format('ALTER TABLE referrals DROP CONSTRAINT %I', cname);
        END IF;

        EXECUTE format(
            'ALTER TABLE referrals ADD CONSTRAINT %I '
            'FOREIGN KEY (%I) REFERENCES users(id) ON DELETE SET NULL',
            'fk_referrals_' || col, col
        );
    END LOOP;
END $$;
"""


def _rewrite(action: str) -> None:
    """Rebuild both FKs with the given ON DELETE action, whatever they are now."""
    op.execute(
        _SET_NULL.replace("ON DELETE SET NULL", f"ON DELETE {action}")
        .replace("'fk_referrals_' || col", "'referrals_' || col || '_fkey'")
    )


def upgrade() -> None:
    # NOT NULL first: dropping it is independent of the FK, and doing it before
    # the constraint is rebuilt keeps the window where a row could be orphaned
    # under a NOT NULL column impossible.
    for column in _COLUMNS:
        op.alter_column("referrals", column, existing_type=sa.UUID(), nullable=True)

    _rewrite("SET NULL")

    # A row naming neither party is not a record of anything. One side null is a
    # legitimate orphan; neither is not, and permitting it would let a future
    # INSERT fabricate referrals that no aggregate could explain.
    op.create_check_constraint(
        "ck_referrals_at_least_one_party",
        "referrals",
        "referrer_id IS NOT NULL OR referred_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_referrals_at_least_one_party", "referrals", type_="check")

    # Restore the cascade *before* the NOT NULL. If any row was orphaned while
    # the SET NULL version was live, that step fails - and failing is correct: a
    # downgrade cannot invent the missing party, and deleting those rows to make
    # it fit would destroy exactly the ledger this migration exists to protect.
    _rewrite("CASCADE")

    for column in _COLUMNS:
        op.alter_column("referrals", column, existing_type=sa.UUID(), nullable=False)