import logging
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.api.responses import success_response
from app.database import get_db, get_db_replica
from app.deps import get_current_user
from app.models.faq import MarketFAQ
from app.models.liquidity import LiquidityPool
from app.models.market import Market, Outcome
from app.models.position import Position
from app.models.wallet import Transaction, Wallet
from app.schemas.faq import FAQResponse
from app.schemas.market import (
    CreateMarketRequest,
    MarketListResponse,
    MarketResponse,
    OutcomeResponse,
    ResolveMarketRequest,
)
from app.services.market_service import MarketService
from app.workers.tasks import resolve_market

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/markets", tags=["markets"])


def market_to_response(market: Market, yes_price: float = 0.5, no_price: float = 0.5, outcomes: list | None = None) -> MarketResponse:
    resp = MarketResponse(
        id=str(market.id),
        slug=market.slug,
        question=market.question,
        description=market.description,
        category=market.category,
        status=market.status,
        total_liquidity=float(market.total_liquidity or 0),
        total_volume=float(market.total_volume or 0),
        yes_price=yes_price,
        no_price=no_price,
        closes_at=market.closes_at,
        winning_outcome_id=str(market.winning_outcome_id) if market.winning_outcome_id else None,
        winning_outcome_name=None,
    )
    if outcomes:
        resp.outcomes = [
            OutcomeResponse(id=str(o.id), name=o.name, outcome_index=o.outcome_index)
            for o in outcomes
        ]
    return resp


@router.get("/", response_model=MarketListResponse)
async def list_markets(
    q: str | None = None,
    category: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_replica),
):
    base = select(Market, LiquidityPool)
    if q:
        base = base.where(Market.question.ilike(f"%{q}%"))
    if status:
        base = base.where(Market.status == status)
    if category:
        base = base.where(Market.category == category)

    query = (
        base.outerjoin(LiquidityPool, Market.id == LiquidityPool.market_id)
        .order_by(Market.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size + 1)
    )

    result = await db.execute(query)
    rows = result.all()
    has_more = len(rows) > page_size
    if has_more:
        rows = rows[:page_size]

    market_responses = []
    for market, pool in rows:
        yes_price, no_price = MarketService.compute_prices(pool)
        market_responses.append(market_to_response(market, yes_price, no_price))

    outcomes_result = await db.execute(
        select(Outcome).order_by(Outcome.outcome_index)
    )
    all_outcomes = outcomes_result.scalars().all()
    outcomes_by_market: dict = {}
    for o in all_outcomes:
        key = str(o.market_id)
        outcomes_by_market.setdefault(key, []).append(o)

    for resp in market_responses:
        outcomes = outcomes_by_market.get(resp.id)
        if outcomes and len(outcomes) > 2:
            resp.outcomes = [
                OutcomeResponse(id=str(o.id), name=o.name, outcome_index=o.outcome_index)
                for o in outcomes
            ]

    return MarketListResponse(
        data=market_responses,
        page=page,
        page_size=page_size,
        has_more=has_more,
    )


@router.get("/{slug}")
async def get_market(slug: str, db: AsyncSession = Depends(get_db_replica)):
    result = await db.execute(select(Market).where(Market.slug == slug))
    market = result.scalar_one_or_none()
    if not market:
        raise NotFoundError(f"Market '{slug}' not found")

    yes_price, no_price = await MarketService.get_market_prices(str(market.id))
    spread = abs(yes_price - no_price)

    outcomes_result = await db.execute(
        select(Outcome).where(Outcome.market_id == market.id).order_by(Outcome.outcome_index)
    )
    outcomes = outcomes_result.scalars().all()

    return success_response({
        **market_to_response(market, yes_price, no_price).model_dump(),
        "outcomes": [
            OutcomeResponse(id=str(o.id), name=o.name, outcome_index=o.outcome_index).model_dump()
            for o in outcomes
        ],
        "spread": spread,
        "created_at": market.created_at.isoformat() if market.created_at else None,
    })


@router.get("/{slug}/orderbook")
async def get_orderbook(slug: str, db: AsyncSession = Depends(get_db_replica)):
    result = await db.execute(select(Market).where(Market.slug == slug))
    market = result.scalar_one_or_none()
    if not market:
        raise NotFoundError(f"Market '{slug}' not found")

    from app.models.order import Order
    pending = await db.execute(
        select(Order.outcome_id, Order.price, func.sum(Order.remaining_amount).label("total_size"))
        .where(
            Order.market_id == market.id,
            Order.status == "pending",
            Order.order_type.in_(["limit", "fill_or_kill"]),
        )
        .group_by(Order.outcome_id, Order.price)
        .order_by(Order.price.desc())
    )
    rows = pending.all()

    outcomes_result = await db.execute(
        select(Outcome).where(Outcome.market_id == market.id)
    )
    outcome_names = {str(o.id): o.name.lower() for o in outcomes_result.scalars().all()}

    bids = []
    asks = []
    for row in rows:
        entry = {
            "outcome_id": str(row.outcome_id),
            "outcome": outcome_names.get(str(row.outcome_id), "unknown"),
            "price": float(row.price),
            "size": float(row.total_size),
        }
        if entry["outcome"] == "yes":
            bids.append(entry)
        else:
            asks.append(entry)

    return {"bids": bids, "asks": asks}


