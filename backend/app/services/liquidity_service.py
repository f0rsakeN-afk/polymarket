import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import NotFoundError, ValidationError
from app.models.liquidity import LiquidityPool, LPShare
from app.models.market import Market
from app.models.user import User
from app.models.wallet import Transaction, Wallet

logger = logging.getLogger("polymarket")


class LiquidityService:

    @staticmethod
    async def add_liquidity(
        db: AsyncSession,
        user: User,
        market_id: str,
        amount: Decimal,
    ) -> dict:
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
        if amount > available:
            raise ValidationError({
                "available": float(available),
                "requested": float(amount),
            })

        if float(pool.lp_token_supply) > 0:
            pool_total = pool.yes_shares + pool.no_shares
            lp_tokens_minted = (amount * pool.lp_token_supply) / pool_total
        else:
            lp_tokens_minted = amount * Decimal(2)

        collateral_each = amount / Decimal(2)
        pool.yes_shares += collateral_each
        pool.no_shares += collateral_each
        pool.collateral += amount

        lp_result = await db.execute(
            select(LPShare).where(LPShare.pool_id == pool.id, LPShare.user_id == user.id).with_for_update()
        )
        lp_share = lp_result.scalar_one_or_none()
        if lp_share:
            lp_share.lp_tokens += lp_tokens_minted
            lp_share.collateral_deposited += amount
        else:
            lp_share = LPShare(
                pool_id=pool.id,
                user_id=user.id,
                lp_tokens=lp_tokens_minted,
                collateral_deposited=amount,
            )
            db.add(lp_share)

        pool.lp_token_supply += lp_tokens_minted
        wallet.balance -= amount

        tx = Transaction(
            user_id=user.id,
            wallet_id=wallet.id,
            type="liquidity_add",
            amount=-float(amount),
            balance_after=wallet.balance,
            reference_id=str(pool.id),
            reference_type="liquidity_pool",
            status="completed",
        )
        db.add(tx)
        await db.commit()

        logger.info(f"Liquidity added: user={user.id} market={market.slug} amount={float(amount)} lp_tokens={float(lp_tokens_minted)}")

        return {
            "lp_tokens_minted": float(lp_tokens_minted),
            "pool_lp_token_supply": float(pool.lp_token_supply),
            "wallet_balance": float(wallet.balance),
        }

    @staticmethod
    async def remove_liquidity(
        db: AsyncSession,
        user: User,
        market_id: str,
        lp_tokens: Decimal,
    ) -> dict:
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
        if not lp_share or lp_share.lp_tokens < lp_tokens:
            raise ValidationError("Insufficient LP tokens")

        wallet_result = await db.execute(
            select(Wallet).where(Wallet.user_id == user.id).with_for_update()
        )
        wallet = wallet_result.scalar_one_or_none()
        if not wallet:
            raise ValidationError("Wallet not found")

        lp_fraction = lp_tokens / pool.lp_token_supply
        yes_redeemed = pool.yes_shares * lp_fraction
        no_redeemed = pool.no_shares * lp_fraction
        total_redeemed = yes_redeemed + no_redeemed

        pool.yes_shares -= yes_redeemed
        pool.no_shares -= no_redeemed
        pool.lp_token_supply -= lp_tokens

        lp_share.lp_tokens -= lp_tokens
        lp_share.collateral_deposited -= total_redeemed
        wallet.balance += total_redeemed

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

        logger.info(f"Liquidity removed: user={user.id} market={market.slug} lp_tokens={float(lp_tokens)} redeemed={float(total_redeemed)}")

        return {
            "yes_redeemed": float(yes_redeemed),
            "no_redeemed": float(no_redeemed),
            "total_redeemed": float(total_redeemed),
            "wallet_balance": float(wallet.balance),
        }
