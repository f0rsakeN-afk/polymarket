import logging
from decimal import Decimal
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, get_db_replica
from app.deps import get_current_user
from app.models.market import Market
from app.models.liquidity import LiquidityPool, LPShare
from app.api.responses import success_response
from app.api.exceptions import ValidationError, NotFoundError
from app.services.liquidity_service import LiquidityService
from app.models.trade import Trade

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/markets", tags=["liquidity"])


@router.post("/{market_id}/liquidity")
async def add_liquidity(
    market_id: str,
    amount: float,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)
    if amount <= 0:
        raise ValidationError("Amount must be positive")
    result = await LiquidityService.add_liquidity(db, user, market_id, Decimal(str(amount)))
    return success_response(result)


@router.delete("/{market_id}/liquidity")
async def remove_liquidity(
    market_id: str,
    lp_tokens: float,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)
    if lp_tokens <= 0:
        raise ValidationError("LP tokens must be positive")
    result = await LiquidityService.remove_liquidity(db, user, market_id, Decimal(str(lp_tokens)))
    return success_response(result)


@router.get("/{market_id}/liquidity")
async def get_lp_position(
    market_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)
    market = await db.get(Market, market_id)
    if not market:
        from app.api.exceptions import NotFoundError
        raise NotFoundError("Market not found")

    pool = await db.execute(select(LiquidityPool).where(LiquidityPool.market_id == market.id))
    pool = pool.scalar_one_or_none()

    lp_result = await db.execute(
        select(LPShare).where(LPShare.pool_id == pool.id, LPShare.user_id == user.id)
    )
    lp_share = lp_result.scalar_one_or_none()

    if not lp_share:
        return success_response({
            "lp_tokens": 0.0,
            "collateral_deposited": 0.0,
            "pool_lp_token_supply": float(pool.lp_token_supply) if pool else 0.0,
            "pool_yes_shares": float(pool.yes_shares) if pool else 0.0,
            "pool_no_shares": float(pool.no_shares) if pool else 0.0,
        })

    return success_response({
        "lp_tokens": float(lp_share.lp_tokens),
        "collateral_deposited": float(lp_share.collateral_deposited),
        "pool_lp_token_supply": float(pool.lp_token_supply),
        "pool_yes_shares": float(pool.yes_shares),
        "pool_no_shares": float(pool.no_shares),
    })


@router.get("/liquidity/analytics")
async def get_lp_analytics(
    request: Request,
    db: AsyncSession = Depends(get_db_replica),
):
    user = await get_current_user(request, db)
    lp_result = await db.execute(
        select(LPShare, LiquidityPool, Market)
        .join(LiquidityPool, LPShare.pool_id == LiquidityPool.id)
        .join(Market, LiquidityPool.market_id == Market.id)
        .where(LPShare.user_id == user.id, LPShare.lp_tokens > 0)
    )
    rows = lp_result.all()

    positions = []
    total_value = Decimal("0")

    for lp, pool, market in rows:
        share_pct = lp.lp_tokens / pool.lp_token_supply if pool.lp_token_supply > 0 else Decimal("0")
        pool_value = pool.yes_shares + pool.no_shares
        position_value = pool_value * share_pct
        fees_earned = pool.protocol_fees * share_pct
        net_value = position_value - lp.collateral_deposited
        apr = Decimal("0")
        if lp.collateral_deposited > 0:
            days_since = max(1, (pool.updated_at - lp.created_at).days) if lp.created_at and pool.updated_at else 1
            apr = (net_value / lp.collateral_deposited) * (Decimal("365") / Decimal(str(days_since))) * Decimal("100")

        total_value += position_value

        positions.append({
            "market_id": str(market.id),
            "market_slug": market.slug,
            "market_question": market.question,
            "lp_tokens": float(lp.lp_tokens),
            "collateral_deposited": float(lp.collateral_deposited),
            "position_value": float(position_value),
            "share_pct": float(share_pct * 100),
            "fees_earned": float(fees_earned),
            "net_pnl": float(net_value),
            "estimated_apr": float(apr),
            "pool_yes_price": float(pool.no_shares / (pool.yes_shares + pool.no_shares)) if (pool.yes_shares + pool.no_shares) > 0 else 0.5,
            "pool_no_price": float(pool.yes_shares / (pool.yes_shares + pool.no_shares)) if (pool.yes_shares + pool.no_shares) > 0 else 0.5,
        })

    return success_response({
        "positions": positions,
        "total_value": float(total_value),
        "total_deposited": float(sum(p["collateral_deposited"] for p in positions)),
        "total_pnl": float(total_value - Decimal(str(sum(p["collateral_deposited"] for p in positions)))),
    })
