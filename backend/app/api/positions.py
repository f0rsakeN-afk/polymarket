import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import success_response
from app.database import get_db_replica
from app.deps import get_current_user
from app.models.liquidity import LiquidityPool
from app.models.market import Market, Outcome
from app.models.position import Position
from app.schemas.order import PositionResponse
from app.services.market_service import MarketService

logger = logging.getLogger("PredictX")
router = APIRouter(prefix="/positions", tags=["positions"])


@router.get("/", summary="List positions", description="List all active positions with realized P&L (from closed trades) and unrealized P&L (based on current AMM prices).")
async def list_positions(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db_replica),
):
    user = await get_current_user(request, db)

    # Count total for has_more
    count_result = await db.execute(
        select(func.count()).select_from(Position).where(Position.user_id == user.id, Position.shares_held > 0)
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(Position)
        .where(Position.user_id == user.id, Position.shares_held > 0)
        .order_by(Position.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    positions = result.scalars().all()

    if not positions:
        return success_response({"positions": [], "total": total, "page": page, "page_size": page_size, "has_more": False})

    # Batch fetch all related data to avoid N+1 queries
    market_ids = list({str(pos.market_id) for pos in positions})
    outcome_ids = list({str(pos.outcome_id) for pos in positions})

    markets_result = await db.execute(select(Market).where(Market.id.in_(market_ids)))
    markets = {str(m.id): m for m in markets_result.scalars().all()}

    outcomes_result = await db.execute(select(Outcome).where(Outcome.id.in_(outcome_ids)))
    outcomes = {str(o.id): o for o in outcomes_result.scalars().all()}

    # Keyed on (market_id, outcome_id), not market_id. A parimutuel market has one
    # pool per outcome, so a market_id-keyed dict would silently keep just the
    # last pool and price every position in the market off it.
    pools_by_outcome: dict[tuple[str, str], LiquidityPool] = {}
    binary_pools: dict[str, LiquidityPool] = {}
    all_pools: dict[str, list] = {}
    for market_id in market_ids:
        pools = await MarketService.load_all_pools(db, market_id)
        all_pools[market_id] = pools
        for pool in pools:
            if pool.outcome_id is None:
                binary_pools[market_id] = pool
            else:
                pools_by_outcome[(market_id, str(pool.outcome_id))] = pool

    # Price per (market, outcome). Computed once per market rather than per
    # position - a parimutuel outcome's price depends on every sibling pool, so
    # it cannot be derived from the position's own row alone.
    outcome_prices: dict[tuple[str, str], float] = {}
    for market_id, pools in all_pools.items():
        if market_id in binary_pools:
            pool = binary_pools[market_id]
            total = float(pool.yes_shares) + float(pool.no_shares)
            yes_price = float(pool.yes_shares) / total if total > 0 else 0.5
            for o in outcomes.values():
                if str(o.market_id) == market_id:
                    outcome_prices[(market_id, str(o.id))] = (
                        yes_price if o.name.lower() == "yes" else 1 - yes_price
                    )
        else:
            # Parimutuel: shares_i / SUM(shares). Dividing a single pool's
            # yes_shares by its own yes+no would always give 1.0, because a
            # parimutuel pool stores no_shares = 0.
            for outcome_id, price in MarketService.outcome_prices(pools).items():
                outcome_prices[(market_id, outcome_id)] = float(price)

    response = []
    for pos in positions:
        market = markets.get(str(pos.market_id))
        outcome = outcomes.get(str(pos.outcome_id))

        current_price = outcome_prices.get(
            (str(pos.market_id), str(pos.outcome_id)), 0.5
        )
        unrealized_pnl = float(pos.shares_held) * (
            current_price - float(pos.average_price)
        )

        response.append(PositionResponse(
            id=str(pos.id),
            market_id=str(pos.market_id),
            market_slug=market.slug if market else "",
            market_question=market.question if market else None,
            outcome=outcome.name.lower() if outcome else "",
            shares_held=str(pos.shares_held),
            average_price=str(pos.average_price),
            realized_pnl=str(pos.realized_pnl),
            unrealized_pnl=str(unrealized_pnl),
            current_price=str(current_price),
        ))

    return success_response({"positions": response, "total": total, "page": page, "page_size": page_size, "has_more": (page * page_size) < total})
