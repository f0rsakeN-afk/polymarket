import logging
from decimal import Decimal
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.market import Market, Outcome
from app.models.liquidity import LiquidityPool, LPShare
from app.models.wallet import Wallet, Transaction
from app.api.responses import success_response
from app.api.exceptions import NotFoundError, ValidationError

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/markets", tags=["liquidity"])


def _pool_price(pool: LiquidityPool) -> Decimal:
    total = float(pool.yes_shares) + float(pool.no_shares)
    if total == 0:
        return Decimal("0.5")
    return Decimal(str(float(pool.yes_shares) / total))


@router.post("/{market_id}/liquidity", summary="Add liquidity", description="Add liquidity to a market's AMM pool and receive LP tokens proportional to your contribution.")
async def add_liquidity(
    market_id: str,
    amount: float,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Add liquidity to a market pool. LP tokens are minted proportionally."""
    user = await get_current_user(request, db)
    amount_dec = Decimal(str(amount))

    if amount_dec <= 0:
        raise ValidationError("Amount must be positive")

    # Lock market with FOR UPDATE before checking status (lock ordering: market → pool)
    market_result = await db.execute(
        select(Market).where(Market.id == market_id).with_for_update()
    )
    market = market_result.scalar_one_or_none()
    if not market:
        raise NotFoundError("Market not found")
    if market.status != "active":
        raise ValidationError("Market is not active for liquidity provision")

    pool_result = await db.execute(
        select(LiquidityPool).where(LiquidityPool.market_id == market.id).with_for_update()
    )
    pool = pool_result.scalar_one_or_none()
    if not pool:
        raise ValidationError("Market has no liquidity pool")

    wallet_result = await db.execute(
        select(Wallet).where(Wallet.user_id == user.id).with_for_update()
    )
    wallet = wallet_result.scalar_one_or_none()
    if not wallet:
        raise ValidationError("Wallet not found")

    available = wallet.balance - wallet.locked_balance
    if amount_dec > available:
        raise ValidationError({
            "available": float(available),
            "requested": float(amount_dec),
        })

    # Compute LP tokens minted: proportional share of the pool
    # Both operands are Decimal — no float contamination
    if float(pool.lp_token_supply) > 0:
        pool_total = pool.yes_shares + pool.no_shares
        lp_tokens_minted = (amount_dec * pool.lp_token_supply) / pool_total
    else:
        # First LP: tokens = amount * 2 (initial equal split)
        lp_tokens_minted = amount_dec * Decimal("2")

    # Add to YES and NO pools equally
    collateral_each = amount_dec / Decimal("2")
    pool.yes_shares += collateral_each
    pool.no_shares += collateral_each
    pool.collateral += amount_dec

    # Update or create LP share
    lp_result = await db.execute(
        select(LPShare).where(LPShare.pool_id == pool.id, LPShare.user_id == user.id).with_for_update()
    )
    lp_share = lp_result.scalar_one_or_none()
    if lp_share:
        lp_share.lp_tokens += lp_tokens_minted
        lp_share.collateral_deposited += amount_dec
    else:
        lp_share = LPShare(
            pool_id=pool.id,
            user_id=user.id,
            lp_tokens=lp_tokens_minted,
            collateral_deposited=amount_dec,
        )
        db.add(lp_share)

    pool.lp_token_supply += lp_tokens_minted

    # Deduct from wallet
    wallet.balance -= amount_dec

    # Transaction record
    tx = Transaction(
        user_id=user.id,
        wallet_id=wallet.id,
        type="liquidity_add",
        amount=-float(amount_dec),
        balance_after=wallet.balance,
        reference_id=str(pool.id),
        reference_type="liquidity_pool",
        status="completed",
    )
    db.add(tx)
    await db.commit()

    logger.info(f"Liquidity added: user={user.id} market={market.slug} amount={amount} lp_tokens={float(lp_tokens_minted)}")
    return success_response({
        "lp_tokens_minted": float(lp_tokens_minted),
        "pool_lp_token_supply": float(pool.lp_token_supply),
        "wallet_balance": float(wallet.balance),
    })


@router.delete("/{market_id}/liquidity", summary="Remove liquidity", description="Burn LP tokens to redeem proportional share of YES and NO pool collateral.")
async def remove_liquidity(
    market_id: str,
    lp_tokens: float,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Remove liquidity and burn LP tokens. Receives proportional share of YES and NO pool."""
    user = await get_current_user(request, db)
    lp_tokens_dec = Decimal(str(lp_tokens))

    if lp_tokens_dec <= 0:
        raise ValidationError("LP tokens must be positive")

    market = await db.get(Market, market_id)
    if not market:
        raise NotFoundError("Market not found")

    pool_result = await db.execute(
        select(LiquidityPool).where(LiquidityPool.market_id == market.id).with_for_update()
    )
    pool = pool_result.scalar_one_or_none()
    if not pool:
        raise ValidationError("Market has no liquidity pool")

    lp_result = await db.execute(
        select(LPShare).where(LPShare.pool_id == pool.id, LPShare.user_id == user.id).with_for_update()
    )
    lp_share = lp_result.scalar_one_or_none()
    if not lp_share or lp_share.lp_tokens < lp_tokens_dec:
        raise ValidationError("Insufficient LP tokens")

    wallet_result = await db.execute(
        select(Wallet).where(Wallet.user_id == user.id).with_for_update()
    )
    wallet = wallet_result.scalar_one_or_none()
    if not wallet:
        raise ValidationError("Wallet not found")

    # Proportional redemption from YES and NO pools
    lp_fraction = lp_tokens_dec / pool.lp_token_supply
    yes_redeemed = pool.yes_shares * lp_fraction
    no_redeemed = pool.no_shares * lp_fraction
    total_redeemed = yes_redeemed + no_redeemed

    # Update pool
    pool.yes_shares -= yes_redeemed
    pool.no_shares -= no_redeemed
    pool.lp_token_supply -= lp_tokens_dec

    # Update LP share
    lp_share.lp_tokens -= lp_tokens_dec
    lp_share.collateral_deposited -= total_redeemed

    # Credit wallet
    wallet.balance += total_redeemed

    # Transaction record
    tx = Transaction(
        user_id=user.id,
        wallet_id=wallet.id,
        type="liquidity_remove",
        amount=float(total_redeemed),
        balance_after=wallet.balance,
        reference_id=str(pool.id),
        reference_type="liquidity_pool",
        status="completed",
    )
    db.add(tx)
    await db.commit()

    logger.info(f"Liquidity removed: user={user.id} market={market.slug} lp_tokens={lp_tokens} redeemed={float(total_redeemed)}")
    return success_response({
        "yes_redeemed": float(yes_redeemed),
        "no_redeemed": float(no_redeemed),
        "total_redeemed": float(total_redeemed),
        "wallet_balance": float(wallet.balance),
    })


@router.get("/{market_id}/liquidity", summary="Get LP position", description="Get the authenticated user's LP share for a market.")
async def get_lp_position(
    market_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get LP position for the current user."""
    user = await get_current_user(request, db)

    market = await db.get(Market, market_id)
    if not market:
        raise NotFoundError("Market not found")

    pool = await db.execute(select(LiquidityPool).where(LiquidityPool.market_id == market.id))
    pool = pool.scalar_one_or_none()

    lp_result = await db.execute(
        select(LPShare).where(LPShare.pool_id == pool.id, LPShare.user_id == user.id)
    )
    lp_share = lp_result.scalar_one_or_none()

    if not lp_share:
        return success_response({
            "lp_tokens": 0.0,
            "collateral_deposited": 0.0,
            "pool_lp_token_supply": float(pool.lp_token_supply) if pool else 0.0,
            "pool_yes_shares": float(pool.yes_shares) if pool else 0.0,
            "pool_no_shares": float(pool.no_shares) if pool else 0.0,
        })

    return success_response({
        "lp_tokens": float(lp_share.lp_tokens),
        "collateral_deposited": float(lp_share.collateral_deposited),
        "pool_lp_token_supply": float(pool.lp_token_supply),
        "pool_yes_shares": float(pool.yes_shares),
        "pool_no_shares": float(pool.no_shares),
    })
