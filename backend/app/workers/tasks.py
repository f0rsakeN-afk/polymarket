import asyncio
import json
import logging
import secrets
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from celery import shared_task
from sqlalchemy import delete, select, text

from app.amm.engine import BinaryAMM
from app.api.exceptions import ValidationError
from app.config import settings
from app.database import async_session
from app.deps import hash_password
from app.models import (
    LiquidityPool,
    LPShare,
    Market,
    Order,
    Outcome,
    Position,
    PriceHistory,
    RefreshToken,
    Session,
    Trade,
    Transaction,
    User,
    Wallet,
)
from app.models.liquidity import EscrowShortfallError
from app.services.liquidity_service import LiquidityService
from app.services.market_service import MarketService
from app.services.matching_engine import MatchingEngine
from app.services.order_service import OrderService
from app.websocket.manager import redis_pubsub

logger = logging.getLogger("PredictX")

# Thread-local event loops • each Celery thread gets its own loop, reused across tasks
_thread_local = threading.local()


def _is_retryable_email_error(exc: BaseException) -> bool:
    """Whether retrying an email send could plausibly succeed.

    A bad API key, a missing key, or a validation error is a configuration or
    caller fault: identical on every attempt. Only a rate limit or a
    server-side fault clears on its own, so only those are worth a retry.

    SMTP is checked by class name rather than by import, so this stays a pure
    function with no dependency on which transport happens to be configured.
    """
    # Resend distinguishes these itself; fall back to the class name so a
    # version without the subclasses still classifies correctly.
    name = type(exc).__name__

    # Resend has its own rate-limit subclass; the class-name check below covers
    # it too, so no import is needed here (and no dependency on resend being
    # installed for this function to work).

    # smtplib: every SMTPException subclass carries smtp_code, and they all
    # inherit OSError - so this must be checked before the OSError branch below,
    # or a permanent auth failure (535) would look like a dropped connection.
    # Transient: 421 (service unavailable), 450/451 (busy), 452 (out of
    # storage), and any 4xx (temporary local failure). 5xx is not: 535 is a
    # rejected credential and 552 is a full mailbox, neither of which clears.
    if "SMTP" in name and hasattr(exc, "smtp_code"):
        code = exc.smtp_code
        if code in {421, 450, 451, 452}:
            return True
        return isinstance(code, int) and 400 <= code < 500

    if name == "RateLimitError":
        return True

    # ResendError and its subclasses (ApplicationError, ValidationError,
    # InvalidApiKeyError, ...) all carry the HTTP code. Matching on the class
    # name alone would miss the subclasses, whose names do not contain
    # "ResendError" - so check the whole MRO.
    if any(cls.__name__ == "ResendError" for cls in type(exc).__mro__):
        code = getattr(exc, "code", None)
        try:
            code_int = int(code)
        except (TypeError, ValueError):
            # No usable code. A rate limit is worth one retry on the strength of
            # its name alone; anything else is an unknown fault, and guessing
            # "retryable" is what produced the traceback flood.
            return name == "RateLimitError"
        # 429 and 5xx are transient; 401/403/422 fail identically forever.
        return code_int == 429 or 500 <= code_int < 600

    # Connection-level errors: the host blipped, retrying is reasonable.
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True

    return False


