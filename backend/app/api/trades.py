import base64
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import NotFoundError, ValidationError
from app.api.responses import success_response
from app.database import get_db_replica
from app.models.market import Market
from app.models.trade import Trade
from app.models.user import User

logger = logging.getLogger("polymarket")
router = APIRouter(tags=["trades"])


def _encode_cursor(executed_at, trade_id) -> str:
    raw = f"{executed_at.isoformat()}|{trade_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, object]:
    import uuid

    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts_str, trade_id = raw.rsplit("|", 1)
        return datetime.fromisoformat(ts_str), uuid.UUID(trade_id)
    except Exception:
        raise ValidationError("Invalid cursor")


def _cursor_filter(query, cursor: str | None):
    """Keyset filter for stable desc pagination. executed_at alone is not
    unique (same-ms trades), so (executed_at, id) is the tiebreak pair."""
    if not cursor:
        return query
    ts, trade_id = _decode_cursor(cursor)
    return query.where(
        (Trade.executed_at < ts)
        | ((Trade.executed_at == ts) & (Trade.id < trade_id))
    )


@router.get("/trades", summary="Global trade feed", description="Public global feed of recent trades across all markets.")
async def list_trades(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    market_slug: str | None = None,
    cursor: str | None = Query(None, description="Opaque cursor from a previous response for stable pagination. Overrides page."),
    db: AsyncSession = Depends(get_db_replica),
):
    # Enforce keyset pagination when offset would exceed 1000
    use_cursor = cursor is not None or (page - 1) * page_size > 1000
    if not use_cursor and (page - 1) * page_size > 1000:
        raise ValidationError("Pagination offset exceeds 1000. Use cursor pagination instead.")
    query = (
        select(Trade, Market.slug, Market.question, User.username)
        .join(Market, Trade.market_id == Market.id)
        .join(User, Trade.user_id == User.id)
        .order_by(Trade.executed_at.desc(), Trade.id.desc())
        .limit(page_size + 1)  # +1 probes has_more without a COUNT query
    )

    if market_slug:
        query = query.where(Market.slug == market_slug)

    if cursor:
        query = _cursor_filter(query, cursor)
    elif not use_cursor:
        query = query.offset((page - 1) * page_size)

    result = await db.execute(query)
    rows = result.all()
    has_more = len(rows) > page_size
    rows = rows[:page_size]

    trades = [
        {
            "id": str(trade.id),
            "market_id": str(trade.market_id),
            "market_slug": slug,
            "market_question": question,
            "outcome": trade.outcome,
            "side": trade.side,
            "price": str(trade.price),
            "amount": str(trade.amount),
            "executed_at": trade.executed_at.isoformat() if trade.executed_at else None,
            "username": username,
        }
        for trade, slug, question, username in rows
    ]

    next_cursor = None
    if has_more and rows:
        last_trade = rows[-1][0]
        if last_trade.executed_at:
            next_cursor = _encode_cursor(last_trade.executed_at, last_trade.id)

    return success_response({
        "trades": trades,
        "page": page,
        "page_size": page_size,
        "next_cursor": next_cursor,
        "has_more": has_more,
    })


@router.get("/markets/{slug}/trades", summary="Market trade feed", description="Public trade feed for a specific market.")
async def list_market_trades(
    slug: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None, description="Opaque cursor from a previous response for stable pagination. Overrides page."),
    db: AsyncSession = Depends(get_db_replica),
):
    market_result = await db.execute(select(Market).where(Market.slug == slug))
    market = market_result.scalar_one_or_none()
    if not market:
        raise NotFoundError("Market not found")

    query = (
        select(Trade, User.username)
        .join(User, Trade.user_id == User.id)
        .where(Trade.market_id == market.id)
        .order_by(Trade.executed_at.desc(), Trade.id.desc())
        .limit(page_size + 1)
    )
    if cursor:
        query = _cursor_filter(query, cursor)
    else:
        query = query.offset((page - 1) * page_size)

    result = await db.execute(query)
    rows = result.all()
    has_more = len(rows) > page_size
    rows = rows[:page_size]

    next_cursor = None
    if has_more and rows:
        last_trade = rows[-1][0]
        if last_trade.executed_at:
            next_cursor = _encode_cursor(last_trade.executed_at, last_trade.id)

    return success_response({
        "trades": [
            {
                "id": str(t.id),
                "market_id": str(t.market_id),
                "market_slug": slug,
                "market_question": market.question,
                "outcome": t.outcome,
                "side": t.side,
                "price": str(t.price),
                "amount": str(t.amount),
                "executed_at": t.executed_at.isoformat() if t.executed_at else None,
                "username": username,
            }
            for t, username in rows
        ],
        "page": page,
        "page_size": page_size,
        "next_cursor": next_cursor,
        "has_more": has_more,
    })