@router.post("/")
async def create_market(data: CreateMarketRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if not user.is_admin:
        raise ForbiddenError("Only admins can create markets")

    if data.closes_at <= datetime.now():
        raise ValidationError("closes_at must be in the future")

    if data.initial_probability is not None and data.initial_liquidity <= 0:
        raise ValidationError("initial_probability requires initial_liquidity > 0")

    existing = await db.execute(select(Market).where(Market.slug == data.slug))
    if existing.scalar_one_or_none():
        raise ValidationError(f"Market with slug '{data.slug}' already exists")

    market = Market(
        slug=data.slug,
        question=data.question,
        description=data.description,
        category=data.category,
        created_by=user.id,
        status="active",
        closes_at=data.closes_at,
    )
    db.add(market)
    await db.flush()

    if data.outcomes_create:
        db.add_all([
            Outcome(market_id=market.id, name=oc.name, outcome_index=oc.outcome_index)
            for oc in data.outcomes_create
        ])
    else:
        outcome_yes = Outcome(market_id=market.id, name="Yes", outcome_index=0)
        outcome_no = Outcome(market_id=market.id, name="No", outcome_index=1)
        db.add_all([outcome_yes, outcome_no])
    await db.flush()

    pool = LiquidityPool(
        market_id=market.id,
        yes_shares=0,
        no_shares=0,
        collateral=0,
        lp_token_supply=0,
    )
    db.add(pool)
    await db.flush()

    if data.initial_liquidity > 0:
        from app.models.wallet import Wallet
        wallet = await db.execute(select(Wallet).where(Wallet.user_id == user.id))
        wallet = wallet.scalar_one_or_none()
        if wallet and wallet.balance >= Decimal(str(data.initial_liquidity)):
            amount_dec = Decimal(str(data.initial_liquidity))
            wallet.balance -= amount_dec
            if data.initial_probability is not None:
                yes_shares = amount_dec * Decimal(str(1 - data.initial_probability))
                no_shares = amount_dec * Decimal(str(data.initial_probability))
                pool.yes_shares += yes_shares
                pool.no_shares += no_shares
            else:
                half = amount_dec / Decimal(2)
                pool.yes_shares += half
                pool.no_shares += half
            pool.collateral += amount_dec
            pool.lp_token_supply = amount_dec * Decimal(2)

    await db.commit()
    logger.info(f"Market created: {data.slug} by admin={user.id}")
    return success_response({"slug": data.slug, "id": str(market.id)})


@router.get("/{slug}/faqs")
async def get_faqs(slug: str, db: AsyncSession = Depends(get_db_replica)):
    result = await db.execute(select(Market).where(Market.slug == slug))
    market = result.scalar_one_or_none()
    if not market:
        raise NotFoundError(f"Market '{slug}' not found")
    faqs_result = await db.execute(
        select(MarketFAQ).where(MarketFAQ.market_id == market.id).order_by(MarketFAQ.display_order)
    )
    faqs = faqs_result.scalars().all()
    return success_response([FAQResponse(id=str(f.id), question=f.question, answer=f.answer, display_order=f.display_order) for f in faqs])


@router.get("/{slug}/price-history")
async def get_price_history(
    slug: str,
    interval: str = "5m",
    from_date: str | None = None,
    to_date: str | None = None,
    db: AsyncSession = Depends(get_db_replica),
):
    from app.models.market import Outcome
    from app.models.price_history import PriceHistory

    market = await db.execute(select(Market).where(Market.slug == slug))
    market = market.scalar_one_or_none()
    if not market:
        raise NotFoundError(f"Market '{slug}' not found")

    filters = [PriceHistory.market_id == market.id]
    if from_date:
        filters.append(PriceHistory.snapshot_at >= datetime.fromisoformat(from_date))
    if to_date:
        filters.append(PriceHistory.snapshot_at <= datetime.fromisoformat(to_date))

    raw = await db.execute(
        select(PriceHistory)
        .where(*filters)
        .order_by(PriceHistory.snapshot_at.asc())
    )
    rows = raw.scalars().all()

    outcomes_result = await db.execute(
        select(Outcome).where(Outcome.market_id == market.id).order_by(Outcome.outcome_index)
    )
    outcomes_map = {str(o.id): o.name for o in outcomes_result.scalars().all()}

    interval_seconds = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}.get(interval, 300)

    grouped: dict = {}
    for r in rows:
        ts = int(r.snapshot_at.timestamp())
        bucket = ts - (ts % interval_seconds)
        grouped.setdefault(bucket, []).append(r)

    samples = []
    for bucket_ts in sorted(grouped):
        bucket_rows = grouped[bucket_ts]
        ts_dt = datetime.fromtimestamp(bucket_ts, tz=UTC)
        outcome_prices = {}
        total_vol = 0
        for r in bucket_rows:
            oid = str(r.outcome_id)
            outcome_prices[oid] = float(r.price)
            total_vol += float(r.total_volume or 0)
        samples.append({
            "timestamp": ts_dt.isoformat(),
            "outcomes": [
                {"id": oid, "name": outcomes_map.get(oid, "Unknown"), "price": outcome_prices[oid]}
                for oid in sorted(outcome_prices, key=lambda x: outcomes_map.get(x, ""))
            ],
            "total_volume": total_vol,
        })

    return success_response(samples)


