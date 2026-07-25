import logging
import asyncio
from datetime import datetime, timezone

from celery import shared_task
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import settings
from app.models import Order, Market, Wallet, Transaction, Position, LiquidityPool, LPShare, Outcome, Trade, User
from app.workers.celery_app import celery_app
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
            now = datetime.now(timezone.utc)
            result = await db.execute(
                select(Order).where(
                    Order.order_type.in_(["limit", "fill_or_kill"]),
                    Order.status.in_(["pending", "partial"]),
                    Order.expires_at <= now,
                ).with_for_update()
            )
            orders = result.scalars().all()

            if not orders:
                return f"No orders to expire"

            expired_ids = []
            for order in orders:
                order.status = "expired"
                order.executed_at = datetime.now(timezone.utc)
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
    """Check pending limit orders and execute those whose price condition is met."""
    logger.info("Running check_limit_order_execution")

    async def _run():
        async with async_session() as db:
            now = datetime.now(timezone.utc)
            result = await db.execute(
                select(Order).where(
                    Order.order_type.in_(["limit", "fill_or_kill"]),
                    Order.status == "pending",
                ).with_for_update()
            )
            orders = result.scalars().all()

            if not orders:
                return f"No pending limit orders"

            executed = 0
            for order in orders:
                # Skip expired
                if order.expires_at and order.expires_at <= now:
                    order.status = "expired"
                    order.executed_at = now
                    # Release locked collateral for buys
                    if order.side == "buy":
                        wallet = await db.execute(
                            select(Wallet).where(Wallet.user_id == order.user_id).with_for_update()
                        )
                        wallet = wallet.scalar_one_or_none()
                        if wallet:
                            wallet.locked_balance = max(wallet.locked_balance - order.amount, 0)
                    await db.commit()
                    continue

                # Load market + pool with locks (market first to avoid status-check race)
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

                # Check price condition against LIVE pool state
                amm = BinaryAMM(
                    yes_shares=pool.yes_shares,
                    no_shares=pool.no_shares,
                    fee_rate=pool.fee_rate,
                )
                current_price = float(amm.price(outcome.name.lower()))
                limit_price = float(order.price)

                if order.side == "buy":
                    can_fill = current_price <= limit_price
                else:
                    can_fill = current_price >= limit_price

                if not can_fill:
                    continue

                # Execute the order
                wallet = await db.execute(
                    select(Wallet).where(Wallet.user_id == order.user_id).with_for_update()
                )
                wallet = wallet.scalar_one_or_none()
                if not wallet:
                    continue

                position_result = await db.execute(
                    select(Position).where(
                        Position.user_id == order.user_id,
                        Position.market_id == market.id,
                        Position.outcome_id == outcome.id,
                    ).with_for_update()
                )
                position = position_result.scalar_one_or_none()

                if order.side == "buy":
                    if wallet.balance < order.amount:
                        continue
                    quote = amm.apply_trade(outcome.name.lower(), order.amount)
                    wallet.balance -= order.amount
                    shares = quote.shares_out
                else:
                    if not position or position.shares_held < order.amount:
                        continue
                    quote = amm.apply_trade(outcome.name.lower(), order.amount)
                    shares_sold = min(order.amount, position.shares_held)
                    cost_basis = position.average_price * shares_sold
                    sell_proceeds = quote.collateral_in
                    realized_pnl = sell_proceeds - cost_basis
                    position.shares_held -= shares_sold
                    position.realized_pnl += realized_pnl
                    wallet.balance += sell_proceeds
                    shares = order.amount

                # Protocol fee: 1% of trade value
                trade_value = order.amount * quote.price
                protocol_fee = trade_value * Decimal("0.01")
                pool.protocol_fees += protocol_fee

                # Update pool AND recreate AMM for next order in batch (fresh state)
                pool.yes_shares = amm.yes_shares
                pool.no_shares = amm.no_shares
                # Recreate AMM so next order in batch uses correct (updated) pool state
                amm = BinaryAMM(
                    yes_shares=pool.yes_shares,
                    no_shares=pool.no_shares,
                    fee_rate=pool.fee_rate,
                )

                # Update position
                if order.side == "buy":
                    if position:
                        total_cost = order.amount
                        total_shares = position.shares_held + shares
                        if total_shares > 0:
                            position.average_price = (
                                position.average_price * position.shares_held + total_cost
                            ) / total_shares
                        position.shares_held = total_shares
                    else:
                        avg_price = quote.collateral_in / shares if shares > 0 else Decimal("0")
                        position = Position(
                            user_id=order.user_id,
                            market_id=market.id,
                            outcome_id=outcome.id,
                            shares_held=shares,
                            average_price=avg_price,
                        )
                        db.add(position)

                # Release locked balance for buy
                if order.side == "buy" and wallet:
                    wallet.locked_balance = max(wallet.locked_balance - order.amount, 0)

                # Update order
                order.status = "filled"
                order.executed_at = now
                order.remaining_amount = Decimal("0")
                order.shares_bought = shares if order.side == "buy" else None
                order.shares_sold = shares if order.side == "sell" else None
                order.fees_paid = quote.fee

                # Market stats
                market.total_volume += order.amount
                market.num_trades += 1

                # Trade for public feed
                trade = Trade(
                    market_id=market.id,
                    outcome=outcome.name.lower(),
                    side=order.side,
                    price=quote.price,
                    amount=shares,
                    executed_at=now,
                )
                db.add(trade)

                # Trade transaction
                trade_amount = -float(order.amount) if order.side == "buy" else float(sell_proceeds)
                tx = Transaction(
                    user_id=order.user_id,
                    wallet_id=wallet.id,
                    type="trade_buy" if order.side == "buy" else "trade_sell",
                    amount=trade_amount,
                    balance_after=wallet.balance,
                    reference_id=str(order.id),
                    reference_type="order",
                    status="completed",
                )
                db.add(tx)
                await db.commit()
                executed += 1

                # Publish price update
                total = float(pool.yes_shares) + float(pool.no_shares)
                yes_price = float(pool.no_shares) / total if total > 0 else 0.5
                no_price = float(pool.yes_shares) / total if total > 0 else 0.5
                try:
                    from app.websocket.manager import redis_pubsub
                    await redis_pubsub.publish_price_update(
                        str(market.id), yes_price, no_price, float(market.total_volume)
                    )
                    await redis_pubsub.publish_order_fill(str(order.user_id), {
                        "order_id": str(order.id),
                        "market_id": str(market.id),
                        "status": "filled",
                        "side": order.side,
                        "shares": float(shares),
                        "price": float(quote.price),
                    })
                except Exception:
                    pass

            return f"Executed {executed}/{len(orders)} limit orders"

    return asyncio.run(_run())


