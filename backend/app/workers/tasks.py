import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal

from celery import shared_task
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.amm.engine import BinaryAMM
from app.config import settings
from app.models import (
    Alert,
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
from app.services.liquidity_service import LiquidityService
from app.services.matching_engine import MatchingEngine
from app.websocket.manager import redis_pubsub

logger = logging.getLogger("polymarket")

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_session():
    async with async_session() as session:
        yield session


@shared_task(bind=True, name="app.workers.tasks.expire_stale_orders")
def expire_stale_orders(self):
    """Cancel limit orders that have passed their expiry time."""
    logger.info("Running expire_stale_orders")

    async def _run():
        async with async_session() as db:
            now = datetime.now(UTC)
            result = await db.execute(
                select(Order).where(
                    Order.order_type.in_(["limit", "fill_or_kill"]),
                    Order.status.in_(["pending", "partial"]),
                    Order.expires_at <= now,
                ).with_for_update()
            )
            orders = result.scalars().all()

            if not orders:
                return "No orders to expire"

            expired_ids = []
            for order in orders:
                order.status = "expired"
                order.executed_at = datetime.now(UTC)
                if order.side == "buy" and order.amount:
                    wallet_result = await db.execute(
                        select(Wallet).where(Wallet.user_id == order.user_id).with_for_update()
                    )
                    wallet = wallet_result.scalar_one_or_none()
                    if wallet:
                        wallet.locked_balance = max(wallet.locked_balance - order.amount, 0)
                expired_ids.append(str(order.id))

            await db.commit()

            # Notify WebSocket clients
            for order in orders:
                try:
                    await redis_pubsub.publish_market_event(
                        str(order.market_id), "order:expired", {"order_id": str(order.id)}
                    )
                except Exception:
                    pass

            return f"Expired {len(expired_ids)} orders"

    return asyncio.run(_run())


@shared_task(bind=True, name="app.workers.tasks.check_limit_order_execution")
def check_limit_order_execution(self):
    """Check pending/partial limit orders and execute those whose price condition is met."""
    logger.info("Running check_limit_order_execution")

    async def _run():
        async with async_session() as db:
            now = datetime.now(UTC)
            result = await db.execute(
                select(Order).where(
                    Order.order_type.in_(["limit", "fill_or_kill"]),
                    Order.status.in_(["pending", "partial"]),
                    Order.remaining_amount > 0,
                ).with_for_update()
            )
            orders = result.scalars().all()

            if not orders:
                return "No executable orders"

            executed = 0
            for order in orders:
                if order.expires_at and order.expires_at <= now:
                    order.status = "expired"
                    order.executed_at = now
                    if order.side == "buy":
                        wallet = await db.execute(
                            select(Wallet).where(Wallet.user_id == order.user_id).with_for_update()
                        )
                        wallet = wallet.scalar_one_or_none()
                        if wallet:
                            wallet.locked_balance = max(wallet.locked_balance - order.remaining_amount, 0)
                    await db.commit()
                    continue

                market_result = await db.execute(
                    select(Market).where(Market.id == order.market_id).with_for_update()
                )
                market = market_result.scalar_one_or_none()
                if not market or market.status != "active":
                    continue

                pool_result = await db.execute(
                    select(LiquidityPool).where(LiquidityPool.market_id == market.id).with_for_update()
                )
                pool = pool_result.scalar_one_or_none()
                if not pool:
                    continue

                outcome = await db.get(Outcome, order.outcome_id)
                if not outcome:
                    continue

                order_side = order.side
                order_amount = order.remaining_amount
                limit_price = order.price

                remaining_after_book, book_matches = await MatchingEngine.match_pending_order(
                    db, order, market, outcome,
                )

                remaining = remaining_after_book
                amm_shares = Decimal(0)
                amm_price_val = Decimal(0)
                amm_fee = Decimal(0)
                sell_proceeds_amm = Decimal(0)

                if remaining > 0:
                    amm = BinaryAMM(
                        yes_shares=pool.yes_shares,
                        no_shares=pool.no_shares,
                        fee_rate=pool.fee_rate,
                    )

                    current_price = float(amm.price(outcome.name.lower()))
                    limit_price_f = float(limit_price)

                    if order_side == "buy":
                        can_fill = current_price <= limit_price_f
                    else:
                        can_fill = current_price >= limit_price_f

                    if not can_fill:
                        if order.status != "filled":
                            await db.commit()
                        continue

                    wallet = await db.execute(
                        select(Wallet).where(Wallet.user_id == order.user_id).with_for_update()
                    )
                    wallet = wallet.scalar_one_or_none()
                    if not wallet:
                        continue

                    if order_side == "buy":
                        if wallet.balance < remaining:
                            continue
                        quote = amm.buy(outcome.name.lower(), remaining)
                        wallet.balance -= remaining
                        amm_shares = quote.shares_out
                        amm_price_val = quote.price
                        amm_fee = quote.fee

                        if wallet.locked_balance > 0:
                            wallet.locked_balance = max(wallet.locked_balance - remaining, 0)

                        pos_result = await db.execute(
                            select(Position).where(
                                Position.user_id == order.user_id,
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
                            pos = Position(
                                user_id=order.user_id,
                                market_id=market.id,
                                outcome_id=outcome.id,
                                shares_held=amm_shares,
                                average_price=avg_price,
                            )
                            db.add(pos)

                        market.total_volume += remaining
                        market.num_trades += 1
                    else:
                        pos_result = await db.execute(
                            select(Position).where(
                                Position.user_id == order.user_id,
                                Position.market_id == market.id,
                                Position.outcome_id == outcome.id,
                            ).with_for_update()
                        )
                        pos = pos_result.scalar_one_or_none()
                        if not pos or pos.shares_held < remaining:
                            continue

                        quote = amm.sell(outcome.name.lower(), remaining)
                        cost_basis = pos.average_price * remaining
                        sell_proceeds_amm = quote.collateral_in
                        realized_pnl = sell_proceeds_amm - cost_basis
                        pos.shares_held -= remaining
                        pos.realized_pnl += realized_pnl
                        wallet.balance += sell_proceeds_amm
                        amm_shares = remaining
                        amm_price_val = quote.price
                        amm_fee = quote.fee

                        market.total_volume += remaining
                        market.num_trades += 1

                    trade_value = remaining * amm_price_val
                    protocol_fee = trade_value * Decimal("0.01")
                    pool.protocol_fees += protocol_fee

                    pool.yes_shares = amm.yes_shares
                    pool.no_shares = amm.no_shares

                    order.remaining_amount -= remaining
                    if order.remaining_amount <= 0:
                        order.status = "filled"
                        order.executed_at = now
                    elif order.status != "filled":
                        order.status = "partial"

                    order.shares_bought = amm_shares if order_side == "buy" else None
                    order.shares_sold = amm_shares if order_side == "sell" else None
                    order.fees_paid = (order.fees_paid or Decimal(0)) + amm_fee

                    trade = Trade(
                        user_id=order.user_id,
                        market_id=market.id,
                        outcome=outcome.name.lower(),
                        side=order_side,
                        price=amm_price_val,
                        amount=remaining,
                        executed_at=now,
                    )
                    db.add(trade)

                    trade_amount = -float(remaining) if order_side == "buy" else float(sell_proceeds_amm)
                    tx = Transaction(
                        user_id=order.user_id,
                        wallet_id=wallet.id,
                        type="trade_buy" if order_side == "buy" else "trade_sell",
                        amount=trade_amount,
                        balance_after=wallet.balance,
                        reference_id=str(order.id),
                        reference_type="order",
                        status="completed",
                    )
                    db.add(tx)

                if order.status in ("filled", "partial") or remaining_after_book != order_amount:
                    await db.commit()

                    if order.status == "filled" or remaining_after_book != order_amount:
                        total = float(pool.yes_shares) + float(pool.no_shares)
                        yes_price = float(pool.no_shares) / total if total > 0 else 0.5
                        no_price = float(pool.yes_shares) / total if total > 0 else 0.5
                        try:
                            from app.websocket.manager import redis_pubsub
                            await redis_pubsub.publish_price_update(
                                str(market.id), yes_price, no_price, float(market.total_volume)
                            )
                            check_price_alerts.delay(str(market.id), yes_price, no_price)
                            await redis_pubsub.publish_order_fill(str(order.user_id), {
                                "order_id": str(order.id),
                                "market_id": str(market.id),
                                "status": order.status,
                                "side": order_side,
                                "shares": float(order_amount - remaining),
                                "price": float(amm_price_val) if amm_price_val > 0 else float(order.price),
                            })
                            # Also dispatch in-app notification
                            from app.services.notification_service import (
                                NotificationService,
                            )
                            await NotificationService.dispatch(
                                db, str(order.user_id), "order_filled",
                                f"Order filled: {order_side} {float(order_amount - remaining):.2f} shares",
                                f"Your {order.status} order on {market.slug} has been filled.",
                                {"order_id": str(order.id), "market_id": str(market.id), "side": order_side}
                            )
                            # Publish position:update for real-time UI refresh
                            await redis_pubsub.publish_notification(str(order.user_id), {
                                "type": "position:update",
                                "market_id": str(market.id),
                                "outcome": outcome.name if outcome else None,
                                "shares": float(order_amount - remaining),
                                "side": order_side,
                            })
                        except Exception:
                            pass

                    executed += 1

            return f"Executed {executed}/{len(orders)} limit orders"

    return asyncio.run(_run())


@shared_task(bind=True, name="app.workers.tasks.sync_amm_prices")
def sync_amm_prices(self):
    """Sync AMM prices from DB to Redis for fast reads."""
    logger.info("Running sync_amm_prices")

    async def _run():
        from app.models import LiquidityPool, Market
        from app.redis import get_redis

        async with async_session() as db:
            result = await db.execute(
                select(Market, LiquidityPool).join(
                    LiquidityPool, Market.id == LiquidityPool.market_id
                ).where(Market.status == "active")
            )
            rows = result.all()

            if not rows:
                return "No active markets"

            r = get_redis()
            pipe = r.pipeline()

            for market, pool in rows:
                total = float(pool.yes_shares) + float(pool.no_shares)
                if total > 0:
                    yes_price = float(pool.no_shares) / total
                    no_price = float(pool.yes_shares) / total
                else:
                    yes_price, no_price = 0.5, 0.5

                key = f"market:{market.id}:price"
                pipe.hset(key, mapping={
                    "yes_price": str(yes_price),
                    "no_price": str(no_price),
                    "updated_at": datetime.now(UTC).isoformat(),
                })
                pipe.expire(key, 300)  # 5 min TTL

            await pipe.execute()
            return f"Synced prices for {len(rows)} markets"

    return asyncio.run(_run())


@shared_task(bind=True, name="app.workers.tasks.snapshot_price_history")
def snapshot_price_history(self):
    """Snapshot current prices to price_history table for charting."""
    logger.info("Running snapshot_price_history")

    async def _run():
        async with async_session() as db:
            result = await db.execute(
                select(Market, LiquidityPool).join(
                    LiquidityPool, Market.id == LiquidityPool.market_id
                ).where(Market.status == "active")
            )
            rows = result.all()

            if not rows:
                return "No active markets"

            market_ids = [r[0].id for r in rows]
            outcomes_result = await db.execute(
                select(Outcome).where(Outcome.market_id.in_(market_ids))
            )
            outcomes = outcomes_result.scalars().all()
            outcomes_by_market: dict = {}
            for o in outcomes:
                outcomes_by_market.setdefault(o.market_id, []).append(o)

            now = datetime.now(UTC)
            snapshots = []
            for market, pool in rows:
                total = pool.yes_shares + pool.no_shares
                yes_price = pool.no_shares / total if total > 0 else Decimal("0.5")
                no_price = pool.yes_shares / total if total > 0 else Decimal("0.5")

                market_outcomes = outcomes_by_market.get(market.id, [])
                if len(market_outcomes) == 2:
                    snapshots.append(PriceHistory(
                        market_id=market.id,
                        outcome_id=market_outcomes[0].id,
                        price=yes_price,
                        total_volume=market.total_volume,
                        snapshot_at=now,
                    ))
                    snapshots.append(PriceHistory(
                        market_id=market.id,
                        outcome_id=market_outcomes[1].id,
                        price=no_price,
                        total_volume=market.total_volume,
                        snapshot_at=now,
                    ))
                else:
                    uniform_price = Decimal(1) / Decimal(str(len(market_outcomes))) if market_outcomes else Decimal("0.5")
                    for o in market_outcomes:
                        snapshots.append(PriceHistory(
                            market_id=market.id,
                            outcome_id=o.id,
                            price=uniform_price,
                            total_volume=market.total_volume,
                            snapshot_at=now,
                        ))

            db.add_all(snapshots)
            await db.commit()
            return f"Snapshotted {len(snapshots)} price records for {len(rows)} markets"

    return asyncio.run(_run())


@shared_task(bind=True, name="app.workers.tasks.check_order_expiration")
def check_order_expiration(self):
    """Cancel pending orders that have passed their expiry time."""
    logger.info("Running check_order_expiration")

    async def _run():
        async with async_session() as db:
            now = datetime.now(UTC)
            result = await db.execute(
                select(Order).where(
                    Order.status == "pending",
                    Order.expires_at.isnot(None),
                    Order.expires_at <= now,
                ).with_for_update()
            )
            orders = result.scalars().all()
            if not orders:
                return "No expired pending orders"

            for order in orders:
                order.status = "cancelled"
                order.executed_at = now
                if order.side == "buy" and order.amount:
                    wallet_result = await db.execute(
                        select(Wallet).where(Wallet.user_id == order.user_id).with_for_update()
                    )
                    wallet = wallet_result.scalar_one_or_none()
                    if wallet:
                        wallet.locked_balance = max(wallet.locked_balance - order.amount, 0)
                logger.info(f"Cancelled expired pending order {order.id}")
                try:
                    await redis_pubsub.publish_market_event(
                        str(order.market_id), "order:cancelled",
                        {"order_id": str(order.id), "reason": "expired"}
                    )
                except Exception:
                    pass

            await db.commit()
            return f"Cancelled {len(orders)} expired pending orders"

    return asyncio.run(_run())


@shared_task(bind=True, name="app.workers.tasks.check_markets_ready_to_resolve")
def check_markets_ready_to_resolve(self):
    """Close markets that have passed their close time but are not yet resolved."""
    logger.info("Running check_markets_ready_to_resolve")

    async def _run():
        async with async_session() as db:
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
                logger.warning(f"Market {market.slug} ({market.id}) closed — awaiting resolution")

            await db.commit()
            return f"Closed {len(markets)} markets"

    return asyncio.run(_run())


@shared_task(bind=True, name="app.workers.tasks.process_stripe_deposit")
def process_stripe_deposit(self, stripe_event_id: str, user_id: str, amount_cents: int, payment_intent_id: str):
    """Process Stripe deposit (called by webhook handler as Celery task)."""
    logger.info(f"Processing Stripe deposit: PI={payment_intent_id} user={user_id} amount={amount_cents}")

    async def _run():
        async with async_session() as db:
            # Idempotency check
            existing = await db.execute(
                select(Transaction).where(
                    Transaction.reference_id == payment_intent_id,
                    Transaction.type == "deposit",
                )
            )
            if existing.scalar_one_or_none():
                return "Already processed"

            wallet_result = await db.execute(select(Wallet).where(Wallet.user_id == user_id))
            wallet = wallet_result.scalar_one_or_none()
            if not wallet:
                return f"Wallet not found for user {user_id}"

            amount = amount_cents / 100.0
            wallet.balance += amount

            tx = Transaction(
                user_id=user_id,
                wallet_id=wallet.id,
                type="deposit",
                amount=amount,
                balance_after=wallet.balance,
                reference_id=payment_intent_id,
                reference_type="stripe_payment_intent",
                status="completed",
            )
            db.add(tx)
            await db.commit()
            return f"Credited {amount} to user {user_id}"

    return asyncio.run(_run())


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
    logger.info(f"Running resolve_market: market={market_id} outcome={winning_outcome_id}")

    async def _run():
        async with async_session() as db:
            # Lock market row to prevent concurrent resolution
            market_result = await db.execute(
                select(Market).where(Market.id == market_id).with_for_update()
            )
            market = market_result.scalar_one_or_none()
            if not market:
                return f"Market {market_id} not found"
            if market.status == "resolved":
                return f"Market {market_id} already resolved"

            pool_result = await db.execute(
                select(LiquidityPool).where(LiquidityPool.market_id == market.id).with_for_update()
            )
            pool = pool_result.scalar_one_or_none()

            # Get or create system treasury user
            treasury_result = await db.execute(
                select(User).where(User.is_system).limit(1)
            )
            treasury_user = treasury_result.scalar_one_or_none()
            if not treasury_user:
                treasury_user = User(
                    email="treasury@system",
                    username="treasury",
                    password_hash="",
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

            # Get YES outcome for LP redemption
            yes_outcome_result = await db.execute(
                select(Outcome).where(Outcome.market_id == market.id, Outcome.outcome_index == 0)
            )
            yes_outcome = yes_outcome_result.scalar_one_or_none()

            # Settle positions
            pos_result = await db.execute(
                select(Position).where(Position.market_id == market.id)
            )
            positions = pos_result.scalars().all()

            winners_credited = 0
            for pos in positions:
                wallet_result = await db.execute(
                    select(Wallet).where(Wallet.user_id == pos.user_id).with_for_update()
                )
                wallet = wallet_result.scalar_one_or_none()
                if not wallet:
                    continue

                is_winner = str(pos.outcome_id) == winning_outcome_id
                # Use Decimal throughout to avoid float rounding — convert to float only at DB write
                payout: Decimal = pos.shares_held if is_winner else Decimal(0)

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

            # Extract protocol fees to treasury before LP redemption
            if pool and float(pool.protocol_fees) > 0:
                treasury_amount = pool.protocol_fees
                treasury_wallet.balance += treasury_amount
                pool.protocol_fees = Decimal(0)
                treasury_tx = Transaction(
                    user_id=treasury_user.id,
                    wallet_id=treasury_wallet.id,
                    type="protocol_fee",
                    amount=float(treasury_amount),
                    balance_after=treasury_wallet.balance,
                    reference_id=str(market.id),
                    reference_type="protocol_fee",
                    status="completed",
                )
                db.add(treasury_tx)

            # Settle LP shares
                lp_result = await db.execute(
                    select(LPShare).where(LPShare.pool_id == pool.id, LPShare.lp_tokens > 0)
                )
                lp_shares = lp_result.scalars().all()

                # LP redemption: use winning outcome's pool side — Decimal throughout
                is_yes_winner = yes_outcome and str(yes_outcome.id) == winning_outcome_id
                winning_shares = pool.yes_shares if is_yes_winner else pool.no_shares
                lp_payout_per_token = winning_shares / pool.lp_token_supply

                for lp in lp_shares:
                    lp_payout = lp.lp_tokens * lp_payout_per_token
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
            await db.commit()
            return f"Settled market {market_id}: {winners_credited}/{len(positions)} positions credited"

    return asyncio.run(_run())


@shared_task(bind=True, name="app.workers.tasks.check_price_alerts")
def check_price_alerts(self, market_id: str, yes_price: float, no_price: float):
    """Check untriggered alerts when price updates and broadcast triggered ones via WebSocket."""
    logger.info(f"Running check_price_alerts: market={market_id} yes={yes_price:.4f} no={no_price:.4f}")

    async def _run():
        async with async_session() as db:
            result = await db.execute(
                select(Alert).where(
                    Alert.market_id == market_id,
                    not Alert.triggered,
                )
            )
            alerts = result.scalars().all()
            if not alerts:
                return "No active alerts"

            triggered_count = 0
            for alert in alerts:
                price = yes_price if (alert.outcome == "yes" or alert.outcome is None) else no_price
                is_triggered = (
                    (alert.condition == "above" and price >= alert.trigger_price) or
                    (alert.condition == "below" and price <= alert.trigger_price)
                )
                if is_triggered:
                    alert.triggered = True
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
                        from app.models.market import Market
                        from app.services.notification_service import (
                            NotificationService,
                        )
                        market_result = await db.execute(select(Market).where(Market.id == market_id))
                        market = market_result.scalar_one_or_none()
                        market_slug = market.slug if market else market_id
                        await NotificationService.dispatch(
                            db, str(alert.user_id), "alert_triggered",
                            f"Price alert triggered: {alert.outcome or 'price'} {alert.condition} ${alert.trigger_price:.2f}",
                            f"Your alert on {market_slug} has been triggered at ${price:.2f}.",
                            {"alert_id": str(alert.id), "market_id": market_id, "outcome": alert.outcome, "condition": alert.condition}
                        )
                    except Exception:
                        pass
            await db.commit()
            return f"Checked {len(alerts)} alerts, {triggered_count} triggered"

    return asyncio.run(_run())


@shared_task(bind=True, name="app.workers.tasks.send_email", max_retries=3, default_retry_delay=60)
def send_email(self, to_email: str, subject: str, body: str):
    """Send transactional email via Resend or Mailtrap SMTP."""
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
        logger.error(f"Failed to send email to {to_email}: {exc}")
        raise self.retry(exc=exc)


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
    if purpose == "verify":
        subject = "Your Polymarket verification code"
        body = f"Your verification code is: {code}\nThis code expires in 10 minutes."
    elif purpose == "magic" and magic_url:
        subject = "Your Polymarket login link"
        body = (
            f"Click this link to sign in: {magic_url}\n\n"
            f"This link expires in 15 minutes. "
            f"If you didn't request this, you can safely ignore this email."
        )
    elif purpose == "magic":
        subject = "Your Polymarket login code"
        body = (
            f"Your login code is: {code}\n"
            f"This code expires in 10 minutes. "
            f"If you didn't request this, you can safely ignore this email."
        )
    elif purpose == "resetpwd":
        subject = "Your Polymarket password reset code"
        body = (
            f"Your password reset code is: {code}\n"
            f"This code expires in 10 minutes. "
            f"If you didn't request this, your account is safe."
        )
    else:
        subject = "Your Polymarket code"
        body = f"Your code is: {code}\nThis code expires in 10 minutes."

    send_email.delay(to_email=email, subject=subject, body=body)
    logger.info(f"Auth email prepared for {email}, purpose={purpose}")


@shared_task(bind=True, name="app.workers.tasks.enqueue_otp")
def enqueue_otp(self, email: str, purpose: str):
    """
    Store OTP in Redis and dispatch the appropriate email via the send_email task.
    Called by auth routes as a fire-and-forget Celery task.
    """
    import hashlib
    import hmac
    import random

    def _get_secret(e: str, p: str) -> str:
        import app.config
        base = f"{app.config.settings.jwt_secret}:{e}:{p}"
        return hashlib.sha256(base.encode()).hexdigest()[:32]

    def _hash_code(code: str, secret: str) -> str:
        return hmac.new(secret.encode(), code.encode(), hashlib.sha256).hexdigest()[:64]

    def _generate_code() -> str:
        return str(random.randint(100000, 999999))

    code = _generate_code()
    secret = _get_secret(email, purpose)
    key = f"otp:{purpose}:{email}"

    # Store in Redis synchronously inside the task
    import asyncio
    async def _store():
        from app.redis import get_redis, redis_cb
        r = get_redis()
        await redis_cb.call(
            lambda: r.setex(key, 600, f"{code}:{_hash_code(code, secret)}")
        )
    asyncio.run(_store())

    # Build email content based on purpose
    if purpose == "verify":
        subject = "Your Polymarket verification code"
        body = f"Your verification code is: {code}\nThis code expires in 10 minutes."
    elif purpose == "magic":
        subject = "Your Polymarket login code"
        body = f"Your login code is: {code}\nThis code expires in 10 minutes. If you didn't request this, you can safely ignore this email."
    elif purpose == "resetpwd":
        subject = "Your Polymarket password reset code"
        body = f"Your password reset code is: {code}\nThis code expires in 10 minutes. If you didn't request this, your account is safe."
    else:
        subject = "Your Polymarket code"
        body = f"Your code is: {code}\nThis code expires in 10 minutes."

    send_email.delay(to_email=email, subject=subject, body=body)
    logger.info(f"OTP enqueued for {email}, purpose={purpose}")



@shared_task(bind=True, name="app.workers.tasks.distribute_protocol_fees")
def distribute_protocol_fees(self):
    """Distribute accumulated protocol fees from all markets to the treasury."""
    logger.info("Running distribute_protocol_fees")

    async def _run():
        async with async_session() as db:
            result = await LiquidityService.distribute_protocol_fees(db)
            logger.info(f"Protocol fees distributed: {result}")
            return result

    return asyncio.run(_run())


@shared_task(bind=True, name="app.workers.tasks.cleanup_expired_sessions")
def cleanup_expired_sessions(self):
    """
    Delete expired sessions and refresh tokens from the DB.
    Runs daily to prevent table bloat.
    """
    from datetime import UTC, datetime, timedelta

    async def _run():
        async with async_session() as db:
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

    return asyncio.run(_run())