def celery_run(coro):
    """
    Run a coroutine from a Celery thread.

    Each thread maintains its own event loop in thread-local storage.
    Loops are reused across tasks on the same thread and closed on thread shutdown.
    """
    loop = getattr(_thread_local, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        _thread_local.loop = loop
    return loop.run_until_complete(coro)


def get_session():
    """Fresh AsyncSession from the shared pooled session factory.

    Note: ``async_session_maker`` is the cached sessionmaker *getter* • calling
    it returns the maker itself, not a session (``async with`` on it raises
    TypeError). ``app.database.async_session()`` returns an actual session
    bound to the pooled engine and honours the test-session patching in
    tests/conftest.py, so it is the correct entry point here.
    """
    return async_session()


@shared_task(bind=True, name="app.workers.tasks.expire_stale_orders")
def expire_stale_orders(self):
    """Cancel limit orders that have passed their expiry time."""
    task_id = uuid.uuid4().hex
    logger.info(json.dumps({
        "event": "task_start",
        "task_id": task_id,
        "task_name": self.name,
    }))
    start = time.perf_counter()
    result = None
    try:
        async def _run():
            from app.services.cache_service import cache_invalidate_orderbook

            async with get_session() as db:
                # Batched: one giant FOR UPDATE sweep would lock every expirable
                # order row and balloon the transaction. SKIP LOCKED lets a
                # concurrent executor keep working while we drain in chunks.
                expired_count = 0
                expired_by_market: dict[str, list] = {}
                while True:
                    now = datetime.now(UTC)
                    result = await db.execute(
                        select(Order).where(
                            Order.order_type.in_(["limit", "fill_or_kill"]),
                            Order.status.in_(["pending", "partial"]),
                            Order.expires_at <= now,
                        ).with_for_update(skip_locked=True).limit(500)
                    )
                    orders = result.scalars().all()
                    if not orders:
                        break

                    for order in orders:
                        order.status = "expired"
                        order.executed_at = datetime.now(UTC)
                        # Only BUY orders lock funds; remaining_amount is the
                        # unspent USDC remainder, so release exactly that.
                        if order.side == "buy":
                            wallet_result = await db.execute(
                                select(Wallet).where(Wallet.user_id == order.user_id).with_for_update()
                            )
                            wallet = wallet_result.scalar_one_or_none()
                            if wallet:
                                wallet.locked_balance = max(wallet.locked_balance - order.remaining_amount, 0)
                        expired_count += 1
                        expired_by_market.setdefault(str(order.market_id), []).append(order)

                    await db.commit()

                if not expired_count:
                    return "No orders to expire"

                # Notify WebSocket clients • all publishes run concurrently
                await asyncio.gather(
                    *[
                        redis_pubsub.publish_market_event(
                            str(order.market_id), "order:expired", {"order_id": str(order.id)}
                        )
                        for batch in expired_by_market.values()
                        for order in batch
                    ],
                    return_exceptions=True,
                )
                for market_id in expired_by_market:
                    await cache_invalidate_orderbook(market_id)

                return f"Expired {expired_count} orders"

        result = celery_run(_run())
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(json.dumps({
            "event": "task_complete",
            "task_id": task_id,
            "task_name": self.name,
            "duration_ms": round(duration_ms, 2),
            "result": str(result)[:200],
        }))
    return result


@shared_task(bind=True, name="app.workers.tasks.check_limit_order_execution")
def check_limit_order_execution(self):
    """Check pending/partial limit orders and execute those whose price condition is met."""
    task_id = uuid.uuid4().hex
    logger.info(json.dumps({
        "event": "task_start",
        "task_id": task_id,
        "task_name": self.name,
    }))
    start = time.perf_counter()
    result = None
    try:
        async def _run():
            from app.services.alert_engine import pop_dirty_markets

            async with get_session() as db:
                # Only markets whose price moved can have newly fillable orders.
                # AMM prices change exclusively on trade, and every trade marks
                # its market dirty • so an empty dirty set means zero work.
                # None = Redis unavailable -> fall back to the full scan.
                dirty = await pop_dirty_markets()
                if dirty is not None and not dirty:
                    return "No price moves since last check"

                now = datetime.now(UTC)
                query = select(Order).where(
                    Order.order_type.in_(["limit", "fill_or_kill"]),
                    Order.status.in_(["pending", "partial"]),
                    Order.remaining_amount > 0,
                )
                if dirty:
                    query = query.where(Order.market_id.in_(dirty))
                # SKIP LOCKED: a concurrent placement/trade holding some of
                # these rows doesn't stall the whole sweep; leftovers are
                # picked up next minute.
                result = await db.execute(query.with_for_update(skip_locked=True))
                orders = result.scalars().all()

                if not orders:
                    return "No executable orders"

                executed = 0

                # Group orders by market • one market/pool lock per group instead of per order
                by_market: dict[str, list] = {}
                for order in orders:
                    by_market.setdefault(str(order.market_id), []).append(order)

                for market_id, market_orders in by_market.items():
                    # Per-market fault isolation: one market's failure rolls back
                    # only its own group and never aborts the rest of the run.
                    # The group-boundary commit also releases market/pool locks
                    # promptly instead of holding them across all markets.
                    market_fills = 0
                    try:
                        market_result = await db.execute(
                            select(Market).where(Market.id == market_id).with_for_update()
                        )
                        market = market_result.scalar_one_or_none()
                        if not market or market.status != "active":
                            await db.rollback()
                            continue

                        outcomes_result = await db.execute(
                            select(Outcome)
                            .where(Outcome.market_id == market.id)
                            .order_by(Outcome.outcome_index)
                        )
                        all_outcomes = list(outcomes_result.scalars().all())
                        parimutuel = MarketService.is_parimutuel(all_outcomes)

                        # The pool and AMM are resolved PER ORDER below, keyed on
                        # the order's outcome. A market-level lookup used to be
                        # safe because market_id was UNIQUE; with per-outcome rows
                        # it raises MultipleResultsFound, and picking one pool
                        # would fill orders in other outcomes against it.

                        for order in market_orders:
                            # Re-lock the individual order row
                            re_lock_result = await db.execute(
                                select(Order).where(Order.id == order.id).with_for_update()
                            )
                            re_locked_order = re_lock_result.scalar_one_or_none()
                            if not re_locked_order or re_locked_order.status not in ("pending", "partial"):
                                continue

                            if re_locked_order.expires_at and re_locked_order.expires_at <= now:
                                re_locked_order.status = "expired"
                                re_locked_order.executed_at = now
                                if re_locked_order.side == "buy":
                                    wallet = await db.execute(
                                        select(Wallet).where(Wallet.user_id == re_locked_order.user_id).with_for_update()
                                    )
                                    wallet = wallet.scalar_one_or_none()
                                    if wallet:
                                        wallet.locked_balance = max(wallet.locked_balance - re_locked_order.remaining_amount, 0)
                                await db.commit()
                                continue

                            outcome = await db.get(Outcome, re_locked_order.outcome_id)
                            if not outcome:
                                continue

                            try:
                                pool = await OrderService._resolve_pool(
                                    db, market, outcome, parimutuel, lock=True
                                )
                            except ValidationError:
                                continue

                            # Resolve the AMM side explicitly. The engine selects
                            # its reserve with a literal `outcome == "yes"`, so
                            # passing a raw name routed every outcome that was
                            # not "yes" into the NO reserve.
                            amm_side: str | None = "yes"
                            outcome_amm = None
                            market_total = None
                            if parimutuel:
                                # Built over ALL outcome pools so `total` is the
                                # market total and the complement is correct.
                                outcome_amm, market_total = (
                                    MarketService.build_outcome_amm(
                                        await MarketService.load_outcome_pools(
                                            db, market.id
                                        ),
                                        outcome.id,
                                    )
                                )
                            else:
                                amm_side = (
                                    "yes" if outcome.name.lower() == "yes" else "no"
                                )

                            order_side = re_locked_order.side
                            order_amount = re_locked_order.remaining_amount
                            limit_price = re_locked_order.price

                            remaining_after_book, book_matches = await MatchingEngine.match_pending_order(
                                db, re_locked_order, market, outcome,
                            )

                            remaining = remaining_after_book
                            amm_shares = Decimal(0)
                            amm_price_val = Decimal(0)
                            amm_fee = Decimal(0)
                            sell_proceeds_amm = Decimal(0)

                            # An AMM leg exists for every market now that a parimutuel one is
                            # priced from its own outcome pools. Decided by whether
                            # the AMM above could be built, not by outcome count.
                            if remaining > 0 and amm_side is not None:
                                 amm = outcome_amm or BinaryAMM(
                                     yes_shares=pool.yes_shares,
                                     no_shares=pool.no_shares,
                                     fee_rate=pool.fee_rate,
                                 )

                                 current_price = float(amm.price(amm_side))
                                 limit_price_f = float(limit_price)

                                 if order_side == "buy":
                                     can_fill = current_price <= limit_price_f
                                 else:
                                     can_fill = current_price >= limit_price_f

                                 if not can_fill:
                                     if re_locked_order.status != "filled":
                                         await db.commit()
                                     continue

                                 wallet = await db.execute(
                                     select(Wallet).where(Wallet.user_id == re_locked_order.user_id).with_for_update()
                                 )
                                 wallet = wallet.scalar_one_or_none()
                                 if not wallet:
                                     continue

                                 if order_side == "buy":
                                     # Available balance, not total: locked limit funds
                                     # must not be double-spent by a second fill.
                                     if wallet.balance - wallet.locked_balance < remaining:
                                         continue
                                     quote = amm.buy(amm_side, remaining)
                                     wallet.balance -= remaining
                                     # Escrow the spend: it funds the shares the
                                     # AMM just minted (single-entry ledger).
                                     pool.credit_collateral(remaining)
                                     amm_shares = quote.shares_out
                                     amm_price_val = quote.price
                                     amm_fee = quote.fee

                                     if wallet.locked_balance > 0:
                                         wallet.locked_balance = max(wallet.locked_balance - remaining, 0)

                                     pos_result = await db.execute(
                                         select(Position).where(
                                             Position.user_id == re_locked_order.user_id,
                                             Position.market_id == market.id,
                                             Position.outcome_id == outcome.id,
                                         ).with_for_update()
                                     )
                                     pos = pos_result.scalar_one_or_none()
                                     if pos:
                                         total_shares_pos = pos.shares_held + amm_shares
                                         if total_shares_pos > 0:
                                             pos.average_price = (
                                                 pos.average_price * pos.shares_held + remaining
                                             ) / total_shares_pos
                                         pos.shares_held = total_shares_pos
                                     else:
                                         avg_price = remaining / amm_shares if amm_shares > 0 else Decimal(0)
                                         # Upsert: INSERT ON CONFLICT DO UPDATE • atomic, no race between SELECT and INSERT
                                         await db.execute(
                                             text("""
                                                 INSERT INTO positions (id, user_id, market_id, outcome_id, shares_held, average_price, realized_pnl, settled_at, created_at, updated_at)
                                                 VALUES (gen_random_uuid(), :user_id, :market_id, :outcome_id, :shares_held, :average_price, 0, NULL, NOW(), NOW())
                                                 ON CONFLICT (user_id, market_id, outcome_id)
                                                 DO UPDATE SET shares_held = positions.shares_held + EXCLUDED.shares_held,
                                                              average_price = (positions.average_price * positions.shares_held + EXCLUDED.average_price * EXCLUDED.shares_held) / (positions.shares_held + EXCLUDED.shares_held)
                                             """),
                                             {
                                                 "user_id": re_locked_order.user_id,
                                                 "market_id": market.id,
                                                 "outcome_id": outcome.id,
                                                 "shares_held": amm_shares,
                                                 "average_price": avg_price,
                                             }
                                         )

                                     market.total_volume += remaining
                                     market.num_trades += 1
                                 else:
                                     pos_result = await db.execute(
                                         select(Position).where(
                                             Position.user_id == re_locked_order.user_id,
                                             Position.market_id == market.id,
                                             Position.outcome_id == outcome.id,
                                         ).with_for_update()
                                     )
                                     pos = pos_result.scalar_one_or_none()
                                     if not pos or pos.shares_held < remaining:
                                         continue

                                     quote = amm.sell(amm_side, remaining)
                                     cost_basis = pos.average_price * remaining
                                     sell_proceeds_amm = quote.collateral_in
                                     realized_pnl = sell_proceeds_amm - cost_basis
                                     pos.shares_held -= remaining
                                     pos.realized_pnl += realized_pnl
                                     wallet.balance += sell_proceeds_amm
                                     # Shares in, dollars out of the escrow.
                                     # Strict: a shortfall rolls the fill back.
                                     pool.debit_collateral(sell_proceeds_amm)
                                     amm_shares = remaining
                                     amm_price_val = quote.price
                                     amm_fee = quote.fee

                                     market.total_volume += remaining
                                     market.num_trades += 1

                                 trade_value = remaining * amm_price_val
                                 protocol_fee = trade_value * settings.protocol_fee_rate
                                 pool.protocol_fees += protocol_fee

                                 pool.yes_shares = amm.yes_shares
                                 if not parimutuel:
                                     # Binary only. On a parimutuel outcome
                                     # no_shares is a derived complement, not
                                     # stored state, so writing it back would
                                     # put a real number where there is none.
                                     pool.no_shares = amm.no_shares

                                 re_locked_order.remaining_amount -= remaining
                                 if re_locked_order.remaining_amount <= 0:
                                     re_locked_order.status = "filled"
                                     re_locked_order.executed_at = now
                                 elif re_locked_order.status != "filled":
                                     re_locked_order.status = "partial"

                                 re_locked_order.shares_bought = amm_shares if order_side == "buy" else None
                                 re_locked_order.shares_sold = amm_shares if order_side == "sell" else None
                                 re_locked_order.fees_paid = (re_locked_order.fees_paid or Decimal(0)) + amm_fee

                                 trade = Trade(
                                     user_id=re_locked_order.user_id,
                                     market_id=market.id,
                                     outcome=outcome.name.lower(),
                                     side=order_side,
                                     price=amm_price_val,
                                     amount=remaining,
                                     executed_at=now,
                                 )
                                 db.add(trade)

                                 trade_amount = -remaining if order_side == "buy" else sell_proceeds_amm  # Decimal, no float (H10 fix)
                                 tx = Transaction(
                                     user_id=re_locked_order.user_id,
                                     wallet_id=wallet.id,
                                     type="trade_buy" if order_side == "buy" else "trade_sell",
                                     amount=trade_amount,
                                     balance_after=wallet.balance,
                                     reference_id=str(re_locked_order.id),
                                     reference_type="order",
                                     status="completed",
                                 )
                                 db.add(tx)

                        if re_locked_order.status in ("filled", "partial"):
                            await db.commit()

                            if re_locked_order.status == "filled":
                                if parimutuel:
                                    # A binary yes/no pair says nothing about any
                                    # outcome, so publish a real price per
                                    # outcome taken from the pools. Without it
                                    # the front end has nothing to draw the extra
                                    # chart lines from and they sit frozen.
                                    outcome_prices = MarketService.outcome_prices(
                                        await MarketService.load_outcome_pools(
                                            db, market.id
                                        )
                                    )
                                    by_id = {
                                        str(o.id): o.name for o in all_outcomes
                                    }
                                    yes_price = float(
                                        outcome_prices.get(str(outcome.id), 0)
                                    )
                                    no_price = 1 - yes_price
                                else:
                                    total = pool.yes_shares + pool.no_shares
                                    yes_price = float(pool.yes_shares / total) if total > 0 else 0.5
                                    no_price = float(pool.no_shares / total) if total > 0 else 0.5
                                try:
                                    from app.websocket.manager import redis_pubsub
                                    await redis_pubsub.publish_price_update(
                                        str(market.id), yes_price, no_price,
                                        float(market.total_volume),
                                        outcome_prices=(
                                            {by_id[k]: float(v) for k, v in outcome_prices.items() if k in by_id}
                                            if parimutuel else None
                                        ),
                                    )
                                    check_price_alerts.delay(str(market.id), yes_price, no_price)
                                    await redis_pubsub.publish_order_fill(str(re_locked_order.user_id), {
                                        "order_id": str(re_locked_order.id),
                                        "market_id": str(market.id),
                                        "status": re_locked_order.status,
                                        "side": order_side,
                                        "shares": float(order_amount) - float(remaining),
                                        "price": float(amm_price_val) if amm_price_val > 0 else float(re_locked_order.price),
                                    })
                                    # Also dispatch in-app notification
                                    from app.services.notification_service import (
                                        NotificationService,
                                    )
                                    await NotificationService.dispatch(
                                        db, str(re_locked_order.user_id), "order_filled",
                                        f"Order filled: {order_side} {float(order_amount - remaining):.2f} shares",
                                        f"Your {re_locked_order.status} order on {market.slug} has been filled.",
                                        {"order_id": str(re_locked_order.id), "market_id": str(market.id), "side": order_side}
                                    )
                                    # Publish position:update for real-time UI refresh
                                    await redis_pubsub.publish_notification(str(re_locked_order.user_id), {
                                        "type": "position:update",
                                        "market_id": str(market.id),
                                        "outcome": outcome.name if outcome else None,
                                        "shares": float(order_amount) - float(remaining),
                                        "side": order_side,
                                    })
                                except Exception:
                                    pass

                                executed += 1
                                market_fills += 1

                        await db.commit()
                    except Exception:
                        await db.rollback()
                        logger.exception(f"Limit executor failed for market {market_id} • continuing")
                        continue

                    if market_fills:
                        # Rebuild + push the book once per market with fills,
                        # same contract as the placement path (cache + event).
                        try:
                            from app.services.cache_service import (
                                build_orderbook,
                                cache_set_orderbook,
                            )
                            book = await build_orderbook(db, market_id)
                            await cache_set_orderbook(market_id, book, ttl=60)
                            await redis_pubsub.publish_market_event(
                                market_id, "orderbook:update", book
                            )
                        except Exception:
                            pass

                        # These fills moved the price again, so an order the
                        # current sweep already passed over may now be
                        # fillable. Re-arm the sweep instead of leaving that
                        # cascade for the next 30s beat tick • throttled to
                        # one enqueue per second, so it cannot loop hot.
                        try:
                            from app.services.order_service import (
                                _enqueue_limit_sweep_now,
                            )
                            await _enqueue_limit_sweep_now()
                        except Exception:
                            pass

                return f"Executed {executed}/{len(orders)} limit orders"

        result = celery_run(_run())
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(json.dumps({
            "event": "task_complete",
            "task_id": task_id,
            "task_name": self.name,
            "duration_ms": round(duration_ms, 2),
            "result": str(result)[:200],
        }))
    return result


@shared_task(bind=True, name="app.workers.tasks.sync_amm_prices")
def sync_amm_prices(self):
    """Sync AMM prices from DB to Redis for fast reads.
    Only publishes WS updates when prices actually changed to avoid
    unnecessary network traffic and client-side chart redraws.
    """
    task_id = uuid.uuid4().hex
    logger.info(json.dumps({
        "event": "task_start",
        "task_id": task_id,
        "task_name": self.name,
    }))
    start = time.perf_counter()
    result = None
    try:
        async def _run():
            from app.models import Market
            from app.redis import get_redis
            from app.websocket.manager import redis_pubsub

            async with get_session() as db:
                # Markets only, not a Market x Pool join. A parimutuel market
                # has one pool per outcome, so the join fanned a single market
                # out into N rows and each pass wrote the same cache key.
                result = await db.execute(
                    select(Market).where(Market.status == "active")
                )
                markets = list(result.scalars().all())
                # (market, yes_price, no_price, per-outcome prices or None)
                priced = []
                for market in markets:
                    pool = await MarketService.load_binary_pool(db, market.id)
                    if pool is not None:
                        total = pool.yes_shares + pool.no_shares
                        if total > 0:
                            priced.append(
                                (market, float(pool.yes_shares / total),
                                 float(pool.no_shares / total), None)
                            )
                        else:
                            priced.append((market, 0.5, 0.5, None))
                        continue

                    # Parimutuel: the cached yes/no pair becomes the leading
                    # outcome versus the rest, and the real per-outcome prices
                    # are stored alongside so the chart can draw every line.
                    per_outcome = MarketService.outcome_prices(
                        await MarketService.load_outcome_pools(db, market.id)
                    )
                    if not per_outcome:
                        priced.append((market, 0.5, 0.5, None))
                        continue
                    lead = max(per_outcome.values())
                    names = {
                        str(o.id): o.name
                        for o in (
                            await db.execute(
                                select(Outcome).where(Outcome.market_id == market.id)
                            )
                        ).scalars().all()
                    }
                    priced.append((
                        market, float(lead), float(Decimal(1) - lead),
                        {names[k]: float(v) for k, v in per_outcome.items() if k in names},
                    ))

            if not priced:
                return "No active markets"

            r = await get_redis()
            pipe = r.pipeline()

            for market, yes_price, no_price, outcome_prices in priced:

                key = f"market:{market.id}:price"
                # Check if prices actually changed before updating.
                # This avoids unnecessary WS fan-out when prices haven't moved.
                cached = await r.hgetall(key)
                prev_yes = float(cached.get(b"yes_price", b"0.5")) if cached else 0.5
                prev_no = float(cached.get(b"no_price", b"0.5")) if cached else 0.5
                price_changed = (abs(yes_price - prev_yes) > 0.0001 or
                                 abs(no_price - prev_no) > 0.0001)

                pipe.hset(key, mapping={
                    "yes_price": str(yes_price),
                    "no_price": str(no_price),
                    "updated_at": datetime.now(UTC).isoformat(),
                })
                pipe.expire(key, 300)  # 5 min TTL

                # Only push WS updates when prices actually changed.
                if price_changed:
                    await redis_pubsub.publish_price_update(
                        str(market.id), yes_price, no_price,
                        float(market.total_volume),
                        outcome_prices=outcome_prices)

            await pipe.execute()
            return f"Synced prices for {len(markets)} markets"

        result = celery_run(_run())
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(json.dumps({
            "event": "task_complete",
            "task_id": task_id,
            "task_name": self.name,
            "duration_ms": round(duration_ms, 2),
            "result": str(result)[:200],
        }))
    return result


@shared_task(bind=True, name="app.workers.tasks.snapshot_price_history")
def snapshot_price_history(self):
    """Snapshot current prices to price_history table for charting.
    Deduplicates: skips snapshots that already exist for the current
    minute window to prevent duplicate entries on task retries.
    """
    task_id = uuid.uuid4().hex
    logger.info(json.dumps({
        "event": "task_start",
        "task_id": task_id,
        "task_name": self.name,
    }))
    start = time.perf_counter()
    result = None
    try:
        async def _run():
            async with get_session() as db:
                # Markets only: the old Market x Pool join fanned a parimutuel
                # market out into one row per outcome, snapshotting it N times.
                result = await db.execute(
                    select(Market).where(Market.status == "active")
                )
                markets = list(result.scalars().all())

                if not markets:
                    return "No active markets"

                market_ids = [m.id for m in markets]
                outcomes_result = await db.execute(
                    select(Outcome).where(Outcome.market_id.in_(market_ids))
                )
                outcomes = outcomes_result.scalars().all()
                outcomes_by_market: dict = {}
                for o in outcomes:
                    outcomes_by_market.setdefault(o.market_id, []).append(o)

                now = datetime.now(UTC)
                # Dedup: check which market/outcome combinations already
                # have a snapshot for this minute window.
                minute_floor = now.replace(second=0, microsecond=0)
                existing_result = await db.execute(
                    select(PriceHistory.market_id, PriceHistory.outcome_id).where(
                        PriceHistory.snapshot_at >= minute_floor,
                        PriceHistory.snapshot_at < minute_floor + timedelta(minutes=1),
                    ).distinct()
                )
                existing_pairs = {(r[0], r[1]) for r in existing_result.scalars().all()}

                snapshots = []
                for market in markets:
                    market_outcomes = outcomes_by_market.get(market.id, [])
                    if not market_outcomes:
                        continue

                    binary = await MarketService.load_binary_pool(db, market.id)
                    if binary is not None:
                        total = binary.yes_shares + binary.no_shares
                        yes_price = binary.yes_shares / total if total > 0 else Decimal("0.5")
                        no_price = binary.no_shares / total if total > 0 else Decimal("0.5")
                        prices = {
                            str(o.id): (
                                yes_price if o.name.lower() == "yes" else no_price
                            )
                            for o in market_outcomes
                        }
                    else:
                        # Parimutuel: each outcome's real share of the market
                        # total. This used to write a flat 1/N for every outcome,
                        # which drew N identical overlapping lines and made the
                        # chart look frozen.
                        prices = MarketService.outcome_prices(
                            await MarketService.load_outcome_pools(db, market.id)
                        )
                        if not prices:
                            even = Decimal(1) / Decimal(str(len(market_outcomes)))
                            prices = {str(o.id): even for o in market_outcomes}

                    for o in market_outcomes:
                        if (market.id, o.id) in existing_pairs:
                            continue  # Skip duplicate snapshot
                        price = prices.get(str(o.id))
                        if price is None:
                            continue
                        snapshots.append(PriceHistory(
                            market_id=market.id,
                            outcome_id=o.id,
                            price=price,
                            total_volume=market.total_volume,
                            snapshot_at=now,
                        ))

                if snapshots:
                    db.add_all(snapshots)
                    await db.commit()
                return f"Snapshotted {len(snapshots)} price records for {len(markets)} markets"

        result = celery_run(_run())
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(json.dumps({
            "event": "task_complete",
            "task_id": task_id,
            "task_name": self.name,
            "duration_ms": round(duration_ms, 2),
            "result": str(result)[:200],
        }))
    return result

@shared_task(bind=True, name="app.workers.tasks.check_markets_ready_to_resolve")
def check_markets_ready_to_resolve(self):
    """Close markets that have passed their close time but are not yet resolved."""
    task_id = uuid.uuid4().hex
    logger.info(json.dumps({
        "event": "task_start",
        "task_id": task_id,
        "task_name": self.name,
    }))
    start = time.perf_counter()
    result = None
    try:
        async def _run():
            async with get_session() as db:
                now = datetime.now(UTC)
                result = await db.execute(
                    select(Market).where(
                        Market.status == "active",
                        Market.closes_at <= now,
                        Market.winning_outcome_id.is_(None),
                    )
                )
                markets = result.scalars().all()
                if not markets:
                    return "No markets ready to close"

                for market in markets:
                    market.status = "closed"
                    logger.warning(f"Market {market.slug} ({market.id}) closed • awaiting resolution")

                await db.commit()
                return f"Closed {len(markets)} markets"

        result = celery_run(_run())
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(json.dumps({
            "event": "task_complete",
            "task_id": task_id,
            "task_name": self.name,
            "duration_ms": round(duration_ms, 2),
            "result": str(result)[:200],
        }))
    return result


async def settle_market(market_id: str, winning_outcome_id: str, task_id: str = "") -> str:
    """Settle one market: pay winners from escrow, sweep protocol fees, redeem LP shares.

    Module-level coroutine rather than a nested `_run()` so it can be awaited
    directly on the caller's event loop • Celery's `celery_run()` needs a
    thread with no running loop, which never exists inside an async test.
    """
    async with get_session() as db:
        from app.redis import get_redis
        r = await get_redis()

        # Finished-marker • written only after a successful settlement
        # commit. Status can't be used as the "already settled" signal:
        # both enqueueing callers set `resolving`/`resolved` *before*
        # the worker starts, which is exactly why the old guard
        # (`if status in ("resolving", "resolved"): return`) skipped
        # every single settlement • winners were never credited, LP
        # shares were never redeemed, protocol fees were never swept,
        # and markets stayed in "resolving" where claim_winnings
        # refuses to pay (it requires "resolved").
        if await r.exists(f"resolve_done:{market_id}"):
            return f"Market {market_id} already settled"

        # Lock market row to prevent concurrent resolution
        market_result = await db.execute(
            select(Market).where(Market.id == market_id).with_for_update()
        )
        market = market_result.scalar_one_or_none()
        if not market:
            return f"Market {market_id} not found"

        # Settle only against the outcome recorded on the market row.
        # A stale delivery (market re-resolved through the dispute
        # flow) must not settle against a superseded proposal.
        if not market.winning_outcome_id:
            return f"Market {market_id} has no winning outcome • refusing to settle"
        if str(market.winning_outcome_id) != str(winning_outcome_id):
            logger.warning(json.dumps({
                "event": "settlement_outcome_mismatch",
                "market_id": market_id,
                "expected": str(winning_outcome_id),
                "recorded": str(market.winning_outcome_id),
            }))
            return f"Market {market_id} outcome mismatch • stale settlement task dropped"

        # Scoped to the WINNING outcome's pool, falling back to the market's single
        # binary pool. A parimutuel market has one pool per outcome, so the old
        # market_id-only lookup raised MultipleResultsFound - and paying winners
        # out of whichever pool came first would move one outcome's escrow to
        # cover another's payout. A binary market also has winning_outcome_id
        # set but stores its reserve in the NULL-outcome pool.
        pool_result = await db.execute(
            select(LiquidityPool)
            .where(
                LiquidityPool.market_id == market.id,
                LiquidityPool.outcome_id == winning_outcome_id,
            )
            .with_for_update()
        )
        pool = pool_result.scalar_one_or_none()
        if pool is None:
            pool_result = await db.execute(
                select(LiquidityPool)
                .where(
                    LiquidityPool.market_id == market.id,
                    LiquidityPool.outcome_id.is_(None),
                )
                .with_for_update()
            )
            pool = pool_result.scalar_one_or_none()

        # Get or create system treasury user with row lock to prevent concurrent creation.
        # System users use a cryptographically random password_hash derived from
        # the application's JWT secret • they cannot be used for human authentication.
        treasury_result = await db.execute(
            select(User).where(User.is_system).with_for_update().limit(1)
        )
        treasury_user = treasury_result.scalar_one_or_none()
        if not treasury_user:
            system_secret = settings.jwt_secret + str(secrets.token_hex(32))
            treasury_user = User(
                email="treasury@system",
                username="treasury",
                password_hash=hash_password(system_secret),
                is_system=True,
                is_active=True,
            )
            db.add(treasury_user)
            await db.flush()

        # Get or create treasury wallet
        treasury_wallet_result = await db.execute(
            select(Wallet).where(Wallet.user_id == treasury_user.id).with_for_update()
        )
        treasury_wallet = treasury_wallet_result.scalar_one_or_none()
        if not treasury_wallet:
            treasury_wallet = Wallet(
                user_id=treasury_user.id,
                balance=Decimal(0),
                locked_balance=Decimal(0),
                currency="USDC",
            )
            db.add(treasury_wallet)
            await db.flush()

        # Settle positions • lock only unsettled rows to prevent double settlement with claim_winnings (C9 fix)
        pos_result = await db.execute(
            select(Position)
            .where(Position.market_id == market.id, Position.settled_at.is_(None))
            .with_for_update()
        )
        positions = pos_result.scalars().all()

        # Batch-fetch all wallets upfront • O(1) query vs O(n) inside the loop
        user_ids = list({str(p.user_id) for p in positions})
        if user_ids:
            wallets_result = await db.execute(
                select(Wallet).where(Wallet.user_id.in_(user_ids)).with_for_update()
            )
            wallet_map = {str(w.user_id): w for w in wallets_result.scalars().all()}
        else:
            wallet_map = {}

        # ── Pre-flight: can the escrow fund the WHOLE obligation? ──
        # Checked once, up front, before a single wallet is touched. Paying
        # per-position and reacting to a shortfall part-way through is what
        # used to happen: the first winners were paid in full, the last one
        # got whatever was left, and *every* position was still stamped
        # settled • so the remainder was owed to nobody and reachable by
        # nobody. A shortfall can only mean the ledger upstream is broken, so
        # the correct response is to abort the whole settlement, leave every
        # position claimable, and surface it loudly.
        winner_total = sum(
            (Decimal(str(pos.shares_held)) for pos in positions
             if str(pos.outcome_id) == winning_outcome_id and Decimal(str(pos.shares_held or 0)) > 0),
            Decimal(0),
        )
        if winner_total > 0 and pool is None:
            # No pool row means no escrow to pay from. Paying here would mint
            # the winner's shares out of nothing (the old `pool is not None`
            # guard silently skipped the debit and credited the wallet anyway).
            raise EscrowShortfallError(
                f"market {market.id}: {winner_total} shares owed to winners but no "
                f"liquidity pool exists to fund them from"
            )
        owed_fees = Decimal(str(pool.protocol_fees or 0)) if pool is not None else Decimal(0)
        available = Decimal(str(pool.collateral or 0)) if pool is not None else Decimal(0)
        required = winner_total + owed_fees
        if required > available:
            logger.error(json.dumps({
                "event": "settlement_escrow_shortfall",
                "market_id": str(market.id),
                "market_slug": market.slug,
                "winners_owed": float(winner_total),
                "protocol_fees_owed": float(owed_fees),
                "required": float(required),
                "available": float(available),
                "action": "settlement_aborted_positions_left_claimable",
            }))
            raise EscrowShortfallError(
                f"market {market.id}: escrow cannot fund settlement • need {required}, "
                f"hold {available}. Positions left unsettled and claimable."
            )

        winners_credited = 0
        for pos in positions:
            # Extra guard: skip if raced with claim_winnings (defense in depth)
            if pos.settled_at is not None:
                continue
            wallet = wallet_map.get(str(pos.user_id))
            if not wallet:
                continue

            is_winner = str(pos.outcome_id) == winning_outcome_id
            # Use Decimal throughout to avoid float rounding • convert to float only at DB write
            payout: Decimal = pos.shares_held if is_winner else Decimal(0)

            # Strict debit: the pre-flight proved the escrow covers the entire
            # obligation, so a shortfall here is a bug and must fail the whole
            # settlement rather than quietly underpay.
            if payout > 0:
                pool.debit_collateral(payout)

            # Mark as settled • prevents double-claim if claim_winnings is called after Celery settles
            pos.settled_at = Decimal(str(int(datetime.now(UTC).timestamp())))

            if payout > 0:
                wallet.balance += payout
                pos.realized_pnl += payout
                tx = Transaction(
                    user_id=pos.user_id,
                    wallet_id=wallet.id,
                    type="settlement_win",
                    amount=payout,
                    balance_after=wallet.balance,
                    reference_id=str(market.id),
                    reference_type="market_settlement",
                    status="completed",
                )
            else:
                tx = Transaction(
                    user_id=pos.user_id,
                    wallet_id=wallet.id,
                    type="settlement_loss",
                    amount=0,
                    balance_after=wallet.balance,
                    reference_id=str(market.id),
                    reference_type="market_settlement",
                    status="completed",
                )
            db.add(tx)
            if is_winner:
                winners_credited += 1

        # Extract protocol fees to treasury before LP redemption.
        # The sweep is paid out of the escrow too • protocol_fees is a
        # sub-ledger inside pool.collateral, so removing the claim and
        # the backing dollars happen together.
        if pool and pool.protocol_fees > 0:
            owed_fees = Decimal(str(pool.protocol_fees))
            # Covered by the pre-flight check • strict debit fails the whole
            # settlement if it somehow isn't, rather than zeroing the fee
            # record while paying the treasury less than it recorded.
            treasury_amount = pool.debit_collateral(owed_fees)
            pool.protocol_fees = Decimal(0)
            if treasury_amount > 0:
                treasury_wallet.balance += treasury_amount
                treasury_tx = Transaction(
                    user_id=treasury_user.id,
                    wallet_id=treasury_wallet.id,
                    type="protocol_fee",
                    amount=treasury_amount,
                    balance_after=treasury_wallet.balance,
                    reference_id=str(market.id),
                    reference_type="protocol_fee",
                    status="completed",
                )
                db.add(treasury_tx)

        # Settle LP shares • lock rows to prevent concurrent LP redemption
        # NOTE: runs regardless of protocol_fees • LPs must be credited even on 0-fee markets (C1 fix)
        if pool:
            lp_result = await db.execute(
                select(LPShare).where(LPShare.pool_id == pool.id, LPShare.lp_tokens > 0).with_for_update()
            )
            lp_shares = lp_result.scalars().all()

            # LP redemption: LPs split whatever the escrow still holds
            # *after* winners and protocol fees • paid in USDC,
            # pro-rata to their lp_tokens. The old formula handed them
            # the winning side's reserve shares
            # (winning_shares / lp_token_supply), which was uncorrelated
            # with real collateral and could promise more dollars than
            # the pool held. Because this runs after the debits above,
            # the value computed here IS the residual. Decimal
            # throughout.
            lp_payout_per_token = (
                pool.collateral / pool.lp_token_supply
                if pool.lp_token_supply > 0
                else Decimal(0)
            )

            # These payouts are pro-rata of the residual, so they sum to it •
            # strict debit cannot fail, and if it ever did that would mean the
            # token supply and the share rows disagree (a real bug), so fail
            # loudly rather than underpaying an LP and burning their tokens.
            outstanding_tokens = sum(
                (Decimal(str(lp.lp_tokens or 0)) for lp in lp_shares), Decimal(0)
            )
            if outstanding_tokens > Decimal(str(pool.lp_token_supply or 0)):
                logger.error(json.dumps({
                    "event": "lp_token_supply_drift",
                    "market_id": str(market.id),
                    "share_rows_total": float(outstanding_tokens),
                    "lp_token_supply": float(pool.lp_token_supply),
                }))
                raise EscrowShortfallError(
                    f"market {market.id}: LP share rows total {outstanding_tokens} but "
                    f"lp_token_supply is {pool.lp_token_supply} • refusing to redeem"
                )

            for lp in lp_shares:
                lp_payout = Decimal(str(lp.lp_tokens or 0)) * lp_payout_per_token
                if lp_payout > 0:
                    pool.debit_collateral(lp_payout)
                wallet_result = await db.execute(
                    select(Wallet).where(Wallet.user_id == lp.user_id).with_for_update()
                )
                wallet = wallet_result.scalar_one_or_none()
                if not wallet or lp_payout <= 0:
                    continue
                wallet.balance += lp_payout
                lp.lp_tokens = 0
                tx = Transaction(
                    user_id=lp.user_id,
                    wallet_id=wallet.id,
                    type="liquidity_removal",
                    amount=lp_payout,
                    balance_after=wallet.balance,
                    reference_id=str(pool.id),
                    reference_type="lp_settlement",
                    status="completed",
                )
                db.add(tx)

        market.status = "resolved"
        if market.resolved_at is None:
            market.resolved_at = datetime.now(UTC)
        await db.commit()
        # Completion marker, written only after the settlement
        # transaction is durable: a redelivered/duplicate task
        # short-circuits above instead of re-walking the ledger.
        await r.set(f"resolve_done:{market_id}", "1", ex=60 * 60 * 24 * 30)
    return f"Settled market {market_id}: {winners_credited}/{len(positions)} positions credited"

@shared_task(
    bind=True,
    name="app.workers.tasks.resolve_market",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def resolve_market(self, market_id: str, winning_outcome_id: str):
    """
    Settle a resolved market: credit winning positions and LP shares.
    Retries up to 3 times with exponential backoff on failure.
    """
    task_id = uuid.uuid4().hex
    logger.info(json.dumps({
        "event": "task_start",
        "task_id": task_id,
        "task_name": self.name,
        "market_id": market_id,
        "winning_outcome_id": winning_outcome_id,
    }))
    start = time.perf_counter()
    lock_acquired = False
    result = None
    try:
        # ── Exclusive settlement lock ──────────────────────────────────────
        # One settlement per market at a time. Released in the `finally`
        # below on success AND on failure: the old code never released it, so
        # a crash left the lock held for its 2h TTL and every Celery retry hit
        # "already running", acked, and the market silently never settled.
        # The real correctness guarantee is DB-side • the market row lock plus
        # idempotent data (positions carry settled_at, LP shares are zeroed,
        # protocol fees are swept) • this lock only collapses duplicate work.
        # NOTE: distinct from the API enqueue dedup key (resolve_enqueue:{id}).
        from app.redis import get_redis_sync

        lock_key = f"resolve_lock:{market_id}"
        lock_acquired = bool(
            get_redis_sync().set(lock_key, str(self.request.id or task_id), nx=True, ex=7200)
        )
        if not lock_acquired:
            return f"Market {market_id} resolution task already running"


        result = celery_run(settle_market(market_id, winning_outcome_id, task_id))
    finally:
        if lock_acquired:
            # Release on every exit path (success, exception, early return) so
            # a Celery retry of a crashed run can actually acquire the lock and
            # settle instead of being told "already running" until the TTL
            # expires. Settlement is idempotent, so a duplicate run that slips
            # through pays nothing twice.
            try:
                from app.redis import get_redis_sync

                get_redis_sync().delete(lock_key)
            except Exception:
                logger.exception(f"Failed to release settlement lock for {market_id}")
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(json.dumps({
            "event": "task_complete",
            "task_id": task_id,
            "task_name": self.name,
            "duration_ms": round(duration_ms, 2),
            "result": str(result)[:200],
        }))
    return result


@shared_task(bind=True, name="app.workers.tasks.check_price_alerts")
def check_price_alerts(self, market_id: str, yes_price: float, no_price: float):
    """Check untriggered alerts when price updates and broadcast triggered ones via WebSocket."""
    task_id = uuid.uuid4().hex
    logger.info(json.dumps({
        "event": "task_start",
        "task_id": task_id,
        "task_name": self.name,
        "market_id": market_id,
        "yes_price": yes_price,
        "no_price": no_price,
    }))
    start = time.perf_counter()
    result = None
    try:
        async def _run():
            from app.services.alert_engine import (
                claim_due_alerts,
                mark_triggered,
                reindex_market_alerts,
            )

            async with get_session() as db:
                try:
                    claimed = await claim_due_alerts(market_id, yes_price, no_price)

                    if not claimed:
                        # Either nothing is due, or the index is cold/empty.
                        # Distinguish cheaply: reindex rebuilds from Postgres; if it
                        # indexed rows, evaluate them via the legacy scan once.
                        reindexed = await reindex_market_alerts(db, market_id)
                        if reindexed:
                            claimed = await claim_due_alerts(market_id, yes_price, no_price)
                        if not claimed:
                            return "No active alerts"

                    alerts = await mark_triggered(db, claimed)
                    if not alerts:
                        # Lost the race (another worker flipped them) or IDs stale.
                        return "No active alerts"

                    from app.models.market import Market
                    from app.services.notification_service import (
                        NotificationService,
                    )
                    market_result = await db.execute(select(Market).where(Market.id == market_id))
                    market = market_result.scalar_one_or_none()
                    market_slug = market.slug if market else market_id

                    triggered_count = 0
                    for alert in alerts:
                        price = yes_price if (alert.outcome == "yes" or alert.outcome is None) else no_price
                        alert.triggered_at = datetime.now(UTC)
                        triggered_count += 1
                        try:
                            await redis_pubsub.publish_notification(
                                str(alert.user_id),
                                {
                                    "type": "alert:triggered",
                                    "alert_id": str(alert.id),
                                    "market_id": market_id,
                                    "outcome": alert.outcome or "any",
                                    "condition": alert.condition,
                                    "trigger_price": alert.trigger_price,
                                    "actual_price": price,
                                },
                            )
                            # Also dispatch in-app notification
                            await NotificationService.dispatch(
                                db, str(alert.user_id), "alert_triggered",
                                f"Price alert triggered: {alert.outcome or 'price'} {alert.condition} ${alert.trigger_price:.2f}",
                                f"Your alert on {market_slug} has been triggered at ${price:.2f}.",
                                {"alert_id": str(alert.id), "market_id": market_id, "outcome": alert.outcome, "condition": alert.condition}
                            )
                        except Exception:
                            pass
                    await db.commit()
                    return f"Checked alerts, {triggered_count} triggered"
                except Exception:
                    # Crash between claim (ZREM) and commit would orphan alerts
                    # out of the index while still untriggered in Postgres.
                    # Reindex from source of truth so nothing is lost.
                    await db.rollback()
                    try:
                        await reindex_market_alerts(db, market_id)
                        await db.commit()
                    except Exception:
                        pass
                    raise

        result = celery_run(_run())
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(json.dumps({
            "event": "task_complete",
            "task_id": task_id,
            "task_name": self.name,
            "duration_ms": round(duration_ms, 2),
            "result": str(result)[:200],
        }))
    return result


@shared_task(bind=True, name="app.workers.tasks.send_email", max_retries=3, default_retry_delay=60)
def send_email(self, to_email: str, subject: str, body: str):
    """Send transactional email via Resend or Mailtrap SMTP."""
    task_id = uuid.uuid4().hex
    logger.info(json.dumps({
        "event": "task_start",
        "task_id": task_id,
        "task_name": self.name,
        "to_email": to_email,
        "subject": subject,
    }))
    start = time.perf_counter()

    # No transport configured at all. Not an error: a fresh checkout has no
    # RESEND_API_KEY, and retrying an absent key three times just produces three
    # identical tracebacks per notification.
    if not settings.smtp_host and not settings.resend_api_key:
        logger.warning(json.dumps({
            "event": "email_skipped",
            "task_id": task_id,
            "task_name": self.name,
            "to_email": to_email,
            "reason": (
                "no email transport configured - set RESEND_API_KEY or "
                "SMTP_HOST to send mail"
            ),
        }))
        return "skipped"

    try:
        if settings.smtp_host:
            # Mailtrap / SMTP fallback
            import smtplib
            from email.message import EmailMessage
            msg = EmailMessage()
            msg["From"] = settings.smtp_from_email
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.set_content(body)
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_pass)
                server.send_message(msg)
            logger.info(f"Email sent via SMTP to {to_email}: {subject}")
        else:
            # Resend
            import resend
            resend.api_key = settings.resend_api_key
            resend.Emails.send({
                "from": settings.notifications_from_email,
                "to": [to_email],
                "subject": subject,
                "text": body,
            })
            logger.info(f"Email sent via Resend to {to_email}: {subject}")
    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.error(json.dumps({
            "event": "task_error",
            "task_id": task_id,
            "task_name": self.name,
            "duration_ms": round(duration_ms, 2),
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:200],
        }))

        # Retry only what a retry can fix.
        #
        # This used to retry everything, so a bad API key - a permanent
        # configuration fault that no number of attempts resolves - burned
        # max_retries with a 60s delay between each and raised an unpicklable
        # Resend exception through Celery each time. Retryable is a rate limit
        # or a server-side fault; everything else is reported and dropped.
        if not _is_retryable_email_error(exc):
            logger.error(json.dumps({
                "event": "email_failed_permanently",
                "task_id": task_id,
                "task_name": self.name,
                "to_email": to_email,
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:200],
                "suggested_action": (
                    getattr(exc, "suggested_action", "") or
                    "check RESEND_API_KEY / SMTP settings"
                ),
            }))
            return "failed_permanently"

        raise self.retry(exc=exc)

    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(json.dumps({
        "event": "task_complete",
        "task_id": task_id,
        "task_name": self.name,
        "duration_ms": round(duration_ms, 2),
        "result": "sent",
    }))
    return "sent"


