import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.amm.engine import BinaryAMM
from app.api.exceptions import (
    InsufficientBalanceError,
    MarketClosedError,
    NotFoundError,
    SlippageExceededError,
    ValidationError,
)
from app.config import settings
from app.models.liquidity import LiquidityPool
from app.models.market import Market, Outcome
from app.models.order import Order
from app.models.position import Position
from app.models.referral import Referral
from app.models.trade import Trade
from app.models.user import User
from app.models.wallet import Transaction, Wallet
from app.redis import get_redis, redis_cb
from app.schemas.order import OrderRequest
from app.services.matching_engine import MatchingEngine
from app.websocket.manager import redis_pubsub

logger = logging.getLogger("polymarket")


@dataclass
class OrderResult:
    order_id: str
    status: str
    side: str
    outcome: str
    shares: Decimal
    price: Decimal
    price_before: Decimal
    price_after: Decimal
    yes_price_after: Decimal
    no_price_after: Decimal
    slippage: Decimal
    fee: Decimal
    wallet_balance: Decimal


class OrderService:

    QUOTE_TTL = 5  # seconds

    @staticmethod
    def _get_market_prices(pool: LiquidityPool) -> tuple[float, float]:
        total = float(pool.yes_shares) + float(pool.no_shares)
        if total == 0:
            return 0.5, 0.5
        return float(pool.no_shares) / total, float(pool.yes_shares) / total

    @staticmethod
    async def compute_quote(
        db: AsyncSession,
        market_id: str,
        outcome_name: str,
        side: str,
        amount: Decimal,
    ) -> dict:
        market_result = await db.execute(
            select(Market).where(Market.id == market_id)
        )
        market = market_result.scalar_one_or_none()
        if not market:
            raise NotFoundError("Market not found")
        if market.status != "active":
            raise MarketClosedError()

        outcome_result = await db.execute(
            select(Outcome).where(
                Outcome.market_id == market.id,
                Outcome.name.ilike(outcome_name),
            )
        )
        outcome = outcome_result.scalar_one_or_none()
        if not outcome:
            raise ValidationError(f"Invalid outcome '{outcome_name}'")

        pool_result = await db.execute(
            select(LiquidityPool).where(LiquidityPool.market_id == market.id)
        )
        pool = pool_result.scalar_one_or_none()
        if not pool:
            raise ValidationError("Market has no liquidity")

        amm = BinaryAMM(
            yes_shares=pool.yes_shares,
            no_shares=pool.no_shares,
            fee_rate=pool.fee_rate,
        )

        price_before = float(amm.price(outcome_name))

        if side == "buy":
            amm.buy(outcome_name, amount)
        else:
            amm.sell(outcome_name, amount)

        price_after = float(amm.price(outcome_name))
        slippage = abs(price_after - price_before)

        quote_id = str(uuid.uuid4())
        now = time.time()
        payload = {
            "quote_id": quote_id,
            "market_id": market_id,
            "outcome": outcome_name,
            "side": side,
            "amount": float(amount),
            "price_before": price_before,
            "price_after": price_after,
            "slippage": slippage,
            "yes_price": float(amm.yes_shares),
            "no_price": float(amm.no_shares),
            "expires_at": now + OrderService.QUOTE_TTL,
        }

        try:
            r = get_redis()
            await redis_cb.call(lambda: r.setex(
                f"quote:{quote_id}",
                OrderService.QUOTE_TTL,
                json.dumps(payload),
            ))
        except Exception:
            pass

        return payload

    @staticmethod
    async def execute_order(
        db: AsyncSession,
        user: User,
        data: OrderRequest,
    ) -> OrderResult:
        amount = Decimal(str(data.amount))

        # ── Step 1: Lock Market + Pool + Wallet (serialization point) ──

        market_result = await db.execute(
            select(Market).where(Market.id == data.market_id).with_for_update()
        )
        market = market_result.scalar_one_or_none()
        if not market:
            raise NotFoundError("Market not found")
        if market.status != "active":
            raise MarketClosedError()
        if market.closes_at and datetime.now(UTC) >= market.closes_at:
            raise MarketClosedError({"reason": "Market has closed for trading"})

        outcomes_result = await db.execute(
            select(Outcome).where(Outcome.market_id == market.id).order_by(Outcome.outcome_index)
        )
        all_outcomes = list(outcomes_result.scalars().all())
        outcome_map = {o.name.lower(): o for o in all_outcomes}
        outcome = outcome_map.get(data.outcome)
        if not outcome:
            raise ValidationError(f"Invalid outcome '{data.outcome}'")

        pool = await db.execute(
            select(LiquidityPool).where(LiquidityPool.market_id == market.id).with_for_update()
        )
        pool = pool.scalar_one_or_none()
        if not pool:
            raise ValidationError("Market has no liquidity")

        wallet = await db.execute(
            select(Wallet).where(Wallet.user_id == user.id).with_for_update()
        )
        wallet = wallet.scalar_one_or_none()
        if not wallet:
            raise ValidationError("Wallet not found")

        # ── Step 2: Idempotency check (inside lock — no race) ──

        if data.client_order_id:
            existing = await db.execute(
                select(Order).where(
                    Order.user_id == user.id,
                    Order.client_order_id == data.client_order_id,
                ).with_for_update()
            )
            existing_order = existing.scalar_one_or_none()
            if existing_order:
                return OrderResult(
                    order_id=str(existing_order.id),
                    status="duplicate",
                    side=data.side,
                    outcome=data.outcome,
                    shares=existing_order.shares_bought or existing_order.shares_sold or Decimal(0),
                    price=existing_order.price,
                    price_before=Decimal(0),
                    price_after=Decimal(0),
                    yes_price_after=Decimal(0),
                    no_price_after=Decimal(0),
                    slippage=Decimal(0),
                    fee=existing_order.fees_paid or Decimal(0),
                    wallet_balance=wallet.balance,
                )

        # ── Step 3: Validate quote if provided ──

        if data.quote_id:
            try:
                r = get_redis()
                raw = await redis_cb.call(lambda: r.get(f"quote:{data.quote_id}"))
                if raw:
                    quote = json.loads(raw)
                    if quote["expires_at"] < time.time():
                        raise ValidationError("Quote expired — please refresh")
            except ValidationError:
                raise
            except Exception:
                pass

        # ── Step 4: Position check for sells ──

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

        # ── Step 5: AMM + Matching ──

        amm = BinaryAMM(
            yes_shares=pool.yes_shares,
            no_shares=pool.no_shares,
            fee_rate=pool.fee_rate,
        )

        price_before = amm.price(data.outcome)
        limit_price = Decimal(str(data.price)) if data.price is not None else None

        if data.post_only:
            if data.order_type in ("limit", "fill_or_kill"):
                amm_price_f = float(price_before)
                limit_price_f = float(limit_price) if limit_price else 0
                if data.side == "buy":
                    would_execute = amm_price_f <= limit_price_f
                else:
                    would_execute = amm_price_f >= limit_price_f
                if would_execute:
                    raise ValidationError(
                        f"Post-only order would execute immediately. "
                        f"Current price: {amm_price_f:.4f}, limit: {limit_price_f:.4f}"
                    )

        matched_shares, matched_usdc, match_details = await MatchingEngine.match_order_against_book(
            db, market, outcome, data.side, amount, limit_price, str(user.id),
        )

        if data.side == "buy":
            remaining = amount - matched_usdc
        else:
            remaining = amount - matched_shares

        amm_shares = Decimal(0)
        amm_price_val = Decimal(0)
        amm_fee = Decimal(0)
        amm_slippage = Decimal(0)
        sell_proceeds_amm = Decimal(0)
        Decimal(0)

        if remaining > 0:
            if data.order_type in ("limit", "fill_or_kill"):
                amm_price_f = float(price_before)
                limit_price_f = float(limit_price) if limit_price else 0
                if data.side == "buy":
                    can_fill_amm = amm_price_f <= limit_price_f
                else:
                    can_fill_amm = amm_price_f >= limit_price_f

                if not can_fill_amm:
                    if data.order_type == "fill_or_kill":
                        raise ValidationError(
                            f"Fill-or-kill could not be filled. "
                            f"Matched: {float(matched_shares)} shares, "
                            f"Remaining: {float(remaining)}"
                        )

                    if data.side == "buy":
                        available = wallet.balance - wallet.locked_balance
                        if available < remaining:
                            raise InsufficientBalanceError({
                                "available": float(wallet.balance),
                                "required": float(remaining),
                            })
                        wallet.locked_balance += remaining

                    order = Order(
                        user_id=user.id,
                        market_id=market.id,
                        outcome_id=outcome.id,
                        side=data.side,
                        order_type=data.order_type,
                        amount=amount,
                        price=limit_price,
                        remaining_amount=remaining,
                        status="pending" if matched_shares == 0 else "partial",
                        expires_at=data.expires_at,
                        client_order_id=data.client_order_id,
                    )
                    db.add(order)

                    logger.info(
                        f"Limit order{' partially' if matched_shares > 0 else ''} pending: "
                        f"user={user.id} market={market.slug} "
                        f"{data.side} {data.outcome} amount={float(amount)} "
                        f"limit={float(limit_price) if limit_price else 0} "
                        f"matched={float(matched_shares)}"
                    )

                    return OrderResult(
                        order_id="",
                        status="pending" if matched_shares == 0 else "partial",
                        side=data.side,
                        outcome=data.outcome,
                        shares=matched_shares,
                        price=limit_price or Decimal(0),
                        price_before=price_before,
                        price_after=price_before,
                        yes_price_after=Decimal(0),
                        no_price_after=Decimal(0),
                        slippage=Decimal(0),
                        fee=Decimal(0),
                        wallet_balance=wallet.balance,
                    )

            if data.side == "buy":
                if wallet.balance < remaining:
                    raise InsufficientBalanceError({
                        "available": float(wallet.balance),
                        "required": float(remaining),
                    })
                quote = amm.apply_trade(data.outcome, remaining)
                wallet.balance -= remaining
                amm_shares = quote.shares_out
                amm_price_val = quote.price
                amm_fee = quote.fee
                amm_slippage = quote.slippage
            else:
                tmp_position = await db.execute(
                    select(Position).where(
                        Position.user_id == user.id,
                        Position.market_id == market.id,
                        Position.outcome_id == outcome.id,
                    ).with_for_update()
                )
                tmp_pos = tmp_position.scalar_one_or_none()
                if not tmp_pos or tmp_pos.shares_held < remaining:
                    raise ValidationError(
                        f"Insufficient {data.outcome} shares after orderbook match. "
                        f"Held: {float(tmp_pos.shares_held) if tmp_pos else 0}, "
                        f"Requested: {float(remaining)}"
                    )
                quote = amm.sell(data.outcome, remaining)
                cost_basis = tmp_pos.average_price * remaining
                sell_proceeds_amm = quote.collateral_in
                realized_pnl = sell_proceeds_amm - cost_basis
                tmp_pos.shares_held -= remaining
                tmp_pos.realized_pnl += realized_pnl
                wallet.balance += sell_proceeds_amm
                amm_shares = remaining
                amm_price_val = quote.price
                amm_fee = quote.fee
                amm_slippage = quote.slippage

            trade_value = remaining * amm_price_val
            protocol_fee = trade_value * Decimal("0.01")
            pool.protocol_fees += protocol_fee

            pool.yes_shares = amm.yes_shares
            pool.no_shares = amm.no_shares

        total_shares = matched_shares + amm_shares
        total_usdc_spent = matched_usdc + (remaining if data.side == "buy" else Decimal(0))
        total_usdc_received = matched_usdc + sell_proceeds_amm

        # ── Step 6: Slippage validation ──

        if total_shares > 0:
            actual_price = total_usdc_spent / total_shares if data.side == "buy" else amm_price_val
            if data.min_shares_out is not None and total_shares < Decimal(str(data.min_shares_out)):
                raise SlippageExceededError(
                    expected_price=float(price_before),
                    actual_price=float(actual_price),
                    max_slippage=data.max_slippage or 0.01,
                    details={"received_shares": float(total_shares), "min_shares_out": data.min_shares_out},
                )
            if data.max_slippage is not None:
                expected_price = float(price_before)
                actual_price_f = float(actual_price)
                if expected_price > 0:
                    if data.side == "buy":
                        slippage_pct = (actual_price_f - expected_price) / expected_price
                    else:
                        slippage_pct = (expected_price - actual_price_f) / expected_price
                    if slippage_pct > data.max_slippage:
                        raise SlippageExceededError(
                            expected_price=expected_price,
                            actual_price=actual_price_f,
                            max_slippage=data.max_slippage,
                        )

        # ── Step 7: Save order + positions + trades ──

        order = Order(
            user_id=user.id,
            market_id=market.id,
            outcome_id=outcome.id,
            side=data.side,
            order_type=data.order_type,
            amount=amount,
            remaining_amount=Decimal(0),
            price=amm_price_val if amm_price_val > 0 else (limit_price or Decimal(0)),
            shares_bought=total_shares if data.side == "buy" else None,
            shares_sold=total_shares if data.side == "sell" else None,
            fees_paid=amm_fee,
            status="filled",
            client_order_id=data.client_order_id,
            executed_at=datetime.now(UTC),
        )
        db.add(order)

        if data.side == "buy":
            pos_result = await db.execute(
                select(Position).where(
                    Position.user_id == user.id,
                    Position.market_id == market.id,
                    Position.outcome_id == outcome.id,
                ).with_for_update()
            )
            position = pos_result.scalar_one_or_none()
            total_cost = total_usdc_spent
            if position:
                total_shares_pos = position.shares_held + total_shares
                if total_shares_pos > 0:
                    position.average_price = (
                        position.average_price * position.shares_held + total_cost
                    ) / total_shares_pos
                position.shares_held = total_shares_pos
            else:
                avg_price = total_cost / total_shares if total_shares > 0 else Decimal(0)
                position = Position(
                    user_id=user.id,
                    market_id=market.id,
                    outcome_id=outcome.id,
                    shares_held=total_shares,
                    average_price=avg_price,
                )
                db.add(position)

        market.total_volume += amount
        market.num_trades += 1

        for md in match_details:
            t = Trade(
                user_id=user.id,
                market_id=market.id,
                outcome=md["outcome"],
                side=data.side,
                price=md["match_price"],
                amount=md["match_shares"],
                executed_at=datetime.now(UTC),
            )
            db.add(t)

        if remaining > 0:
            t = Trade(
                user_id=user.id,
                market_id=market.id,
                outcome=data.outcome,
                side=data.side,
                price=amm_price_val,
                amount=total_shares,
                executed_at=datetime.now(UTC),
            )
            db.add(t)

        trade_amount = -float(total_usdc_spent) if data.side == "buy" else float(total_usdc_received)
        tx = Transaction(
            user_id=user.id,
            wallet_id=wallet.id,
            type="trade_buy" if data.side == "buy" else "trade_sell",
            amount=trade_amount,
            balance_after=wallet.balance,
            reference_id="",
            reference_type="order",
            status="completed",
        )
        db.add(tx)

        # ── Step 8: Referral (best-effort) ──

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
                ref_wallet_result = await db.execute(
                    select(Wallet).where(Wallet.user_id == referral.referrer_id).with_for_update()
                )
                ref_wallet = ref_wallet_result.scalar_one_or_none()
                if ref_wallet:
                    ref_wallet.balance += reward
                    referral.reward_amount = reward
                    referral.status = "completed"
                    referral.completed_at = datetime.now(UTC)
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
            pass

        # ── Step 9: Single commit ──

        await db.commit()

        tx.reference_id = str(order.id)
        await db.refresh(order)

        # ── Step 10: Post-commit notifications (best-effort) ──

        try:
            yes_price, no_price = OrderService._get_market_prices(pool)
            await redis_pubsub.publish_price_update(
                str(market.id), yes_price, no_price, float(market.total_volume)
            )
            await redis_pubsub.publish_market_event(str(market.id), "trade:new", {
                "outcome": data.outcome,
                "side": data.side,
                "price": float(amm_price_val) if amm_price_val > 0 else float(matched_usdc / matched_shares) if matched_shares > 0 else 0,
                "amount": float(total_shares),
                "username": user.username,
            })
        except Exception:
            pass

        try:
            from app.workers.tasks import check_price_alerts
            check_price_alerts.delay(str(market.id), yes_price, no_price)
        except Exception:
            pass

        logger.info(
            f"Order filled: user={user.id} market={market.slug} "
            f"{data.side} {data.outcome} amount={float(amount)} shares={float(total_shares)}"
        )

        avg_price = total_usdc_spent / total_shares if total_shares > 0 else Decimal(0)

        after_total = amm.yes_shares + amm.no_shares
        yes_price_after = amm.no_shares / after_total if after_total > 0 else Decimal(0)
        no_price_after = amm.yes_shares / after_total if after_total > 0 else Decimal(0)

        return OrderResult(
            order_id=str(order.id),
            status="filled",
            side=data.side,
            outcome=data.outcome,
            shares=total_shares,
            price=avg_price,
            price_before=price_before,
            price_after=amm_price_val if amm_price_val > 0 else avg_price,
            yes_price_after=yes_price_after,
            no_price_after=no_price_after,
            slippage=amm_slippage,
            fee=amm_fee,
            wallet_balance=wallet.balance,
        )

    @staticmethod
    async def cancel_order(
        db: AsyncSession,
        user: User,
        order_id: str,
    ):
        result = await db.execute(
            select(Order).where(
                Order.id == order_id,
                Order.user_id == user.id,
                Order.status == "pending",
            ).with_for_update()
        )
        order = result.scalar_one_or_none()
        if not order:
            raise NotFoundError("Pending order not found")

        order.status = "cancelled"
        order.executed_at = datetime.now(UTC)

        if order.side == "buy" and order.amount > 0:
            wallet = await db.execute(
                select(Wallet).where(Wallet.user_id == user.id).with_for_update()
            )
            wallet = wallet.scalar_one_or_none()
            if wallet:
                wallet.locked_balance = max(Decimal(0), wallet.locked_balance - order.amount)

        await db.commit()
        logger.info(f"Order cancelled: {order_id} by user={user.id}")
