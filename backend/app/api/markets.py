import json
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.api.responses import success_response
from app.config import settings
from app.database import get_db, get_db_replica
from app.deps import get_current_user, get_optional_user
from app.models.faq import MarketFAQ
from app.models.liquidity import LiquidityPool, LPShare
from app.models.market import (
    STATUS_ACTIVE,
    STATUS_PENDING_REVIEW,
    UNPUBLISHED_STATUSES,
    Market,
    Outcome,
)
from app.models.position import Position
from app.models.wallet import Transaction, Wallet
from app.redis import get_redis
from app.schemas.faq import FAQResponse
from app.schemas.market import (
    CreateMarketRequest,
    MarketListResponse,
    MarketResponse,
    OutcomeResponse,
    ResolveMarketRequest,
)
from app.services.cache_service import (
    build_orderbook,
    cache_get_market,
    cache_get_market_list,
    cache_get_orderbook,
    cache_invalidate_market,
    cache_invalidate_market_lists,
    cache_set_market,
    cache_set_market_list,
    cache_set_orderbook,
)
from app.services.market_service import MarketService
from app.workers.tasks import resolve_market

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/markets", tags=["markets"])


def market_to_response(
    market: Market,
    yes_price: Decimal = Decimal("0.5"),
    no_price: Decimal = Decimal("0.5"),
    outcomes: list | None = None,
) -> MarketResponse:
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
        winning_outcome_id=str(market.winning_outcome_id)
        if market.winning_outcome_id
        else None,
        winning_outcome_name=None,
    )
    if outcomes:
        resp.outcomes = [
            OutcomeResponse(id=str(o.id), name=o.name, outcome_index=o.outcome_index)
            for o in outcomes
        ]
    return resp


@router.get("/")
async def list_markets(
    q: str | None = Query(None, max_length=200),
    category: str | None = Query(None, max_length=100),
    status: str | None = Query(None, max_length=32),
    sort: str = Query("volume", pattern="^(volume|newest|closing_soon|liquidity)$"),
    cursor: str | None = Query(None, max_length=512, description="Cursor for stable pagination: base64 encoding of (created_at, id). Overrides page."),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_replica),
):
    # Visibility gate first — it must run before the shared cache is read, or a
    # cached moderator view could be served to an anonymous caller.
    if status and status in UNPUBLISHED_STATUSES:
        raise ValidationError(
            f"Status '{status}' is not available on the public catalogue; "
            "use GET /api/v1/admin/markets",
            error_code="STATUS_NOT_PUBLIC",
        )

    # Cache key no longer includes page/page_size when cursor is used
    if cursor:
        cache_key = f"{q or ''}:{category or ''}:{status or ''}:{sort}"
    else:
        cache_key = f"{q or ''}:{category or ''}:{status or ''}:{sort}:{page}:{page_size}"
    cached = await cache_get_market_list(cache_key)
    if cached is not None:
        return MarketListResponse(**cached)

    base = select(Market, LiquidityPool)
    if q:
        # PostgreSQL full-text search using plainto_tsquery & tsrank_cd for relevance.
        # The to_tsvector('english', question) expression must match the
        # ix_markets_question_fts GIN expression index exactly (literal config,
        # not a bind param) so the planner can use it.
        # Fall back to ilike if FTS fails at execution time.
        try:
            fts_vector = func.to_tsvector(literal_column("'english'"), Market.question)
            query_vector = func.plainto_tsquery("english", q)
            relevance = func.ts_rank_cd(query_vector, fts_vector)
            base = base.where(func.plainto_tsquery("english", q).op("@@")(fts_vector))
            base = base.order_by(relevance.desc())
        except Exception:
            # Fallback: pattern‑like search if FTS is unavailable.
            safe_q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            base = base.where(Market.question.ilike(f"%{safe_q}%", escape="\\"))
    if status:
        base = base.where(Market.status == status)
    else:
        # No filter → the public catalogue: hide markets awaiting review (and
        # rejected ones) unless the caller explicitly asked for a status above.
        base = base.where(Market.status.notin_(UNPUBLISHED_STATUSES))
    if category:
        base = base.where(Market.category == category)

    # Build order by sort parameter
    if sort == "closing_soon":
        base = base.where(Market.status != "resolved")
        order = Market.closes_at.asc().nullslast()
    elif sort == "volume":
        order = Market.total_volume.desc()
    elif sort == "newest":
        order = Market.created_at.desc()
    else:
        order = Market.total_volume.desc()

    # Keyset (cursor-based) pagination: uses (created_at, id) as the tiebreak pair.
    # This avoids the performance degradation of OFFSET at large page numbers.
    if cursor:
        import base64
        try:
            raw = base64.urlsafe_b64decode(cursor.encode()).decode()
            ts_str, market_id = raw.rsplit("|", 1)
            cursor_ts = datetime.fromisoformat(ts_str)
            base = base.where(Market.created_at < cursor_ts)
        except Exception:
            raise ValidationError("Invalid cursor")
        query = (
            base.outerjoin(LiquidityPool, Market.id == LiquidityPool.market_id)
            .order_by(order)
            .limit(page_size + 1)
        )
    else:
        # Offset-based pagination with safety limit — avoid > 1000 row skip
        if (page - 1) * page_size > 1000:
            raise ValidationError(
                "Pagination offset exceeds 1000. Use cursor pagination instead.",
                error_code="PAGINATION_LIMIT"
            )
        query = (
            base.outerjoin(LiquidityPool, Market.id == LiquidityPool.market_id)
            .order_by(order)
            .offset((page - 1) * page_size)
            .limit(page_size + 1)
        )

    result = await db.execute(query)
    rows = result.all()
    has_more = len(rows) > page_size
    if has_more:
        rows = rows[:page_size]

    page_markets = [market for market, _ in rows]
    market_ids = [m.id for m in page_markets]

    # Batched price fetch: one Redis pipeline + one SELECT for all misses.
    # (Never N sequential per-market lookups — that fanned out DB sessions
    # and stalled cold list pages.)
    price_map = await MarketService.get_market_prices_batch(
        [str(m.id) for m in page_markets], db=db,
    )

    market_responses = []
    for i, (market, pool) in enumerate(rows):
        yes_price, no_price = price_map[str(market.id)]
        market_responses.append(market_to_response(market, yes_price, no_price))

    # Targeted outcome query using page market IDs
    outcomes_result = await db.execute(
        select(Outcome)
        .where(Outcome.market_id.in_(market_ids))
        .order_by(Outcome.outcome_index)
    )
    outcomes_by_market: dict = {}
    for o in outcomes_result.scalars().all():
        key = str(o.market_id)
        outcomes_by_market.setdefault(key, []).append(o)

    for resp in market_responses:
        outcomes = outcomes_by_market.get(resp.id)
        if outcomes and len(outcomes) > 2:
            resp.outcomes = [
                OutcomeResponse(
                    id=str(o.id), name=o.name, outcome_index=o.outcome_index
                )
                for o in outcomes
            ]

    resp = MarketListResponse(
        data=market_responses,
        page=page,
        page_size=page_size,
        has_more=has_more,
    )
    await cache_set_market_list(cache_key, resp.model_dump(), ttl=60)
    return resp.model_dump()