@router.get("/{slug}/related")
async def get_related(slug: str, db: AsyncSession = Depends(get_db_replica)):
    result = await db.execute(select(Market).where(Market.slug == slug))
    market = result.scalar_one_or_none()
    if not market:
        raise NotFoundError(f"Market '{slug}' not found")

    related = await db.execute(
        select(Market, LiquidityPool)
        .outerjoin(LiquidityPool, Market.id == LiquidityPool.market_id)
        .where(
            Market.id != market.id,
            (Market.category == market.category) | (Market.subcategory == market.subcategory),
        )
        .order_by(Market.total_volume.desc())
        .limit(5)
    )
    rows = related.all()
    return success_response([
        market_to_response(m, *MarketService.compute_prices(p)).model_dump()
        for m, p in rows
    ])


@router.post("/{slug}/resolve")
async def resolve_market_endpoint(
    slug: str,
    body: ResolveMarketRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)
    if not user.is_admin:
        raise ForbiddenError("Only admins can resolve markets")

    result = await db.execute(select(Market).where(Market.slug == slug))
    market = result.scalar_one_or_none()
    if not market:
        raise NotFoundError(f"Market '{slug}' not found")

    if market.status == "resolved":
        raise ValidationError("Market is already resolved")

    outcome_result = await db.execute(
        select(Outcome).where(Outcome.id == body.winning_outcome_id, Outcome.market_id == market.id)
    )
    outcome = outcome_result.scalar_one_or_none()
    if not outcome:
        raise ValidationError("Winning outcome does not belong to this market")

    market.status = "resolved"
    market.winning_outcome_id = outcome.id
    market.resolved_at = datetime.now(UTC)
    await db.commit()

    resolve_market.delay(str(market.id), str(outcome.id))

    logger.info(f"Market resolved: {slug} -> {outcome.name} by admin={user.id}")
    return success_response({
        "slug": slug,
        "winning_outcome_id": str(outcome.id),
        "winning_outcome_name": outcome.name,
    })


@router.post("/{slug}/claim")
async def claim_winnings(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)

    result = await db.execute(select(Market).where(Market.slug == slug))
    market = result.scalar_one_or_none()
    if not market:
        raise NotFoundError(f"Market '{slug}' not found")
    if market.status != "resolved":
        raise ValidationError("Market is not yet resolved")
    if not market.winning_outcome_id:
        raise ValidationError("Market has no winning outcome set")

    pos_result = await db.execute(
        select(Position).where(
            Position.user_id == user.id,
            Position.market_id == market.id,
            Position.outcome_id == market.winning_outcome_id,
            Position.shares_held > 0,
        ).with_for_update()
    )
    winning_pos = pos_result.scalar_one_or_none()
    if not winning_pos:
        raise ValidationError("You have no winning shares to claim")

    wallet_result = await db.execute(
        select(Wallet).where(Wallet.user_id == user.id).with_for_update()
    )
    wallet = wallet_result.scalar_one_or_none()
    if not wallet:
        raise NotFoundError("Wallet not found")

    payout = winning_pos.shares_held
    wallet.balance += payout
    winning_pos.realized_pnl += payout
    winning_pos.shares_held = 0

    tx = Transaction(
        user_id=user.id,
        wallet_id=wallet.id,
        type="settlement_win",
        amount=payout,
        balance_after=wallet.balance,
        reference_id=str(market.id),
        reference_type="market_settlement",
        status="completed",
    )
    db.add(tx)
    await db.commit()

    logger.info(f"Claimed winnings: user={user.id} market={slug} payout={payout}")
    return success_response({"claimed": float(payout)})
