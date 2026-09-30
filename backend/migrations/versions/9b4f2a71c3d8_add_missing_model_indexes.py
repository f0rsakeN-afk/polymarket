"""add missing model indexes (comments, orders, FTS)

Creates the indexes that are declared on the models but were never applied by
a migration (issue #90):

* ``ix_comments_market_id`` / ``ix_comments_parent_id`` / ``ix_comments_market_parent``
  -- ``list_comments`` filters by ``market_id`` and ``get_replies`` by ``parent_id``,
  both full table scans without these.
* ``ix_orders_market_outcome_side_price`` / ``ix_orders_market_outcome_price``
  -- declared on ``Order`` for order-book / matching lookups.
* ``ix_markets_question_fts`` -- GIN expression index for the full-text search in
  ``list_markets``. Must be an expression index on ``to_tsvector('english', question)``:
  PostgreSQL has no default GIN opclass for varchar/text columns, so a plain
  GIN index on ``question`` cannot be created at all.

Revision ID: 9b4f2a71c3d8
Revises: 3c95a685f3f9
Create Date: 2026-09-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9b4f2a71c3d8'
down_revision: Union[str, None] = '3c95a685f3f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # comments: hot filters in list_comments / get_replies (#90)
    op.create_index('ix_comments_market_id', 'comments', ['market_id'], unique=False, if_not_exists=True)
    op.create_index('ix_comments_parent_id', 'comments', ['parent_id'], unique=False, if_not_exists=True)
    op.create_index('ix_comments_market_parent', 'comments', ['market_id', 'parent_id'], unique=False, if_not_exists=True)

    # orders: declared on the model but never migrated
    op.create_index(
        'ix_orders_market_outcome_side_price', 'orders',
        ['market_id', 'outcome_id', 'side', 'price'], unique=False, if_not_exists=True,
    )
    op.create_index(
        'ix_orders_market_outcome_price', 'orders',
        ['market_id', 'outcome_id', 'price'], unique=False, if_not_exists=True,
    )

    # markets: full-text search expression index (query side uses the exact
    # same to_tsvector('english', ...) expression so the planner can match it)
    op.create_index(
        'ix_markets_question_fts', 'markets',
        [sa.text("to_tsvector('english', question)")],
        unique=False,
        postgresql_using='gin',
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index('ix_markets_question_fts', table_name='markets', if_exists=True)
    op.drop_index('ix_orders_market_outcome_price', table_name='orders', if_exists=True)
    op.drop_index('ix_orders_market_outcome_side_price', table_name='orders', if_exists=True)
    op.drop_index('ix_comments_market_parent', table_name='comments', if_exists=True)
    op.drop_index('ix_comments_parent_id', table_name='comments', if_exists=True)
    op.drop_index('ix_comments_market_id', table_name='comments', if_exists=True)