@shared_task(
    bind=True, name="app.workers.tasks.send_auth_email",
    max_retries=3, default_retry_delay=30,
)
def send_auth_email(self, email: str, purpose: str, code: str | None = None, magic_url: str | None = None):
    """
    Send an auth-related email. Purpose drives content:
    - verify    → email verification code
    - magic     → login code OR magic URL
    - resetpwd  → password reset code
    """
    task_id = uuid.uuid4().hex
    logger.info(json.dumps({
        "event": "task_start",
        "task_id": task_id,
        "task_name": self.name,
        "email": email,
        "purpose": purpose,
    }))
    start = time.perf_counter()
    try:
        if purpose == "verify":
            subject = "Your PredictX verification code"
            body = f"Your verification code is: {code}\nThis code expires in 10 minutes."
        elif purpose == "magic" and magic_url:
            subject = "Your PredictX login link"
            body = (
                f"Click this link to sign in: {magic_url}\n\n"
                f"This link expires in 15 minutes. "
                f"If you didn't request this, you can safely ignore this email."
            )
        elif purpose == "magic":
            subject = "Your PredictX login code"
            body = (
                f"Your login code is: {code}\n"
                f"This code expires in 10 minutes. "
                f"If you didn't request this, you can safely ignore this email."
            )
        elif purpose == "resetpwd":
            subject = "Your PredictX password reset code"
            body = (
                f"Your password reset code is: {code}\n"
                f"This code expires in 10 minutes. "
                f"If you didn't request this, your account is safe."
            )
        elif purpose == "exists":
            subject = "You already have a PredictX account"
            body = (
                "Someone tried to register with this email address, but an "
                "account already exists.\n\n"
                "If it was you: sign in as usual, or reset your password if "
                "you have forgotten it. If it wasn't you, no action is needed "
                "- your account and password are unchanged."
            )
        else:
            subject = "Your PredictX code"
            body = f"Your code is: {code}\nThis code expires in 10 minutes."

        send_email.delay(to_email=email, subject=subject, body=body)
        logger.info(f"Auth email prepared for {email}, purpose={purpose}")
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(json.dumps({
            "event": "task_complete",
            "task_id": task_id,
            "task_name": self.name,
            "duration_ms": round(duration_ms, 2),
            "result": "prepared",
        }))