@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db_replica)):
    cached = await cache_get_market_list("categories")
    if cached is not None:
        return success_response(cached)

    result = await db.execute(
        select(Market.category).distinct().where(Market.category.isnot(None))
    )
    categories = [row[0] for row in result.all()]
    data = {"categories": categories}
    await cache_set_market_list("categories", data, ttl=300)
    return success_response(data)


@router.get("/{slug}")
async def get_market(slug: str, request: Request, db: AsyncSession = Depends(get_db_replica)):
    result = await db.execute(select(Market).where(Market.slug == slug))
    market = result.scalar_one_or_none()
    if not market:
        raise NotFoundError(f"Market '{slug}' not found")

    # Unpublished markets (pending review / rejected) are only readable by the
    # user who submitted them and by admins — and 404 rather than 403 for
    # everyone else, so the existence of unpublished submissions isn't leaked.
    if market.status in UNPUBLISHED_STATUSES:
        viewer = await get_optional_user(request, db)
        if viewer is None or (not viewer.is_admin and viewer.id != market.created_by):
            raise NotFoundError(f"Market '{slug}' not found")

    # Check cache using market_id
    cached = await cache_get_market(str(market.id))
    if cached is not None:
        return success_response(cached)

    yes_price, no_price = await MarketService.get_market_prices(str(market.id), db=db)
    spread = abs(yes_price - no_price)

    outcomes_result = await db.execute(
        select(Outcome)
        .where(Outcome.market_id == market.id)
        .order_by(Outcome.outcome_index)
    )
    outcomes = outcomes_result.scalars().all()

    data = {
        **market_to_response(market, yes_price, no_price).model_dump(),
        "outcomes": [
            OutcomeResponse(
                id=str(o.id), name=o.name, outcome_index=o.outcome_index
            ).model_dump()
            for o in outcomes
        ],
        "spread": spread,
        "created_at": market.created_at.isoformat() if market.created_at else None,
    }
    await cache_set_market(str(market.id), data, ttl=300)
    return success_response(data)