@shared_task(bind=True, name="app.workers.tasks.sync_amm_prices")
def sync_amm_prices(self):
    """Sync AMM prices from DB to Redis for fast reads."""
    logger.info("Running sync_amm_prices")

    async def _run():
        from app.redis import get_redis
        from app.models import LiquidityPool, Market

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
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                pipe.expire(key, 300)  # 5 min TTL

            await pipe.execute()
            return f"Synced prices for {len(rows)} markets"

    return asyncio.run(_run())


@shared_task(bind=True, name="app.workers.tasks.check_market_resolution")
def check_market_resolution(self):
    """Find markets that have closed but not yet resolved."""
    logger.info("Running check_market_resolution")

    async def _run():
        async with async_session() as db:
            now = datetime.now(timezone.utc)
            result = await db.execute(
                select(Market).where(
                    Market.status == "active",
                    Market.closes_at <= now,
                )
            )
            markets = result.scalars().all()

            if not markets:
                return "No markets to auto-resolve"

            # For now, just log - auto-resolution requires oracle/admin input
            for market in markets:
                logger.warning(f"Market {market.slug} ({market.id}) has closed but not resolved")
                # In production: trigger resolution workflow or notify admin

            return f"Found {len(markets)} markets needing resolution"

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
                select(User).where(User.is_system == True).limit(1)
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
                treasury_wallet = Wallet(
                    user_id=treasury_user.id,
                    balance=Decimal("0"),
                    locked_balance=Decimal("0"),
                    currency="USDC",
                )
                db.add(treasury_wallet)

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
                payout: Decimal = pos.shares_held if is_winner else Decimal("0")

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
            treasury_wallet = None
            if pool and float(pool.protocol_fees) > 0:
                treasury_result = await db.execute(
                    select(Wallet).where(Wallet.user_id == treasury_user.id).with_for_update()
                )
                treasury_wallet = treasury_result.scalar_one_or_none()

                if treasury_wallet:
                    treasury_amount = pool.protocol_fees
                    treasury_wallet.balance += treasury_amount
                    pool.protocol_fees = Decimal("0")
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

            await db.commit()
            return f"Settled market {market_id}: {winners_credited}/{len(positions)} positions credited"

    return asyncio.run(_run())