@shared_task(bind=True, name="app.workers.tasks.enqueue_otp")
def enqueue_otp(self, email: str, purpose: str):
    """
    Store OTP in Redis and dispatch the appropriate email via the send_email task.
    Called by auth routes as a fire-and-forget Celery task.
    """
    task_id = uuid.uuid4().hex
    logger.info(json.dumps({
        "event": "task_start",
        "task_id": task_id,
        "task_name": self.name,
        "email": email,
        "purpose": purpose,
    }))
    start = time.perf_counter()
    try:
        import hashlib
        import hmac
        import secrets

        def _get_secret(e: str, p: str) -> str:
            import app.config
            base = f"{app.config.settings.jwt_secret}:{e}:{p}"
            return hashlib.sha256(base.encode()).hexdigest()[:32]

        def _hash_code(code: str, secret: str) -> str:
            return hmac.new(secret.encode(), code.encode(), hashlib.sha256).hexdigest()[:64]

        def _generate_code() -> str:
            # secrets.randbelow(10**8) gives 8-digit code (~100M combos) • cryptographically secure
            return str(secrets.randbelow(10**8)).zfill(8)

        code = _generate_code()
        secret = _get_secret(email, purpose)
        key = f"otp:{purpose}:{email}"

        # Store in Redis synchronously inside the task.
        # Hash-only: the plaintext code goes into the email body below and
        # nowhere else • see OTPService.verify_code, which re-hashes the
        # submitted code instead of reading a stored plaintext one.
        async def _store():
            from app.redis import get_redis, redis_cb
            r = await get_redis()
            await redis_cb.call(
                lambda: r.setex(key, 600, _hash_code(code, secret))
            )
        celery_run(_store())

        # Build email content based on purpose
        if purpose == "verify":
            subject = "Your PredictX verification code"
            body = f"Your verification code is: {code}\nThis code expires in 10 minutes."
        elif purpose == "magic":
            subject = "Your PredictX login code"
            body = f"Your login code is: {code}\nThis code expires in 10 minutes. If you didn't request this, you can safely ignore this email."
        elif purpose == "resetpwd":
            subject = "Your PredictX password reset code"
            body = f"Your password reset code is: {code}\nThis code expires in 10 minutes. If you didn't request this, your account is safe."
        else:
            subject = "Your PredictX code"
            body = f"Your code is: {code}\nThis code expires in 10 minutes."

        send_email.delay(to_email=email, subject=subject, body=body)
        logger.info(f"OTP enqueued for {email}, purpose={purpose}")
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(json.dumps({
            "event": "task_complete",
            "task_id": task_id,
            "task_name": self.name,
            "duration_ms": round(duration_ms, 2),
            "result": "enqueued",
        }))