@router.get("/{slug}/orderbook")
async def get_orderbook(slug: str, db: AsyncSession = Depends(get_db_replica)):
    result = await db.execute(select(Market).where(Market.slug == slug))
    market = result.scalar_one_or_none()
    if not market:
        raise NotFoundError(f"Market '{slug}' not found")

    # Check cache using market_id (not slug)
    cached = await cache_get_orderbook(str(market.id))
    if cached is not None:
        # Cache stores the raw orderbook — wrap it so the response shape is
        # identical to the cache-miss path ({success, data}).
        return success_response(cached)

    data = await build_orderbook(db, str(market.id))
    await cache_set_orderbook(str(market.id), data, ttl=60)
    return success_response(data)


@router.post("/")
async def create_market(
    data: CreateMarketRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(request, db)
    # Anyone with a verified email may submit a market; it lands in
    # pending_review and only becomes visible/tradable once an admin approves
    # it. Admins bypass the review queue.
    if not user.is_admin and not user.is_email_verified:
        raise ForbiddenError("Verify your email before creating markets")

    if data.closes_at <= datetime.now(UTC):
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
        status=STATUS_ACTIVE if user.is_admin else STATUS_PENDING_REVIEW,
        closes_at=data.closes_at,
    )
    db.add(market)
    await db.flush()

    if data.outcomes_create:
        db.add_all(
            [
                Outcome(
                    market_id=market.id, name=oc.name, outcome_index=oc.outcome_index
                )
                for oc in data.outcomes_create
            ]
        )
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
        fee_rate=settings.trading_fee_rate,
        lp_token_supply=0,
    )
    db.add(pool)
    await db.flush()

    if data.initial_liquidity > 0:
        from app.models.wallet import Wallet

        wallet = await db.execute(
            select(Wallet).where(Wallet.user_id == user.id).with_for_update()
        )
        wallet = wallet.scalar_one_or_none()
        if wallet and wallet.balance >= Decimal(str(data.initial_liquidity)):
            amount_dec = Decimal(str(data.initial_liquidity))
            wallet.balance -= amount_dec
            if data.initial_probability is not None:
                # price(YES) = yes_shares / (yes_shares + no_shares), so the
                # YES side must be seeded with `initial_probability` of the
                # collateral — the inverse (the old behaviour) made a market
                # created at 0.70 open at 0.30.
                p = Decimal(str(data.initial_probability))
                yes_shares = amount_dec * p
                no_shares = amount_dec * (Decimal(1) - p)
                pool.yes_shares += yes_shares
                pool.no_shares += no_shares
            else:
                half = amount_dec / Decimal(2)
                pool.yes_shares += half
                pool.no_shares += half
            pool.credit_collateral(amount_dec)
            pool.lp_token_supply = amount_dec * Decimal(2)
            # The seeding wallet is the pool's first LP. Mint its shares so
            # `lp_token_supply == sum(lp_shares.lp_tokens)` holds for
            # API-created markets too (it previously didn't — the supply was
            # set with no holder, locking the seed away forever) and the
            # creator earns/exits like any other LP.
            db.add(
                LPShare(
                    pool_id=pool.id,
                    user_id=user.id,
                    lp_tokens=amount_dec * Decimal(2),
                    collateral_deposited=amount_dec,
                )
            )
            market.total_liquidity = (market.total_liquidity or Decimal(0)) + amount_dec

    await db.commit()
    logger.info(f"Market created: {data.slug} by user={user.id} status={market.status}")
    await cache_invalidate_market_lists()
    return success_response(
        market_to_response(market).model_dump(),
        message=(
            "Market created"
            if market.status == STATUS_ACTIVE
            else "Market submitted — pending admin approval"
        ),
    )


