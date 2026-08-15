import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import NotFoundError
from app.api.responses import success_response
from app.database import get_db_replica
from app.models.comment import Comment
from app.models.liquidity import LiquidityPool
from app.models.market import Market, Outcome
from app.models.position import Position
from app.models.trade import Trade
from app.models.user import User

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/markets", tags=["market_activity"])


@router.get("/{slug}/activity", summary="Live market activity", description="Live activity feed for a market: top holders, recent trades, recent comments, and market stats.")
async def get_market_activity(
    slug: str,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_replica),
):
    """
    Returns:
    - market_stats: volume, liquidity, spread, num_trades
    - top_holders: top 10 positions by shares_held for each outcome
    - recent_trades: last N trades
    - recent_comments: last N comments
    - liquidity: YES/NO pool shares
    """
    market_result = await db.execute(select(Market).where(Market.slug == slug))
    market = market_result.scalar_one_or_none()
    if not market:
        raise NotFoundError("Market not found")

    # Market stats
    pool_result = await db.execute(
        select(LiquidityPool).where(LiquidityPool.market_id == market.id)
    )
    pool = pool_result.scalar_one_or_none()

    if pool:
        total = float(pool.yes_shares) + float(pool.no_shares)
        yes_price = float(pool.no_shares) / total if total > 0 else 0.5
        no_price = float(pool.yes_shares) / total if total > 0 else 0.5
        yes_liquidity = float(pool.yes_shares)
        no_liquidity = float(pool.no_shares)
    else:
        yes_price = no_price = 0.5
        yes_liquidity = no_liquidity = 0.0

    market_stats = {
        "total_volume": str(market.total_volume),
        "total_liquidity": str(market.total_liquidity),
        "num_trades": market.num_trades,
        "yes_price": str(yes_price),
        "no_price": str(no_price),
        "spread": str(abs(yes_price - no_price)),
        "yes_liquidity": str(yes_liquidity),
        "no_liquidity": str(no_liquidity),
        "status": market.status,
    }

    # All outcomes for this market
    outcomes_result = await db.execute(
        select(Outcome).where(Outcome.market_id == market.id).order_by(Outcome.outcome_index)
    )
    outcomes = outcomes_result.scalars().all()

    # Group top holders by outcome
    top_holders_by_outcome = {}
    for outcome in outcomes:
        holders_result = await db.execute(
            select(Position, User.username)
            .join(User, Position.user_id == User.id)
            .where(Position.market_id == market.id, Position.outcome_id == outcome.id)
            .order_by(Position.shares_held.desc())
            .limit(10)
        )
        holders = []
        for pos, username in holders_result:
            holders.append({
                "user_id": str(pos.user_id),
                "username": username,
                "shares_held": str(pos.shares_held),
                "average_price": str(pos.average_price),
                "realized_pnl": str(pos.realized_pnl),
            })
        if holders:
            top_holders_by_outcome[outcome.name] = holders

    # Recent trades
    trades_result = await db.execute(
        select(Trade, User.username)
        .join(User, Trade.user_id == User.id)
        .where(Trade.market_id == market.id)
        .order_by(Trade.executed_at.desc())
        .limit(limit)
    )
    recent_trades = [
        {
            "id": str(t.id),
            "outcome": t.outcome,
            "side": t.side,
            "price": str(t.price),
            "amount": str(t.amount),
            "executed_at": t.executed_at.isoformat(),
            "username": username,
        }
        for t, username in trades_result.all()
    ]

    # Recent comments
    comments_result = await db.execute(
        select(Comment, User.username)
        .join(User, Comment.user_id == User.id)
        .where(Comment.market_id == market.id, not Comment.is_deleted)
        .order_by(Comment.created_at.desc())
        .limit(limit)
    )
    recent_comments = [
        {
            "id": str(c.id),
            "user_id": str(c.user_id),
            "username": username,
            "content": c.content,
            "depth": c.depth,
            "created_at": c.created_at.isoformat(),
        }
        for c, username in comments_result.all()
    ]

    return success_response({
        "market_stats": market_stats,
        "top_holders_by_outcome": top_holders_by_outcome,
        "recent_trades": recent_trades,
        "recent_comments": recent_comments,
    })