@shared_task(bind=True, name="app.workers.tasks.distribute_protocol_fees")
def distribute_protocol_fees(self):
    """Distribute accumulated protocol fees from all markets to the treasury."""
    task_id = uuid.uuid4().hex
    logger.info(json.dumps({
        "event": "task_start",
        "task_id": task_id,
        "task_name": self.name,
    }))
    start = time.perf_counter()
    result = None
    try:
        async def _run():
            async with get_session() as db:
                return await LiquidityService.distribute_protocol_fees(db)

        result = celery_run(_run())
        logger.info(f"Protocol fees distributed: {result}")
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(json.dumps({
            "event": "task_complete",
            "task_id": task_id,
            "task_name": self.name,
            "duration_ms": round(duration_ms, 2),
            "result": str(result)[:200],
        }))
    return result


@shared_task(bind=True, name="app.workers.tasks.cleanup_expired_sessions")
def cleanup_expired_sessions(self):
    """
    Delete expired sessions and refresh tokens from the DB.
    Runs daily to prevent table bloat.
    """
    task_id = uuid.uuid4().hex
    logger.info(json.dumps({
        "event": "task_start",
        "task_id": task_id,
        "task_name": self.name,
    }))
    start = time.perf_counter()
    result = None
    try:
        from datetime import UTC, datetime, timedelta

        async def _run():
            async with get_session() as db:
                now = datetime.now(UTC)

                # Delete expired refresh tokens
                del_rt = await db.execute(
                    delete(RefreshToken).where(RefreshToken.expires_at < now)
                )
                rt_count = del_rt.rowcount

                # Delete expired sessions
                del_sess = await db.execute(
                    delete(Session).where(Session.expires_at < now)
                )
                sess_count = del_sess.rowcount

                # Also delete revoked sessions older than 30 days
                del_old = await db.execute(
                    delete(Session).where(
                        Session.revoked.is_(True),
                        Session.created_at < datetime.now(UTC) - timedelta(days=30),
                    )
                )
                old_count = del_old.rowcount

                await db.commit()
                return {
                    "refresh_tokens_expired": rt_count,
                    "sessions_expired": sess_count,
                    "sessions_revoked_old": old_count,
                }

        result = celery_run(_run())
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(json.dumps({
            "event": "task_complete",
            "task_id": task_id,
            "task_name": self.name,
            "duration_ms": round(duration_ms, 2),
            "result": str(result)[:200],
        }))
    return result


