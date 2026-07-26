import logging
from datetime import datetime, timezone
from decimal import Decimal
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import Market, Outcome
from app.models.order import Order
from app.models.position import Position
from app.models.wallet import Wallet, Transaction
from app.models.trade import Trade
from app.models.user import User

logger = logging.getLogger("polymarket")


@dataclass
class MatchResult:
    matched_shares: Decimal
    matched_usdc: Decimal
    match_details: list[dict]


class MatchingEngine:

    @staticmethod
    async def find_matches(
        db: AsyncSession,
        market_id: str,
        outcome_id: str,
        side: str,
        limit_price: Decimal | None = None,
        exclude_user_id: str | None = None,
    ) -> list[Order]:
        opposite = "sell" if side == "buy" else "buy"

        if side == "buy" and limit_price is not None:
            price_filter = Order.price <= limit_price
        elif side == "sell" and limit_price is not None:
            price_filter = Order.price >= limit_price
        else:
            price_filter = True

        user_filter = Order.user_id != exclude_user_id if exclude_user_id else True

        result = await db.execute(
            select(Order)
            .where(
                Order.market_id == market_id,
                Order.outcome_id == outcome_id,
                Order.side == opposite,
                Order.status.in_(["pending", "partial"]),
                Order.remaining_amount > 0,
                price_filter,
                user_filter,
            )
            .order_by(
                Order.price.desc() if side == "sell" else Order.price.asc(),
                Order.created_at.asc(),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def execute_match(
        db: AsyncSession,
        maker: Order,
        taker_user_id: str,
        match_shares: Decimal,
        match_price: Decimal,
    ) -> dict:
        maker_user = await db.get(User, maker.user_id)
        maker_wallet = await db.execute(
            select(Wallet).where(Wallet.user_id == maker.user_id).with_for_update()
        )
        maker_wallet = maker_wallet.scalar_one_or_none()

        outcome = await db.get(Outcome, maker.outcome_id)
        outcome_name = outcome.name.lower() if outcome else "unknown"

        usdc_value = match_shares * match_price
        fee = usdc_value * Decimal("0.01")

        if maker.side == "buy":
            buyer_user_id = str(maker.user_id)
            seller_user_id = taker_user_id
            buyer_wallet = maker_wallet
            seller_wallet = await db.execute(
                select(Wallet).where(Wallet.user_id == taker_user_id).with_for_update()
            )
            seller_wallet = seller_wallet.scalar_one_or_none()
        else:
            seller_user_id = str(maker.user_id)
            buyer_user_id = taker_user_id
            seller_wallet = maker_wallet
            buyer_wallet = await db.execute(
                select(Wallet).where(Wallet.user_id == taker_user_id).with_for_update()
            )
            buyer_wallet = buyer_wallet.scalar_one_or_none()

        if buyer_wallet:
            buyer_wallet.balance -= usdc_value

        if seller_wallet:
            seller_wallet.balance += usdc_value - fee

        maker.remaining_amount -= match_shares
        if maker.remaining_amount <= 0:
            maker.status = "filled"
            maker.executed_at = datetime.now(timezone.utc)
        else:
            maker.status = "partial"

        if maker.side == "buy" and maker_wallet:
            locked_release = min(maker.amount - maker.remaining_amount, match_shares * maker.price)
            maker_wallet.locked_balance = max(
                Decimal("0"), maker_wallet.locked_balance - locked_release
            )

        trade = Trade(
            user_id=maker.user_id,
            market_id=maker.market_id,
            outcome=outcome_name,
            side=maker.side,
            price=match_price,
            amount=match_shares,
            executed_at=datetime.now(timezone.utc),
        )
        db.add(trade)

        trade_taker = Trade(
            user_id=taker_user_id,
            market_id=maker.market_id,
            outcome=outcome_name,
            side="sell" if maker.side == "buy" else "buy",
            price=match_price,
            amount=match_shares,
            executed_at=datetime.now(timezone.utc),
        )
        db.add(trade_taker)

        if maker.side == "buy":
            seller_pos = await db.execute(
                select(Position).where(
                    Position.user_id == taker_user_id,
                    Position.market_id == maker.market_id,
                    Position.outcome_id == maker.outcome_id,
                ).with_for_update()
            )
            seller_pos = seller_pos.scalar_one_or_none()
            if seller_pos:
                cost_basis = seller_pos.average_price * match_shares
                realized_pnl = usdc_value - cost_basis
                seller_pos.shares_held -= match_shares
                seller_pos.realized_pnl += realized_pnl

            buyer_pos = await db.execute(
                select(Position).where(
                    Position.user_id == maker.user_id,
                    Position.market_id == maker.market_id,
                    Position.outcome_id == maker.outcome_id,
                ).with_for_update()
            )
            buyer_pos = buyer_pos.scalar_one_or_none()
            if buyer_pos:
                total_shares = buyer_pos.shares_held + match_shares
                buyer_pos.average_price = (
                    buyer_pos.average_price * buyer_pos.shares_held + usdc_value
                ) / total_shares if total_shares > 0 else Decimal("0")
                buyer_pos.shares_held = total_shares
            else:
                buyer_pos = Position(
                    user_id=maker.user_id,
                    market_id=maker.market_id,
                    outcome_id=maker.outcome_id,
                    shares_held=match_shares,
                    average_price=match_price,
                )
                db.add(buyer_pos)
        else:
            buyer_pos = await db.execute(
                select(Position).where(
                    Position.user_id == taker_user_id,
                    Position.market_id == maker.market_id,
                    Position.outcome_id == maker.outcome_id,
                ).with_for_update()
            )
            buyer_pos = buyer_pos.scalar_one_or_none()
            if buyer_pos:
                total_shares = buyer_pos.shares_held + match_shares
                buyer_pos.average_price = (
                    buyer_pos.average_price * buyer_pos.shares_held + usdc_value
                ) / total_shares if total_shares > 0 else Decimal("0")
                buyer_pos.shares_held = total_shares
            else:
                buyer_pos = Position(
                    user_id=taker_user_id,
                    market_id=maker.market_id,
                    outcome_id=maker.outcome_id,
                    shares_held=match_shares,
                    average_price=match_price,
                )
                db.add(buyer_pos)

            seller_pos = await db.execute(
                select(Position).where(
                    Position.user_id == maker.user_id,
                    Position.market_id == maker.market_id,
                    Position.outcome_id == maker.outcome_id,
                ).with_for_update()
            )
            seller_pos = seller_pos.scalar_one_or_none()
            if seller_pos:
                cost_basis = seller_pos.average_price * match_shares
                realized_pnl = usdc_value - cost_basis
                seller_pos.shares_held -= match_shares
                seller_pos.realized_pnl += realized_pnl

        return {
            "match_price": match_price,
            "match_shares": match_shares,
            "match_usdc": usdc_value,
            "maker_order_id": str(maker.id),
            "maker_user_id": str(maker.user_id),
            "side": maker.side,
            "outcome": outcome_name,
        }

    @staticmethod
    async def match_order_against_book(
        db: AsyncSession,
        market: Market,
        outcome: Outcome,
        side: str,
        amount: Decimal,
        limit_price: Decimal | None = None,
        taker_user_id: str | None = None,
    ) -> tuple[Decimal, Decimal, list[dict]]:
        matches = await MatchingEngine.find_matches(
            db, str(market.id), outcome.id, side, limit_price, exclude_user_id=taker_user_id
        )

        matched_shares = Decimal("0")
        matched_usdc = Decimal("0")
        match_details = []

        for maker in matches:
            if side == "buy":
                max_buyable = (amount - matched_usdc) / maker.price
                if max_buyable <= 0:
                    break
                match_qty = min(maker.remaining_amount, max_buyable)
                if match_qty == 0:
                    break
                cost = match_qty * maker.price
                matched_shares += match_qty
                matched_usdc += cost
            else:
                remaining_shares = amount - matched_shares
                if remaining_shares <= 0:
                    break
                match_qty = min(maker.remaining_amount, remaining_shares)
                if match_qty == 0:
                    break
                cost = match_qty * maker.price
                matched_shares += match_qty
                matched_usdc += cost

            result = await MatchingEngine.execute_match(
                db, maker, taker_user_id or "system", match_qty, maker.price
            )
            match_details.append(result)

        return matched_shares, matched_usdc, match_details

    @staticmethod
    async def match_pending_order(
        db: AsyncSession,
        order: Order,
        market: Market,
        outcome: Outcome,
    ) -> tuple[Decimal, list[dict]]:
        remaining = order.remaining_amount
        matched_details = []

        matches = await MatchingEngine.find_matches(
            db, str(market.id), outcome.id, order.side, order.price,
            exclude_user_id=str(order.user_id),
        )

        for maker in matches:
            if remaining <= 0:
                break
            match_qty = min(maker.remaining_amount, remaining)
            if match_qty <= 0:
                break
            remaining -= match_qty

            result = await MatchingEngine.execute_match(
                db, maker, str(order.user_id), match_qty, maker.price
            )
            matched_details.append(result)

            order.remaining_amount -= match_qty
            if order.remaining_amount <= 0:
                order.status = "filled"
                order.executed_at = datetime.now(timezone.utc)
            elif order.status != "filled":
                order.status = "partial"

        return remaining, matched_details
