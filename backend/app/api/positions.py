import logging
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, get_db_replica
from app.deps import get_current_user
from app.models.position import Position
from app.models.market import Market, Outcome
from app.models.liquidity import LiquidityPool
from app.schemas.order import PositionResponse
from app.api.responses import success_response
from app.api.exceptions import NotFoundError

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/positions", tags=["positions"])


@router.get("/", summary="List positions", description="List all active positions with realized P&L (from closed trades) and unrealized P&L (based on current AMM prices).")
async def list_positions(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db_replica),
):
    user = await get_current_user(request, db)

    result = await db.execute(
        select(Position)
        .where(Position.user_id == user.id, Position.shares_held > 0)
        .order_by(Position.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    positions = result.scalars().all()

    response = []
    for pos in positions:
        market_result = await db.execute(select(Market).where(Market.id == pos.market_id))
        market = market_result.scalar_one_or_none()
        outcome_result = await db.execute(select(Outcome).where(Outcome.id == pos.outcome_id))
        outcome = outcome_result.scalar_one_or_none()
        pool_result = await db.execute(select(LiquidityPool).where(LiquidityPool.market_id == pos.market_id))
        pool = pool_result.scalar_one_or_none()

        if pool and float(pool.yes_shares) + float(pool.no_shares) > 0:
            current_yes = float(pool.yes_shares) / (float(pool.yes_shares) + float(pool.no_shares))
        else:
            current_yes = 0.5

        if outcome and outcome.name.lower() == "yes":
            unrealized_pnl = float(pos.shares_held) * (current_yes - float(pos.average_price))
        else:
            unrealized_pnl = float(pos.shares_held) * ((1 - current_yes) - float(pos.average_price))

        response.append(PositionResponse(
            id=str(pos.id),
            market_id=str(pos.market_id),
            market_question=market.question if market else None,
            outcome=outcome.name.lower() if outcome else "",
            shares_held=float(pos.shares_held),
            average_price=float(pos.average_price),
            realized_pnl=float(pos.realized_pnl),
            unrealized_pnl=unrealized_pnl,
        ))

    return success_response({"positions": response, "page": page, "page_size": page_size})