@shared_task(
    bind=True,
    name="app.workers.tasks.audit_escrow_invariants",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=2,
)
def audit_escrow_invariants(self):
    """Nightly check that every pool's escrow still covers what it owes.

    Settlement pre-flights the same arithmetic and refuses to run when the
    escrow is short • correct, but it only tells you at resolution. This runs
    the identical check on a schedule so a broken ledger surfaces overnight,
    naming the market, while it can still be funded or unwound.

    Reports only. It never repairs a ledger, because a repair written by
    something that doesn't fully understand the drift is how a rounding bug
    turns into a loss. Exit status is informational; violations are logged as
    structured ERRORs for alerting.
    """
    task_id = uuid.uuid4().hex
    logger.info(json.dumps({
        "event": "task_start",
        "task_id": task_id,
        "task_name": self.name,
    }))
    start = time.perf_counter()
    result = None
    try:
        async def _run():
            from app.services.escrow_audit import audit_and_report

            async with get_session() as db:
                violations = await audit_and_report(db)
                return {
                    "violations": len(violations),
                    "by_kind": {
                        kind: sum(1 for v in violations if v.kind == kind)
                        for kind in {v.kind for v in violations}
                    },
                }

        result = celery_run(_run())
        if result and result.get("violations"):
            logger.error(json.dumps({
                "event": "escrow_audit_failed",
                "task_id": task_id,
                **result,
            }))
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(json.dumps({
            "event": "task_complete",
            "task_id": task_id,
            "task_name": self.name,
            "duration_ms": round(duration_ms, 2),
            "result": str(result)[:200],
        }))
    return result
