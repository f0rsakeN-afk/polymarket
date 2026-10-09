import logging
import secrets
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import NotFoundError, ValidationError
from app.config import settings
from app.deps import hash_password
from app.models.liquidity import LiquidityPool, LPShare
from app.models.market import Market
from app.models.position import Position
from app.models.user import User
from app.models.wallet import Transaction, Wallet
from app.services.market_service import MarketService
from app.websocket.manager import redis_pubsub

logger = logging.getLogger("PredictX")


class LiquidityService:

    @staticmethod
    async def _resolve_liquidity_pool(
        db: AsyncSession,
        market: Market,
        outcome_name: str | None,
        lock: bool = False,
    ) -> LiquidityPool:
        """The pool an LP deposit/withdrawal applies to.

        A parimutuel market holds one pool per outcome, so liquidity has to name
        the outcome it is for - attributing it to an arbitrary pool would let one
        outcome's deposit back another's price. A binary market has exactly one
        pool and the argument is ignored.
        """
        from app.models.market import Outcome

        outcome_rows = list(
            (
                await db.execute(
                    select(Outcome)
                    .where(Outcome.market_id == market.id)
                    .order_by(Outcome.outcome_index)
                )
            ).scalars().all()
        )

        if not MarketService.is_parimutuel(outcome_rows):
            pool = await MarketService.load_binary_pool(db, market.id)
            if pool is None:
                raise ValidationError(
                    "Market has no liquidity pool", error_code="MARKET_NO_LIQUIDITY"
                )
            return pool

        if not outcome_name:
            names = ", ".join(o.name for o in outcome_rows)
            raise ValidationError(
                f"This market has {len(outcome_rows)} outcomes, so liquidity must "
                f"name one. Available outcomes: {names}.",
                error_code="OUTCOME_REQUIRED",
            )

        match = next(
            (o for o in outcome_rows if o.name.lower() == outcome_name.lower()), None
        )
        if match is None:
            raise ValidationError(f"Invalid outcome '{outcome_name}'")

        stmt = select(LiquidityPool).where(
            LiquidityPool.market_id == market.id,
            LiquidityPool.outcome_id == match.id,
        )
        if lock:
            stmt = stmt.with_for_update()
        pool = (await db.execute(stmt)).scalar_one_or_none()
        if pool is None:
            raise ValidationError(
                f"Market has no liquidity pool for outcome '{match.name}'",
                error_code="MARKET_NO_LIQUIDITY",
            )
        return pool

    @staticmethod
    async def add_liquidity(
        db: AsyncSession,
        user: User,
        market_id: str,
        amount: Decimal,
        slippage_tolerance: Decimal = Decimal("0.05"),  # 5% default slippage tolerance
        outcome_name: str | None = None,
    ) -> dict:
        market_result = await db.execute(
            select(Market).where(Market.id == market_id).with_for_update()
        )
        market = market_result.scalar_one_or_none()
        if not market:
            raise NotFoundError("Market not found")
        if market.status != "active":
            raise ValidationError("Market is not active for liquidity provision")

        pool = await LiquidityService._resolve_liquidity_pool(
            db, market, outcome_name, lock=True
        )

        wallet_result = await db.execute(
            select(Wallet).where(Wallet.user_id == user.id).with_for_update()
        )
        wallet = wallet_result.scalar_one_or_none()
        if not wallet:
            raise ValidationError("Wallet not found")

        available = wallet.balance - wallet.locked_balance
        if amount > available:
            raise ValidationError(
                f"Insufficient balance: available={available}, requested={amount}",
                details={"available": str(available), "requested": str(amount)},
            )

        # Capture pre-operation prices to detect adverse price movement.
        # Share counts are Decimal, so prices stay Decimal • never mix float in.
        pre_total = pool.yes_shares + pool.no_shares
        pre_yes_price = pool.yes_shares / pre_total if pre_total > 0 else Decimal("0.5")
        pre_no_price = pool.no_shares / pre_total if pre_total > 0 else Decimal("0.5")

        # Token value is denominated in ESCROW, not reserves.
        #
        # Both ways an LP token turns back into dollars are collateral-
        # denominated, and always were:
        #
        #   remove_liquidity : pool.collateral * (lp_tokens / lp_token_supply)
        #   settlement      : pool.collateral / lp_token_supply  (tasks.py)
        #
        # Minting here against `yes_shares + no_shares` therefore made entry and
        # exit disagree the moment the two denominators diverged - and they
        # diverge on the very first trade, because the AMM mints new shares to
        # every buyer while fees raise the escrow. Concretely: on a 100 USDC pool
        # after a 40 USDC YES buy, reserves summed to 157.44 while the escrow held
        # 140, so a new 10 USDC LP was minted 12.70 tokens and could immediately
        # redeem only 8.96 - a ~10% loss on entry, before any trading, for doing
        # nothing and taking no risk.
        #
        # Pricing the mint off the escrow makes entry and exit exactly symmetric.
        # With supply s, escrow c and deposit X:
        #
        #     minted = X*s/c  ->  fraction = X/(c+X)  ->  payout = (c+X)*X/(c+X) = X
        #
        # so a joiner receives exactly what they put in, and the ratio between
        # supply and escrow is the sole thing that carries value. Fees still reach
        # LPs: trading raises `collateral` while `lp_token_supply` is untouched,
        # so each token's claim on the escrow grows.
        if pool.lp_token_supply > 0:
            escrow = pool.collateral or Decimal(0)
            if escrow <= 0:
                # Tokens are outstanding but the escrow is empty - the pool has
                # already been drained. There is no per-token value left to mint
                # against, and dividing here would raise ZeroDivisionError rather
                # than explain the problem.
                raise ValidationError(
                    "This market's liquidity pool holds no collateral, so new "
                    "liquidity cannot be priced. Outstanding LP tokens have "
                    "already been settled.",
                    error_code="POOL_ESCROW_EMPTY",
                )
            lp_tokens_minted = (amount * pool.lp_token_supply) / escrow
        else:
            # Bootstrap: no reference price exists, so set one. 2x matches what
            # market creation seeds (`lp_token_supply = amount * 2` against an
            # escrow of `amount`), keeping the initial ratio consistent with the
            # branch above.
            lp_tokens_minted = amount * Decimal(2)

        collateral_each = amount / Decimal(2)
        pool.yes_shares += collateral_each
        pool.no_shares += collateral_each
        pool.credit_collateral(amount)

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

        # Validate slippage: check if prices moved adversely beyond tolerance.
        post_total = pool.yes_shares + pool.no_shares
        post_yes_price = pool.yes_shares / post_total if post_total > 0 else Decimal("0.5")
        post_no_price = pool.no_shares / post_total if post_total > 0 else Decimal("0.5")
        max_price_change = max(abs(post_yes_price - pre_yes_price), abs(post_no_price - pre_no_price))
        if max_price_change > slippage_tolerance:
            await db.rollback()
            raise ValidationError(
                f"Adverse price movement detected: {max_price_change:.2%} exceeds slippage tolerance of {float(slippage_tolerance):.2%}. "
                "Please try again when prices are more stable."
            )

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

        # Publish WS events • liquidity changes affect AMM prices
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
        slippage_tolerance: Decimal = Decimal("0.05"),  # 5% default slippage tolerance
        outcome_name: str | None = None,
    ) -> dict:
        market = await db.get(Market, market_id)
        if not market:
            raise NotFoundError("Market not found")

        if market.status != "active":
            raise ValidationError("Market is not active for liquidity removal")

        pool = await LiquidityService._resolve_liquidity_pool(
            db, market, outcome_name, lock=True
        )

        # Standardize lock order: Market → Pool → Wallet → LPShare
        wallet_result = await db.execute(
            select(Wallet).where(Wallet.user_id == user.id).with_for_update()
        )
        wallet = wallet_result.scalar_one_or_none()
        if not wallet:
            raise ValidationError("Wallet not found")

        lp_result = await db.execute(
            select(LPShare).where(LPShare.pool_id == pool.id, LPShare.user_id == user.id).with_for_update()
        )
        lp_share = lp_result.scalar_one_or_none()
        if not lp_share or lp_share.lp_tokens < lp_tokens:
            raise ValidationError("Insufficient LP tokens", error_code="INSUFFICIENT_LP_TOKENS")

        if pool.lp_token_supply == 0:
            raise ValidationError("No LP tokens outstanding")

        # Capture pre-operation prices for slippage detection.
        pre_total = pool.yes_shares + pool.no_shares
        pre_yes_price = pool.yes_shares / pre_total if pre_total > 0 else Decimal("0.5")
        pre_no_price = pool.no_shares / pre_total if pre_total > 0 else Decimal("0.5")

        lp_fraction = lp_tokens / pool.lp_token_supply
        yes_redeemed = pool.yes_shares * lp_fraction
        no_redeemed = pool.no_shares * lp_fraction
        # Payout is the LP's pro-rata slice of the *escrow*, paid in USDC.
        # The old formula paid `yes_redeemed + no_redeemed`, which valued both
        # reserve sides at $1 each: after trading skewed the ratio it could
        # demand more dollars than the pool actually held (e.g. reserves
        # 184/30 against 200 collateral would pay out 214). Collateral is the
        # hard bound on what the pool can hand out. For a freshly-seeded
        # 50/50 pool (reserves sum == collateral) the two are identical.
        total_redeemed = pool.collateral * lp_fraction

        # ── Escrow floor (circuit breaker) ──
        # An LP exit takes real dollars out of the escrow, and settlement pays
        # winners → protocol fees → LPs, in that order. At resolution exactly
        # ONE side is paid $1 per share, so what must stay behind is the
        # larger of the two sides' open positions, plus fees still owed.
        # Without this cap an LP could withdraw the whole pool while traders
        # still hold shares, and settlement would have to short-change them
        # (or fail outright). The claims are read from position rows, which
        # are the authoritative source • pool reserves are AMM pricing state.
        claim_rows = await db.execute(
            select(Position.outcome_id, func.sum(Position.shares_held))
            .where(Position.market_id == market.id, Position.settled_at.is_(None))
            .group_by(Position.outcome_id)
        )
        worst_case_shares = max(
            (total or Decimal(0) for _outcome_id, total in claim_rows.all()),
            default=Decimal(0),
        )
        floor = worst_case_shares + pool.protocol_fees
        withdrawable = max(Decimal(0), pool.collateral - floor)
        if total_redeemed > withdrawable:
            raise ValidationError(
                f"Withdrawal refused: {total_redeemed:.4f} USDC would drop the escrow to "
                f"{pool.collateral - total_redeemed:.4f} while {worst_case_shares:.4f} shares of open "
                f"positions (worst case) and {pool.protocol_fees:.4f} of protocol fees still have to be "
                f"paid from it. Withdrawable right now: {withdrawable:.4f} USDC.",
                error_code="ESCROW_FLOOR",
            )

        pool.yes_shares -= yes_redeemed
        pool.no_shares -= no_redeemed
        market.total_liquidity = max(Decimal(0), (market.total_liquidity or Decimal(0)) - total_redeemed)
        pool.lp_token_supply -= lp_tokens

        lp_share.lp_tokens -= lp_tokens
        lp_share.collateral_deposited = max(
            Decimal(0), lp_share.collateral_deposited - total_redeemed
        )
        # Escrow out • strictly bounded by what the pool holds; `fraction <= 1`
        # makes a shortfall impossible unless the ledger is already broken.
        pool.debit_collateral(total_redeemed)
        wallet.balance += total_redeemed

        # Validate slippage: check if prices moved adversely beyond tolerance.
        post_total = pool.yes_shares + pool.no_shares
        post_yes_price = pool.yes_shares / post_total if post_total > 0 else Decimal("0.5")
        post_no_price = pool.no_shares / post_total if post_total > 0 else Decimal("0.5")
        max_price_change = max(abs(post_yes_price - pre_yes_price), abs(post_no_price - pre_no_price))
        if max_price_change > slippage_tolerance:
            await db.rollback()
            raise ValidationError(
                f"Adverse price movement detected: {max_price_change:.2%} exceeds slippage tolerance of {float(slippage_tolerance):.2%}. "
                "Please try again when prices are more stable."
            )

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

        # Publish WS events • liquidity changes affect AMM prices
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

        # Get or create system treasury user with row lock to prevent concurrent creation.
        # System users use a cryptographically random password_hash derived from
        # the application's JWT secret • they cannot be used for human authentication.
        treasury_result = await db.execute(
            select(User).where(User.is_system.is_(True)).with_for_update().limit(1)
        )
        treasury_user = treasury_result.scalar_one_or_none()
        if not treasury_user:
            # Generate a non-guessable hash using the application's JWT secret as entropy.
            # This ensures the system account cannot be brute-forced via login.
            system_secret = settings.jwt_secret + str(secrets.token_hex(32))
            treasury_user = User(
                email="treasury@system",
                username="treasury",
                password_hash=hash_password(system_secret),
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
            # FLUSH: without it `treasury_wallet.id` is still None, so the
            # Transaction below hits the NOT NULL constraint on wallet_id and
            # the entire sweep dies. Reachable on any deploy where fees accrue
            # before the first settlement has created the treasury account •
            # i.e. the 3:30am sweep failing on day one.
            await db.flush()
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
            if pool.protocol_fees <= 0:
                continue
            owed = Decimal(str(pool.protocol_fees))
            # The sweep is paid out of the pool's escrow: protocol_fees is a
            # sub-ledger *inside* pool.collateral, not extra money. A shortfall
            # means recorded fees exceed backing collateral • an invariant
            # violation. Pay what the escrow actually holds and keep the rest
            # recorded, so the next sweep retries it; never zero the record
            # while handing the treasury less than it claims.
            available = Decimal(str(pool.collateral or 0))
            amount = min(owed, available)
            if amount < owed:
                logger.error(
                    f"Protocol fee sweep shortfall: market={market.slug} "
                    f"owed={float(owed)} paid={float(amount)} "
                    f"carried_forward={float(owed - amount)}"
                )
            pool.protocol_fees = owed - amount
            if amount <= 0:
                continue
            pool.debit_collateral(amount)
            treasury_wallet.balance += amount
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
