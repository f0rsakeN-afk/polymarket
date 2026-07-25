import logging
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, get_db_replica
from app.models.market import Market, Outcome
from app.models.position import Position
from app.models.trade import Trade
from app.models.comment import Comment
from app.models.user import User
from app.models.liquidity import LiquidityPool
from app.api.responses import success_response
from app.api.exceptions import NotFoundError

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
        "total_volume": float(market.total_volume),
        "total_liquidity": float(market.total_liquidity),
        "num_trades": market.num_trades,
        "yes_price": yes_price,
        "no_price": no_price,
        "spread": abs(yes_price - no_price),
        "yes_liquidity": yes_liquidity,
        "no_liquidity": no_liquidity,
        "status": market.status,
    }

    # Top YES holders
    yes_outcome_result = await db.execute(
        select(Outcome).where(Outcome.market_id == market.id, Outcome.outcome_index == 0)
    )
    yes_outcome = yes_outcome_result.scalar_one_or_none()

    top_holders_yes = []
    if yes_outcome:
        holders_result = await db.execute(
            select(Position, User.username)
            .join(User, Position.user_id == User.id)
            .where(Position.market_id == market.id, Position.outcome_id == yes_outcome.id)
            .order_by(Position.shares_held.desc())
            .limit(10)
        )
        for pos, username in holders_result:
            top_holders_yes.append({
                "user_id": str(pos.user_id),
                "username": username,
                "shares_held": float(pos.shares_held),
                "average_price": float(pos.average_price),
                "realized_pnl": float(pos.realized_pnl),
            })

    # Top NO holders
    no_outcome_result = await db.execute(
        select(Outcome).where(Outcome.market_id == market.id, Outcome.outcome_index == 1)
    )
    no_outcome = no_outcome_result.scalar_one_or_none()

    top_holders_no = []
    if no_outcome:
        holders_result = await db.execute(
            select(Position, User.username)
            .join(User, Position.user_id == User.id)
            .where(Position.market_id == market.id, Position.outcome_id == no_outcome.id)
            .order_by(Position.shares_held.desc())
            .limit(10)
        )
        for pos, username in holders_result:
            top_holders_no.append({
                "user_id": str(pos.user_id),
                "username": username,
                "shares_held": float(pos.shares_held),
                "average_price": float(pos.average_price),
                "realized_pnl": float(pos.realized_pnl),
            })

    # Recent trades
    trades_result = await db.execute(
        select(Trade)
        .where(Trade.market_id == market.id)
        .order_by(Trade.executed_at.desc())
        .limit(limit)
    )
    recent_trades = [
        {
            "id": str(t.id),
            "outcome": t.outcome,
            "side": t.side,
            "price": float(t.price),
            "amount": float(t.amount),
            "executed_at": t.executed_at.isoformat(),
        }
        for t in trades_result.scalars().all()
    ]

    # Recent comments
    comments_result = await db.execute(
        select(Comment, User.username)
        .join(User, Comment.user_id == User.id)
        .where(Comment.market_id == market.id, Comment.is_deleted == False)
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
        "top_holders_yes": top_holders_yes,
        "top_holders_no": top_holders_no,
        "recent_trades": recent_trades,
        "recent_comments": recent_comments,
    })
