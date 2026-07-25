import logging
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, get_db_replica
from app.models.market import Market
from app.models.trade import Trade
from app.schemas.trade import TradeResponse
from app.api.responses import success_response
from app.api.exceptions import NotFoundError

logger = logging.getLogger("polymarket")
router = APIRouter(tags=["trades"])


@router.get("/trades", summary="Global trade feed", description="Public global feed of recent trades across all markets.")
async def list_trades(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    market_slug: str | None = None,
    db: AsyncSession = Depends(get_db_replica),
):
    query = (
        select(Trade, Market.slug, Market.question)
        .join(Market, Trade.market_id == Market.id)
        .order_by(Trade.executed_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    if market_slug:
        query = query.where(Market.slug == market_slug)

    result = await db.execute(query)
    rows = result.all()

    trades = [
        {
            "id": str(trade.id),
            "market_id": str(trade.market_id),
            "market_slug": slug,
            "market_question": question,
            "outcome": trade.outcome,
            "side": trade.side,
            "price": float(trade.price),
            "amount": float(trade.amount),
            "executed_at": trade.executed_at,
        }
        for trade, slug, question in rows
    ]

    return success_response({
        "trades": trades,
        "page": page,
        "page_size": page_size,
    })


@router.get("/markets/{slug}/trades", summary="Market trade feed", description="Public trade feed for a specific market.")
async def list_market_trades(
    slug: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db_replica),
):
    market_result = await db.execute(select(Market).where(Market.slug == slug))
    market = market_result.scalar_one_or_none()
    if not market:
        raise NotFoundError("Market not found")

    result = await db.execute(
        select(Trade)
        .where(Trade.market_id == market.id)
        .order_by(Trade.executed_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    trades = result.scalars().all()

    return success_response({
        "trades": [
            {
                "id": str(t.id),
                "market_id": str(t.market_id),
                "market_slug": slug,
                "market_question": market.question,
                "outcome": t.outcome,
                "side": t.side,
                "price": float(t.price),
                "amount": float(t.amount),
                "executed_at": t.executed_at,
            }
            for t in trades
        ],
        "page": page,
        "page_size": page_size,
    })