@router.get("/{slug}/faqs")
async def get_faqs(slug: str, db: AsyncSession = Depends(get_db_replica)):
    result = await db.execute(select(Market).where(Market.slug == slug))
    market = result.scalar_one_or_none()
    if not market:
        raise NotFoundError(f"Market '{slug}' not found")
    faqs_result = await db.execute(
        select(MarketFAQ)
        .where(MarketFAQ.market_id == market.id)
        .order_by(MarketFAQ.display_order)
    )
    faqs = faqs_result.scalars().all()
    return success_response(
        [
            FAQResponse(
                id=str(f.id),
                question=f.question,
                answer=f.answer,
                display_order=f.display_order,
            )
            for f in faqs
        ]
    )


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
        select(PriceHistory).where(*filters).order_by(PriceHistory.snapshot_at.asc()).limit(5000)
    )
    rows = raw.scalars().all()

    outcomes_result = await db.execute(
        select(Outcome)
        .where(Outcome.market_id == market.id)
        .order_by(Outcome.outcome_index)
    )
    outcomes_map = {str(o.id): o.name for o in outcomes_result.scalars().all()}

    interval_seconds = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "4h": 14400,
        "1d": 86400,
    }.get(interval, 300)

    grouped: dict = {}
    for r in rows:
        ts = int(r.snapshot_at.timestamp())
        bucket = ts - (ts % interval_seconds)
        grouped.setdefault(bucket, []).append(r)

    # Track last known price per outcome for carry-forward when one outcome has no snapshot in a bucket
    last_prices: dict[str, float] = {}

    samples = []
    for bucket_ts in sorted(grouped):
        bucket_rows = grouped[bucket_ts]
        ts_dt = datetime.fromtimestamp(bucket_ts, tz=UTC)
        outcome_prices: dict[str, float] = {}
        total_vol = 0
        for r in bucket_rows:
            oid = str(r.outcome_id)
            outcome_prices[oid] = float(r.price)
            last_prices[oid] = float(r.price)
            total_vol += float(r.total_volume or 0)

        # Carry forward last known price for outcomes missing in this bucket
        for oid, price in last_prices.items():
            if oid not in outcome_prices:
                outcome_prices[oid] = price

        samples.append(
            {
                "timestamp": ts_dt.isoformat(),
                "outcomes": [
                    {
                        "id": oid,
                        "name": outcomes_map.get(oid, "Unknown"),
                        "price": str(price),
                    }
                    for oid, price in sorted(outcome_prices.items(), key=lambda x: outcomes_map.get(x[0], ""))
                ],
                "total_volume": str(total_vol),
            }
        )

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
            (Market.category == market.category)
            | (Market.subcategory == market.subcategory),
        )
        .order_by(Market.total_volume.desc())
        .limit(5)
    )
    rows = related.all()
    return success_response(
        [
            market_to_response(m, *MarketService.compute_prices(p)).model_dump()
            for m, p in rows
        ]
    )


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

    # Lock the market row: the settlement worker takes the same lock, and this
    # request enqueues that worker *before* it commits. Holding the row lock
    # across enqueue→commit means the worker can only read this request's
    # writes after they land — so it can never race ahead and have its
    # `status = "resolved"` clobbered by this transaction's later write.
    result = await db.execute(
        select(Market).where(Market.slug == slug).with_for_update()
    )
    market = result.scalar_one_or_none()
    if not market:
        raise NotFoundError(f"Market '{slug}' not found")

    if market.status in ("resolved", "resolving"):
        raise ValidationError("Market is already resolved")

    # Distributed lock: prevent two API pods from both resolving the same market.
    # Uses Redis SETNX with TTL — lock is auto-released if this pod dies.
    r = await get_redis()
    lock_key = f"resolve_api_lock:{market.id}"
    lock_acquired = await r.set(lock_key, str(user.id), nx=True, ex=300)
    # 300s TTL covers the full resolution process (task enqueue + DB commit + worker processing).
    # The lock auto-expires if the worker crashes, making the market safely re-resolvable.
    if not lock_acquired:
        raise ConflictError("Market resolution is already in progress")

    try:
        outcome_result = await db.execute(
            select(Outcome).where(
                Outcome.id == body.winning_outcome_id, Outcome.market_id == market.id
            )
        )
        outcome = outcome_result.scalar_one_or_none()
        if not outcome:
            raise ValidationError("Winning outcome does not belong to this market")

        # Queue-level idempotency: check dedup key BEFORE enqueuing the task.
        # If the key already exists, another request already owns this resolution.
        task_dedup_key = f"resolve_enqueue:{market.id}"
        dedup_already_set = not await r.set(task_dedup_key, "1", nx=True, ex=3600)
        if dedup_already_set:
            # Another request already enqueued the resolution task — do not double-resolve.
            raise ConflictError("Resolution task already enqueued")

        # Enqueue settlement — guaranteed unique thanks to the dedup key check above.
        # Propagate X-Request-ID for tracing across service boundaries.
        try:
            request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
            resolve_market.apply_async(
                args=(str(market.id), str(outcome.id)),
                task_id=request_id,
                priority=5,
            )
        except Exception:
            # If enqueue fails after dedup key was set, we must clear it so a retry can succeed.
            await r.delete(task_dedup_key)
            logger.exception(f"Failed to enqueue settlement for market {market.id}")
            raise HTTPException(status_code=503, detail="Settlement service unavailable, please retry")

        # Mark as resolving (NOT resolved) — the worker flips to resolved after settlement.
        # Worker skips markets already in resolving/resolved, so this also guards double-settlement.
        market.status = "resolving"
        market.winning_outcome_id = outcome.id
        market.resolved_at = datetime.now(UTC)
        await db.commit()

        logger.info(f"Market resolved: {slug} -> {outcome.name} by admin={user.id}")
        await cache_invalidate_market(str(market.id))
        await cache_invalidate_market_lists()
        return success_response(
            {
                "slug": slug,
                "winning_outcome_id": str(outcome.id),
                "winning_outcome_name": outcome.name,
            },
            message="Market resolved",
        )
    finally:
        # Release the distributed lock; 300s TTL is a safety net if we crash
        # before this runs (lock auto-expires and market stays "resolving" — safe).
        await r.delete(lock_key)


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
    # "resolving" is claimable too: both callers that record a winning
    # outcome (POST /resolve and the dispute flow) set it in the same commit
    # that moves the market out of "active", and settlement may refuse to run
    # if the escrow is short — refusing to settle must NOT lock a winner out of
    # money they already won. Claiming here is safe against a concurrent
    # settle: both paths take Pool → Position → Wallet locks in that order and
    # both require settled_at IS NULL, so exactly one of them pays.
    if market.status not in ("resolving", "resolved"):
        raise ValidationError("Market is not yet resolved")
    if not market.winning_outcome_id:
        raise ValidationError("Market has no winning outcome set")

    # Lock the pool escrow under the canonical order (Market → Pool →
    # Position → Wallet) — settlement takes the same locks in this sequence,
    # so a claim racing the Celery settle serialises instead of deadlocking.
    pool_result = await db.execute(
        select(LiquidityPool).where(LiquidityPool.market_id == market.id).with_for_update()
    )
    pool = pool_result.scalar_one_or_none()

    # Idempotency: check settled_at before any write. SETNX on the DB row is the
    # authoritative guard — if two requests race here, only one wins.
    pos_result = await db.execute(
        select(Position)
        .where(
            Position.user_id == user.id,
            Position.market_id == market.id,
            Position.outcome_id == market.winning_outcome_id,
            Position.shares_held > 0,
            Position.settled_at.is_(None),  # not yet settled
        )
        .with_for_update()
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

    payout = Decimal(str(winning_pos.shares_held))
    if payout <= 0:
        raise ValidationError("No winnings to claim", error_code="NOTHING_TO_CLAIM")

    # The claim is *funded* from the pool escrow, not minted (single-entry
    # ledger). All-or-nothing: paying 10 of a 40-share claim would consume the
    # position (settled_at, shares_held = 0) for less than it is worth, so a
    # shortfall refuses instead — the position stays claimable and an ops top-up
    # makes it succeed on retry.
    available = Decimal(str(pool.collateral or 0)) if pool is not None else Decimal(0)
    if payout > available:
        # Nothing has been debited yet — compare, don't probe-and-mutate. A
        # partial claim would consume the position (settled_at, shares_held=0)
        # for less than it is worth, and the remainder would be owed to nobody:
        # the position is the record that the debt is still open, so it stays
        # exactly as it is and the claim can be retried once the escrow is
        # funded. `pool is None` lands here too — the old `else payout` branch
        # credited the wallet in full with no escrow behind it.
        logger.error(json.dumps({
            "event": "claim_escrow_shortfall",
            "market_id": str(market.id),
            "market_slug": slug,
            "user_id": str(user.id),
            "owed": float(payout),
            "available": float(available),
            "pool_exists": pool is not None,
        }))
        raise ValidationError(
            "This claim cannot be paid in full right now — the market escrow is "
            "underfunded. Your position is untouched; try again later or "
            "contact support.",
            error_code="ESCROW_INSUFFICIENT",
        )

    # Mark as settled atomically — prevents double-claim on client retry
    winning_pos.settled_at = Decimal(str(int(datetime.now(UTC).timestamp())))
    pool.debit_collateral(payout)   # strict: proved coverable, must not race away
    wallet.balance += payout
    winning_pos.realized_pnl += payout
    winning_pos.shares_held = Decimal(0)

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
    return success_response({"claimed": str(payout)}, message="Winnings claimed")
