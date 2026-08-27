import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import NotFoundError, ValidationError
from app.models.liquidity import LiquidityPool, LPShare
from app.models.market import Market
from app.models.user import User
from app.models.wallet import Transaction, Wallet
from app.services.market_service import MarketService
from app.websocket.manager import redis_pubsub

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
            raise ValidationError(
                f"Insufficient balance: available={float(available)}, requested={float(amount)}",
                details={"available": float(available), "requested": float(amount)},
            )

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
        market.total_liquidity = (market.total_liquidity or Decimal(0)) + amount
        wallet.balance -= amount

        tx = Transaction(
            user_id=user.id,
            wallet_id=wallet.id,
            type="liquidity_add",
            amount=-amount,
            balance_after=wallet.balance,
            reference_id=str(pool.id),
            reference_type="liquidity_pool",
            status="completed",
        )
        db.add(tx)
        await db.commit()

        logger.info(f"Liquidity added: user={user.id} market={market.slug} amount={float(amount)} lp_tokens={float(lp_tokens_minted)}")

        # Publish WS events — liquidity changes affect AMM prices
        try:
            yes_price, no_price = MarketService.compute_prices(pool)
            await redis_pubsub.publish_price_update(
                str(market.id), float(yes_price), float(no_price), float(market.total_liquidity or 0)
            )
            await redis_pubsub.publish_market_event(str(market.id), "liquidity:add", {
                "user_id": str(user.id),
                "amount": float(amount),
                "lp_tokens": float(lp_tokens_minted),
                "pool_lp_token_supply": float(pool.lp_token_supply),
            })
        except Exception:
            pass

        return {
            "lp_tokens_minted": str(lp_tokens_minted),
            "pool_lp_token_supply": str(pool.lp_token_supply),
            "wallet_balance": str(wallet.balance),
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

        if pool.lp_token_supply == 0:
            raise ValidationError("No LP tokens outstanding")
        lp_fraction = lp_tokens / pool.lp_token_supply
        yes_redeemed = pool.yes_shares * lp_fraction
        no_redeemed = pool.no_shares * lp_fraction
        total_redeemed = yes_redeemed + no_redeemed

        pool.yes_shares -= yes_redeemed
        pool.no_shares -= no_redeemed
        market.total_liquidity = max(Decimal(0), (market.total_liquidity or Decimal(0)) - total_redeemed)
        pool.lp_token_supply -= lp_tokens

        lp_share.lp_tokens -= lp_tokens
        lp_share.collateral_deposited -= total_redeemed
        wallet.balance += total_redeemed

        tx = Transaction(
            user_id=user.id,
            wallet_id=wallet.id,
            type="liquidity_remove",
            amount=total_redeemed,
            balance_after=wallet.balance,
            reference_id=str(pool.id),
            reference_type="liquidity_pool",
            status="completed",
        )
        db.add(tx)
        await db.commit()

        logger.info(f"Liquidity removed: user={user.id} market={market.slug} lp_tokens={float(lp_tokens)} redeemed={float(total_redeemed)}")

        # Publish WS events — liquidity changes affect AMM prices
        try:
            yes_price, no_price = MarketService.compute_prices(pool)
            await redis_pubsub.publish_price_update(
                str(market.id), float(yes_price), float(no_price), float(market.total_liquidity or 0)
            )
            await redis_pubsub.publish_market_event(str(market.id), "liquidity:remove", {
                "user_id": str(user.id),
                "lp_tokens": float(lp_tokens),
                "yes_redeemed": float(yes_redeemed),
                "no_redeemed": float(no_redeemed),
                "pool_lp_token_supply": float(pool.lp_token_supply),
            })
        except Exception:
            pass

        return {
            "yes_redeemed": str(yes_redeemed),
            "no_redeemed": str(no_redeemed),
            "total_redeemed": str(total_redeemed),
            "wallet_balance": str(wallet.balance),
        }

    @staticmethod
    async def distribute_protocol_fees(db: AsyncSession) -> dict:
        """Withdraw all accumulated protocol fees to the treasury and reset pool.protocol_fees to 0.
        Idempotent: if already distributed (pools have protocol_fees=0), returns empty.
        """
        result = await db.execute(
            select(LiquidityPool, Market).join(Market, LiquidityPool.market_id == Market.id)
            .where(LiquidityPool.protocol_fees > 0)
            .with_for_update()
        )
        pools = result.all()
        if not pools:
            return {"markets": [], "total_distributed": "0.0"}

        # Get or create system treasury user with row lock to prevent concurrent creation
        treasury_result = await db.execute(
            select(User).where(User.is_system.is_(True)).with_for_update().limit(1)
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
                balance=Decimal(0),
                locked_balance=Decimal(0),
                currency="USDC",
            )
            db.add(treasury_wallet)
        else:
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

        distributed = []
        total = Decimal(0)
        for pool, market in pools:
            if float(pool.protocol_fees) <= 0:
                continue
            amount = pool.protocol_fees
            treasury_wallet.balance += amount
            pool.protocol_fees = Decimal(0)
            total += amount
            distributed.append({
                "market_id": str(market.id),
                "market_slug": market.slug,
                "amount": amount,
            })
            tx = Transaction(
                user_id=treasury_user.id,
                wallet_id=treasury_wallet.id,
                type="protocol_fee",
                amount=amount,
                balance_after=treasury_wallet.balance,
                reference_id=str(market.id),
                reference_type="protocol_fee",
                status="completed",
            )
            db.add(tx)
            logger.info(f"Distributed protocol fees: market={market.slug} amount={float(amount)}")

        await db.commit()
        return {"markets": distributed, "total_distributed": str(total)}
