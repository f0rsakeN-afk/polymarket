import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import NotFoundError, ValidationError
from app.api.responses import success_response
from app.database import get_db
from app.deps import get_current_user
from app.models.liquidity import LiquidityPool
from app.models.market import Market, Outcome
from app.models.position import Position
from app.models.wallet import Transaction, Wallet
from app.services.market_service import MarketService
from app.websocket.manager import redis_pubsub

logger = logging.getLogger("polymarket")
SPLIT_MERGE_FEE_RATE = Decimal("0.02")
router = APIRouter(prefix="/split-merge", tags=["split-merge"])


@router.post("/split", summary="Split USDC into equal YES+NO shares")
async def split(
    market_id: str,
    amount: float,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Convert USDC into equal amounts of YES and NO shares.

    A 2% fee is deducted from the split amount. The average_price for each
    position is set to the current AMM market price at the time of split,
    giving accurate unrealized PnL display.
    """
    user = await get_current_user(request, db)
    amount_dec = Decimal(str(amount))

    if amount_dec <= 0:
        raise ValidationError("Amount must be positive")

    market_result = await db.execute(
        select(Market).where(Market.id == market_id).with_for_update()
    )
    market = market_result.scalar_one_or_none()
    if not market:
        raise NotFoundError("Market not found")
    if market.status != "active":
        raise ValidationError("Market is not active")

    outcomes_result = await db.execute(
        select(Outcome).where(Outcome.market_id == market.id).order_by(Outcome.outcome_index)
    )
    outcomes = outcomes_result.scalars().all()
    if len(outcomes) < 2:
        raise ValidationError("Market must have both YES and NO outcomes")

    yes_outcome = outcomes[0]
    no_outcome = outcomes[1]

    pool_result = await db.execute(
        select(LiquidityPool).where(LiquidityPool.market_id == market.id).with_for_update()
    )
    pool = pool_result.scalar_one_or_none()

    yes_price, no_price = MarketService.compute_prices(pool)

    wallet_result = await db.execute(
        select(Wallet).where(Wallet.user_id == user.id).with_for_update()
    )
    wallet = wallet_result.scalar_one_or_none()
    if not wallet:
        raise NotFoundError("Wallet not found")

    available = wallet.balance - wallet.locked_balance
    if amount_dec > available:
        raise ValidationError("Insufficient balance")

    fee = amount_dec * SPLIT_MERGE_FEE_RATE
    amount_after_fee = amount_dec - fee
    wallet.balance -= amount_dec

    async def update_position(outcome_obj, avg_price):
        pos_result = await db.execute(
            select(Position).where(
                Position.user_id == user.id,
                Position.market_id == market.id,
                Position.outcome_id == outcome_obj.id,
            ).with_for_update()
        )
        pos = pos_result.scalar_one_or_none()
        if pos is not None:
            total_cost = pos.average_price * pos.shares_held + amount_after_fee
            pos.shares_held += amount_after_fee
            pos.average_price = total_cost / pos.shares_held
        else:
            avg_p = Decimal(str(avg_price))
            # Atomic upsert — eliminates SELECT-then-INSERT race
            await db.execute(
                text("""
                    INSERT INTO positions (id, user_id, market_id, outcome_id, shares_held, average_price, realized_pnl, settled_at, created_at, updated_at)
                    VALUES (gen_random_uuid(), :user_id, :market_id, :outcome_id, :shares_held, :average_price, 0, NULL, NOW(), NOW())
                    ON CONFLICT (user_id, market_id, outcome_id)
                    DO UPDATE SET shares_held = positions.shares_held + EXCLUDED.shares_held,
                                 average_price = (positions.average_price * positions.shares_held + EXCLUDED.average_price * EXCLUDED.shares_held) / (positions.shares_held + EXCLUDED.shares_held)
                """),
                {
                    "user_id": user.id,
                    "market_id": market.id,
                    "outcome_id": outcome_obj.id,
                    "shares_held": amount_after_fee,
                    "average_price": avg_p,
                }
            )

    await update_position(yes_outcome, yes_price)
    await update_position(no_outcome, no_price)

    tx = Transaction(
        user_id=user.id,
        wallet_id=wallet.id,
        type="split",
        amount=-amount_dec,
        balance_after=wallet.balance,
        status="completed",
    )
    db.add(tx)

    await db.commit()

    logger.info(f"Split: user={user.id} market={market_id} amount={amount} fee={float(fee)}")

    # Publish WS events — split changes the supply of YES/NO shares in circulation
    try:
        yes_price, no_price = MarketService.compute_prices(pool)
        await redis_pubsub.publish_price_update(
            str(market.id), float(yes_price), float(no_price), float(market.total_liquidity or 0)
        )
        await redis_pubsub.publish_market_event(str(market.id), "split", {
            "user_id": str(user.id),
            "amount": float(amount),
            "fee": float(fee),
            "yes_shares": float(amount_after_fee),
            "no_shares": float(amount_after_fee),
        })
    except Exception:
        pass

    return success_response({
        "market_id": market_id,
        "amount": amount,
        "fee": str(fee),
        "yes_price": str(yes_price),
        "no_price": str(no_price),
        "yes_shares": str(amount_after_fee),
        "no_shares": str(amount_after_fee),
        "balance_after": str(wallet.balance),
    }, message="Liquidity split successfully")


@router.post("/merge", summary="Merge equal YES+NO shares back into USDC")
async def merge(
    market_id: str,
    amount: float,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Convert equal YES and NO shares back into USDC.

    A 2% fee is deducted from the merged amount. You must hold at least
    `amount` shares of BOTH YES and NO to perform a merge.
    """
    user = await get_current_user(request, db)
    amount_dec = Decimal(str(amount))

    if amount_dec <= 0:
        raise ValidationError("Amount must be positive")

    market_result = await db.execute(
        select(Market).where(Market.id == market_id).with_for_update()
    )
    market = market_result.scalar_one_or_none()
    if not market:
        raise NotFoundError("Market not found")

    outcomes_result = await db.execute(
        select(Outcome).where(Outcome.market_id == market.id).order_by(Outcome.outcome_index)
    )
    outcomes = outcomes_result.scalars().all()
    if len(outcomes) < 2:
        raise ValidationError("Market must have both YES and NO outcomes")

    yes_outcome = outcomes[0]
    no_outcome = outcomes[1]

    yes_pos_result = await db.execute(
        select(Position).where(
            Position.user_id == user.id,
            Position.market_id == market.id,
            Position.outcome_id == yes_outcome.id,
        ).with_for_update()
    )
    yes_pos = yes_pos_result.scalar_one_or_none()

    no_pos_result = await db.execute(
        select(Position).where(
            Position.user_id == user.id,
            Position.market_id == market.id,
            Position.outcome_id == no_outcome.id,
        ).with_for_update()
    )
    no_pos = no_pos_result.scalar_one_or_none()

    if not yes_pos or yes_pos.shares_held < amount_dec:
        raise ValidationError(f"Insufficient YES shares (held: {float(yes_pos.shares_held) if yes_pos else 0}, needed: {amount})")
    if not no_pos or no_pos.shares_held < amount_dec:
        raise ValidationError(f"Insufficient NO shares (held: {float(no_pos.shares_held) if no_pos else 0}, needed: {amount})")

    wallet_result = await db.execute(
        select(Wallet).where(Wallet.user_id == user.id).with_for_update()
    )
    wallet = wallet_result.scalar_one_or_none()

    fee = amount_dec * SPLIT_MERGE_FEE_RATE
    amount_after_fee = amount_dec - fee

    yes_pos.shares_held -= amount_dec
    no_pos.shares_held -= amount_dec
    wallet.balance += amount_after_fee

    if yes_pos.shares_held == 0:
        await db.delete(yes_pos)
    if no_pos.shares_held == 0:
        await db.delete(no_pos)

    tx = Transaction(
        user_id=user.id,
        wallet_id=wallet.id,
        type="merge",
        amount=amount_after_fee,
        balance_after=wallet.balance,
        status="completed",
    )
    db.add(tx)

    await db.commit()

    logger.info(f"Merge: user={user.id} market={market_id} amount={amount} fee={float(fee)}")

    # Publish WS events — merge removes YES/NO shares from circulation
    try:
        pool_result = await db.execute(
            select(LiquidityPool).where(LiquidityPool.market_id == market.id)
        )
        pool = pool_result.scalar_one_or_none()
        if pool:
            yes_price, no_price = MarketService.compute_prices(pool)
            await redis_pubsub.publish_price_update(
                str(market.id), float(yes_price), float(no_price), float(market.total_liquidity or 0)
            )
        await redis_pubsub.publish_market_event(str(market.id), "merge", {
            "user_id": str(user.id),
            "amount": float(amount),
            "fee": float(fee),
            "amount_received": float(amount_after_fee),
        })
    except Exception:
        pass

    return success_response({
        "market_id": market_id,
        "amount": amount,
        "fee": str(fee),
        "amount_received": str(amount_after_fee),
        "balance_after": str(wallet.balance),
    }, message="Liquidity merged successfully")
