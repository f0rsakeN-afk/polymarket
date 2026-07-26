import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, get_db_replica
from app.deps import get_current_user
from app.models.market import Market, Outcome
from app.models.order import Order
from app.models.position import Position
from app.models.wallet import Wallet, Transaction
from app.models.liquidity import LiquidityPool
from app.models.trade import Trade
from app.models.referral import Referral
from app.schemas.order import OrderRequest, OrderResponse, PositionResponse
from app.api.responses import success_response
from app.api.exceptions import (
    NotFoundError,
    ValidationError,
    InsufficientBalanceError,
    MarketClosedError,
    IdempotencyError,
)
from app.amm.engine import BinaryAMM
from app.websocket.manager import redis_pubsub

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/orders", tags=["orders"])


def _get_market_prices(pool: LiquidityPool) -> tuple[float, float]:
    total = float(pool.yes_shares) + float(pool.no_shares)
    if total == 0:
        return 0.5, 0.5
    return float(pool.no_shares) / total, float(pool.yes_shares) / total


@router.post("/", summary="Place a market order", description="Place a buy or sell market order on a prediction market. Uses AMM for price discovery. Requires authentication.")
async def place_order(data: OrderRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    amount = Decimal(str(data.amount))

    # Idempotency check — with FOR UPDATE to prevent race
    if data.client_order_id:
        existing = await db.execute(
            select(Order).where(
                Order.user_id == user.id,
                Order.client_order_id == data.client_order_id,
            )
        )
        if existing.scalar_one_or_none():
            raise IdempotencyError("Order already placed with this client_order_id")

    # Load market with FOR UPDATE — prevents race between status check and pool lock
    market_result = await db.execute(
        select(Market).where(Market.id == data.market_id).with_for_update()
    )
    market = market_result.scalar_one_or_none()
    if not market:
        raise NotFoundError("Market not found")
    if market.status != "active":
        raise MarketClosedError()
    if market.closes_at and datetime.now(timezone.utc) >= market.closes_at:
        raise MarketClosedError({"reason": "Market has closed for trading"})

    # Load outcomes
    outcomes_result = await db.execute(
        select(Outcome).where(Outcome.market_id == market.id).order_by(Outcome.outcome_index)
    )
    all_outcomes = list(outcomes_result.scalars().all())
    outcome_map = {o.name.lower(): o for o in all_outcomes}
    outcome = outcome_map.get(data.outcome)
    if not outcome:
        raise ValidationError(f"Invalid outcome '{data.outcome}'")

    # Load pool with FOR UPDATE (lock ordering: market → pool to avoid deadlocks)
    pool = await db.execute(
        select(LiquidityPool).where(LiquidityPool.market_id == market.id).with_for_update()
    )
    pool = pool.scalar_one_or_none()
    if not pool:
        raise ValidationError("Market has no liquidity")

    # Load wallet with FOR UPDATE
    wallet = await db.execute(
        select(Wallet).where(Wallet.user_id == user.id).with_for_update()
    )
    wallet = wallet.scalar_one_or_none()
    if not wallet:
        raise ValidationError("Wallet not found")

    # Lock position for sell
    position = None
    if data.side == "sell":
        pos_result = await db.execute(
            select(Position).where(
                Position.user_id == user.id,
                Position.market_id == market.id,
                Position.outcome_id == outcome.id,
            ).with_for_update()
        )
        position = pos_result.scalar_one_or_none()
        if not position or position.shares_held < amount:
            raise ValidationError(
                f"Insufficient {data.outcome} shares. "
                f"Held: {float(position.shares_held) if position else 0}, "
                f"Requested: {float(amount)}"
            )

    # Load existing position for buy (to update average price)
    if data.side == "buy":
        pos_result = await db.execute(
            select(Position).where(
                Position.user_id == user.id,
                Position.market_id == market.id,
                Position.outcome_id == outcome.id,
            ).with_for_update()
        )
        position = pos_result.scalar_one_or_none()

    # Execute AMM
    amm = BinaryAMM(
        yes_shares=pool.yes_shares,
        no_shares=pool.no_shares,
        fee_rate=pool.fee_rate,
    )

    # Capture pre-trade price for slippage display
    price_before = amm.price(data.outcome)
    current_price = float(price_before)

    # Limit order: check price condition
    if data.order_type in ("limit", "fill_or_kill"):
        limit_price = Decimal(str(data.price)) if data.price is not None else Decimal("0")
        # Buy: execute if current price <= limit price (can buy at or below limit)
        # Sell: execute if current price >= limit price (can sell at or above limit)
        if data.side == "buy":
            can_fill = current_price <= float(limit_price)
        else:
            can_fill = current_price >= float(limit_price)

        # Post-only: reject if would execute immediately (maker order)
        if data.post_only and can_fill:
            raise ValidationError(
                f"Post-only order would execute immediately. "
                f"Current price: {current_price:.4f}, limit: {float(limit_price):.4f}"
            )

        if not can_fill:
            if data.order_type == "fill_or_kill":
                raise ValidationError(
                    f"Fill-or-kill price condition not met. "
                    f"Current price: {current_price:.4f}, limit: {float(limit_price):.4f}"
                )
            # Limit order: create pending, lock collateral
            if data.side == "buy":
                available = wallet.balance - wallet.locked_balance
                if available < amount:
                    raise InsufficientBalanceError({
                        "available": float(wallet.balance),
                        "required": float(amount),
                    })
                wallet.locked_balance += amount

            order = Order(
                user_id=user.id,
                market_id=market.id,
                outcome_id=outcome.id,
                side=data.side,
                order_type=data.order_type,
                amount=amount,
                price=limit_price,
                remaining_amount=amount,
                status="pending",
                expires_at=data.expires_at,
                client_order_id=data.client_order_id,
            )
            db.add(order)
            await db.commit()
            await db.refresh(order)

            logger.info(
                f"Limit order pending: user={user.id} market={market.slug} "
                f"{data.side} {data.outcome} amount={float(amount)} limit={float(limit_price)}"
            )
            return success_response({
                "order_id": str(order.id),
                "status": "pending",
                "side": data.side,
                "outcome": data.outcome,
                "amount": float(amount),
                "limit_price": float(limit_price),
                "current_price": current_price,
            })

    # Market order (or limit that can fill now)
    if data.side == "buy":
        if wallet.balance < amount:
            raise InsufficientBalanceError({
                "available": float(wallet.balance),
                "required": float(amount),
            })
        quote = amm.apply_trade(data.outcome, amount)
        wallet.balance -= amount
        shares = quote.shares_out
        proceeds = quote.collateral_in - quote.fee
    else:
        quote = amm.apply_trade(data.outcome, amount)
        shares_sold = min(amount, position.shares_held)
        cost_basis = position.average_price * shares_sold
        sell_proceeds = quote.collateral_in
        realized_pnl = sell_proceeds - cost_basis
        position.shares_held -= shares_sold
        position.realized_pnl += realized_pnl
        wallet.balance += sell_proceeds
        shares = amount

    # Protocol fee: 1% of trade value — accrues in pool, extracted at settlement
    trade_value = amount * quote.price
    protocol_fee = trade_value * Decimal("0.01")
    pool.protocol_fees += protocol_fee

    # Update pool
    pool.yes_shares = amm.yes_shares
    pool.no_shares = amm.no_shares

    # Update or create position
    if data.side == "buy":
        if position:
            total_cost = amount
            total_shares = position.shares_held + shares
            if total_shares > 0:
                position.average_price = (
                    position.average_price * position.shares_held + total_cost
                ) / total_shares
            position.shares_held = total_shares
        else:
            avg_price = quote.collateral_in / shares if shares > 0 else Decimal("0")
            position = Position(
                user_id=user.id,
                market_id=market.id,
                outcome_id=outcome.id,
                shares_held=shares,
                average_price=avg_price,
            )
            db.add(position)

    # Market stats
    market.total_volume += amount
    market.num_trades += 1

    # Order record
    order = Order(
        user_id=user.id,
        market_id=market.id,
        outcome_id=outcome.id,
        side=data.side,
        order_type=data.order_type,
        amount=amount,
        remaining_amount=Decimal("0"),
        price=quote.price,
        shares_bought=shares if data.side == "buy" else None,
        shares_sold=shares if data.side == "sell" else None,
        fees_paid=quote.fee,
        status="filled",
        client_order_id=data.client_order_id,
        executed_at=datetime.now(timezone.utc),
    )
    db.add(order)

    # Record trade for public feed
    trade = Trade(
        user_id=user.id,
        market_id=market.id,
        outcome=data.outcome,
        side=data.side,
        price=quote.price,
        amount=shares,
        executed_at=datetime.now(timezone.utc),
    )
    db.add(trade)

    # Record trade transaction
    trade_amount = -float(amount) if data.side == "buy" else float(sell_proceeds)
    tx = Transaction(
        user_id=user.id,
        wallet_id=wallet.id,
        type="trade_buy" if data.side == "buy" else "trade_sell",
        amount=trade_amount,
        balance_after=wallet.balance,
        reference_id=str(order.id),
        reference_type="order",
        status="completed",
    )
    db.add(tx)

    # Credit referral reward if this is the referred user's first trade
    try:
        ref_result = await db.execute(
            select(Referral).where(
                Referral.referred_id == user.id,
                Referral.status == "pending",
            )
        )
        referral = ref_result.scalar_one_or_none()
        if referral:
            reward = Decimal(str(settings.referral_reward_amount))
            # Credit referrer
            ref_wallet_result = await db.execute(
                select(Wallet).where(Wallet.user_id == referral.referrer_id).with_for_update()
            )
            ref_wallet = ref_wallet_result.scalar_one_or_none()
            if ref_wallet:
                ref_wallet.balance += reward
                referral.reward_amount = reward
                referral.status = "completed"
                referral.completed_at = datetime.now(timezone.utc)
                ref_tx = Transaction(
                    user_id=referral.referrer_id,
                    wallet_id=ref_wallet.id,
                    type="referral_reward",
                    amount=float(reward),
                    balance_after=ref_wallet.balance,
                    reference_id=str(referral.id),
                    reference_type="referral",
                    status="completed",
                )
                db.add(ref_tx)
    except Exception:
        pass  # Referral credit failure is non-fatal

    await db.commit()
    await db.refresh(order)

    # Publish price update
    yes_price, no_price = _get_market_prices(pool)
    await redis_pubsub.publish_price_update(
        str(market.id), yes_price, no_price, float(market.total_volume)
    )
    # Check price alerts
    from app.workers.tasks import check_price_alerts
    check_price_alerts.delay(str(market.id), yes_price, no_price)

    # Publish trade event for live feed
    try:
        await redis_pubsub.publish_market_event(str(market.id), "trade:new", {
            "outcome": data.outcome,
            "side": data.side,
            "price": float(quote.price),
            "amount": float(shares),
            "username": user.username,
        })
    except Exception:
        pass  # non-fatal

    logger.info(
        f"Order filled: user={user.id} market={market.slug} "
        f"{data.side} {data.outcome} amount={float(amount)} shares={float(shares)}"
    )

    return success_response({
        "order_id": str(order.id),
        "status": "filled",
        "side": data.side,
        "outcome": data.outcome,
        "shares": float(shares),
        "price": float(quote.price),
        "price_before": float(price_before),
        "price_after": float(quote.price),
        "yes_price_after": float(quote.yes_price_after),
        "no_price_after": float(quote.no_price_after),
        "slippage": float(quote.slippage),
        "fee": float(quote.fee),
        "wallet_balance": float(wallet.balance),
    })


@router.delete("/{order_id}", summary="Cancel a pending order", description="Cancel a pending order and release any locked collateral. Only pending orders can be cancelled.")
async def cancel_order(order_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Cancel a pending limit order and release any locked collateral."""
    user = await get_current_user(request, db)

    order = await db.execute(
        select(Order).where(
            Order.id == order_id,
            Order.user_id == user.id,
            Order.status == "pending",
        ).with_for_update()
    )
    order = order.scalar_one_or_none()
    if not order:
        raise NotFoundError("Pending order not found")

    order.status = "cancelled"
    order.executed_at = datetime.now(timezone.utc)

    # Release locked collateral if it was a buy order
    if order.side == "buy" and order.amount > 0:
        wallet = await db.execute(
            select(Wallet).where(Wallet.user_id == user.id).with_for_update()
        )
        wallet = wallet.scalar_one_or_none()
        if wallet:
            wallet.locked_balance = max(Decimal("0"), wallet.locked_balance - order.amount)

    await db.commit()
    logger.info(f"Order cancelled: {order_id} by user={user.id}")
    return success_response({"order_id": str(order_id), "status": "cancelled"})


@router.get("/{order_id}", summary="Get order details", description="Retrieve details of a specific order by ID. Requires authentication.")
async def get_order(order_id: str, request: Request, db: AsyncSession = Depends(get_db_replica)):
    user = await get_current_user(request, db)
    result = await db.execute(
        select(Order, Outcome, Market).where(
            Order.id == order_id,
            Order.user_id == user.id,
            Order.outcome_id == Outcome.id,
            Order.market_id == Market.id,
        )
    )
    row = result.first()
    if not row:
        raise NotFoundError("Order not found")
    order, outcome, market = row

    return success_response({
        "id": str(order.id),
        "market_id": str(order.market_id),
        "market_slug": market.slug,
        "outcome": outcome.name.lower(),
        "side": order.side,
        "order_type": order.order_type,
        "amount": float(order.amount),
        "remaining_amount": float(order.remaining_amount or 0),
        "price": float(order.price),
        "status": order.status,
        "shares_bought": float(order.shares_bought) if order.shares_bought else None,
        "shares_sold": float(order.shares_sold) if order.shares_sold else None,
        "fee": float(order.fees_paid) if order.fees_paid else None,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "executed_at": order.executed_at.isoformat() if order.executed_at else None,
    })


@router.get("/", summary="List orders", description="List all orders for the authenticated user with pagination.")
async def list_orders(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db_replica),
):
    user = await get_current_user(request, db)

    total_result = await db.execute(
        select(Order).where(Order.user_id == user.id)
    )
    total = len(total_result.scalars().all())

    result = await db.execute(
        select(Order, Outcome, Market).where(
            Order.user_id == user.id,
            Order.outcome_id == Outcome.id,
            Order.market_id == Market.id,
        )
        .order_by(Order.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = result.all()

    orders = []
    for order, outcome, market in rows:
        orders.append({
            "id": str(order.id),
            "market_id": str(order.market_id),
            "market_slug": market.slug,
            "outcome": outcome.name.lower(),
            "side": order.side,
            "order_type": order.order_type,
            "amount": float(order.amount),
            "remaining_amount": float(order.remaining_amount or 0),
            "price": float(order.price),
            "status": order.status,
            "shares_bought": float(order.shares_bought) if order.shares_bought else None,
            "shares_sold": float(order.shares_sold) if order.shares_sold else None,
            "fee": float(order.fees_paid) if order.fees_paid else None,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "executed_at": order.executed_at.isoformat() if order.executed_at else None,
        })

    return success_response({
        "orders": orders,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": (page * page_size) < total,
    })
