import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import NotFoundError, ValidationError
from app.api.responses import success_response
from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models.liquidity import LiquidityPool
from app.models.market import Market, Outcome
from app.models.position import Position
from app.models.wallet import Transaction, Wallet
from app.schemas.split_merge import SplitMergeRequest
from app.services.market_service import MarketService
from app.websocket.manager import redis_pubsub

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/split-merge", tags=["split-merge"])


@router.post("/split", summary="Split USDC into equal YES+NO shares")
async def split(
    data: SplitMergeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Convert USDC into equal amounts of YES and NO shares.

    A 2% fee is deducted from the split amount. The average_price for each
    position is set to the current AMM market price at the time of split,
    giving accurate unrealized PnL display.
    """
    user = await get_current_user(request, db)
    market_id: str = data.market_id
    amount: Decimal = data.amount
    amount_dec = amount

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

    fee = amount_dec * settings.split_merge_fee_rate
    amount_after_fee = amount_dec - fee
    wallet.balance -= amount_dec
    # Route the fee to the pool's protocol ledger (swept to treasury at
    # settlement) instead of burning it. The whole deposit is escrowed:
    # protocol_fees is a sub-ledger *inside* pool.collateral, so the fee
    # portion stays recorded as owed while backing the shares just minted.
    if pool is not None:
        pool.credit_collateral(amount_dec)
        pool.protocol_fees += fee
        # A split mints `amount_after_fee` shares of EACH side — real new
        # supply the AMM now has to be able to hand back out. The trade legs
        # already keep pool reserves in step with minted/burned shares, so
        # these two lines match them; without them the shares created here
        # cannot be sold into the AMM (amm.sell refuses to pay out more than
        # the reserve holds) even though the user legitimately owns them.
        # Both sides grow equally, so the price ratio is unchanged.
        pool.yes_shares += amount_after_fee
        pool.no_shares += amount_after_fee

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
        "amount": str(amount),
        "fee": str(fee),
        "yes_price": str(yes_price),
        "no_price": str(no_price),
        "yes_shares": str(amount_after_fee),
        "no_shares": str(amount_after_fee),
        "balance_after": str(wallet.balance),
    }, message="Liquidity split successfully")


@router.post("/merge", summary="Merge equal YES+NO shares back into USDC")
async def merge(
    data: SplitMergeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Convert equal YES and NO shares back into USDC.

    A 2% fee is deducted from the merged amount. You must hold at least
    `amount` shares of BOTH YES and NO to perform a merge.
    """
    user = await get_current_user(request, db)
    market_id: str = data.market_id
    amount: Decimal = data.amount
    amount_dec = amount

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

    # Lock order market -> pool -> wallet -> position matches the trading
    # path and standardizes lock ordering to prevent deadlocks. (The pool
    # lock used to be taken *after* the wallet — a split holds pool-then-
    # wallet while merge held wallet-then-pool, i.e. a genuine ABBA deadlock
    # waiting to happen under concurrent split/merge on the same market.)
    pool_result = await db.execute(
        select(LiquidityPool).where(LiquidityPool.market_id == market.id).with_for_update()
    )
    pool = pool_result.scalar_one_or_none()

    wallet_result = await db.execute(
        select(Wallet).where(Wallet.user_id == user.id).with_for_update()
    )
    wallet = wallet_result.scalar_one_or_none()
    if not wallet:
        raise NotFoundError("Wallet not found")

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

    # You must actually hold `amount` shares of BOTH sides. Without this check
    # a user could merge shares they don't own and drive balances negative
    # (or crash on a missing position row).
    if yes_pos is None or yes_pos.shares_held < amount_dec:
        held = yes_pos.shares_held if yes_pos is not None else Decimal(0)
        raise ValidationError(f"Insufficient YES shares: held={held}, requested={amount_dec}")
    if no_pos is None or no_pos.shares_held < amount_dec:
        held = no_pos.shares_held if no_pos is not None else Decimal(0)
        raise ValidationError(f"Insufficient NO shares: held={held}, requested={amount_dec}")

    fee = amount_dec * settings.split_merge_fee_rate
    amount_after_fee = amount_dec - fee
    if pool is not None:
        pool.protocol_fees += fee

    # Realize PnL per side: each destroyed pair returns amount_after_fee/2
    # against its cost basis. Rows are kept at 0 shares (positions endpoint
    # filters them) so realized history survives full closes.
    proceeds_per_side = amount_after_fee / 2
    yes_pos.realized_pnl += proceeds_per_side - yes_pos.average_price * amount_dec
    no_pos.realized_pnl += proceeds_per_side - no_pos.average_price * amount_dec

    yes_pos.shares_held -= amount_dec
    no_pos.shares_held -= amount_dec
    wallet.balance += amount_after_fee
    # The destroyed pairs release exactly `amount_after_fee` of escrow; the
    # fee stays behind in the pool (it was recorded above). Strict debit —
    # if the escrow can't cover the merge the ledger is broken, roll back.
    if pool is not None:
        pool.debit_collateral(amount_after_fee)
        # Mirror of the split above: a merge destroys `amount` shares of each
        # side, so the AMM reserves shrink by the same amount (both equally,
        # so the price ratio is unchanged). Clamped at zero because pools
        # created before this sync can carry reserves below the real supply —
        # a clamp is logged so the drift is visible instead of silent.
        before_yes, before_no = pool.yes_shares, pool.no_shares
        pool.yes_shares = max(Decimal(0), pool.yes_shares - amount_dec)
        pool.no_shares = max(Decimal(0), pool.no_shares - amount_dec)
        if before_yes < amount_dec or before_no < amount_dec:
            logger.warning(
                f"Merge clamped pool reserves on market {market_id}: "
                f"yes {before_yes}→{pool.yes_shares}, no {before_no}→{pool.no_shares} "
                f"for amount={amount_dec} (reserves were below the burned supply)"
            )

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
        "amount": str(amount),
        "fee": str(fee),
        "amount_received": str(amount_after_fee),
        "balance_after": str(wallet.balance),
    }, message="Liquidity merged successfully")
