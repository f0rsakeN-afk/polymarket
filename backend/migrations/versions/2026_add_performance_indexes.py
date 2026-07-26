"""Add indexes for query performance (orders, trades, positions, transactions)

Revision ID: 2026_add_performance_indexes
Revises: 1e3a5b7c9d0f
Create Date: 2026-07-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "2026_add_performance_indexes"
down_revision: Union[str, None] = "1e3a5b7c9d0f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Orders: composite indexes for listing/filtering
    op.create_index("ix_orders_user_created", "orders", ["user_id", "created_at"])
    op.create_index("ix_orders_market_status", "orders", ["market_id", "status"])

    # Trades: indexes for user history, market feed, and time-based queries
    op.create_index("ix_trades_user_id", "trades", ["user_id"])
    op.create_index("ix_trades_market_id", "trades", ["market_id"])
    op.create_index("ix_trades_executed_at", "trades", ["executed_at"])
    op.create_index("ix_trades_user_executed", "trades", ["user_id", "executed_at"])

    # Positions: index for user position queries
    op.create_index("ix_positions_user_id", "positions", ["user_id"])
    op.create_index("ix_positions_created_at", "positions", ["created_at"])
    op.create_index("ix_positions_user_market", "positions", ["user_id", "market_id"])

    # Transactions: index for user history
    op.create_index("ix_transactions_user_id", "transactions", ["user_id"])
    op.create_index("ix_transactions_user_created", "transactions", ["user_id", "created_at"])

    # Wallets: index on user_id already exists (unique), but add for transactions lookup
    op.create_index("ix_transactions_wallet_id", "transactions", ["wallet_id"])


def downgrade() -> None:
    op.drop_index("ix_orders_user_created")
    op.drop_index("ix_orders_market_status")
    op.drop_index("ix_trades_user_id")
    op.drop_index("ix_trades_market_id")
    op.drop_index("ix_trades_executed_at")
    op.drop_index("ix_trades_user_executed")
    op.drop_index("ix_positions_user_id")
    op.drop_index("ix_positions_created_at")
    op.drop_index("ix_positions_user_market")
    op.drop_index("ix_transactions_user_id")
    op.drop_index("ix_transactions_user_created")
    op.drop_index("ix_transactions_wallet_id")
