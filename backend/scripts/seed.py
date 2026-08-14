"""
Seed script for Polymarket.
Run with: python -m scripts.seed
"""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from random import choice, randint, uniform

from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from app.database import _get_async_session_maker
from app.deps import hash_password
from app.models.alert import Alert
from app.models.comment import Comment
from app.models.dispute import Dispute
from app.models.faq import MarketFAQ
from app.models.flag import MarketFlag
from app.models.liquidity import LiquidityPool, LPShare
from app.models.market import Market, Outcome
from app.models.notification import Notification, NotificationPreference
from app.models.order import Order
from app.models.position import Position
from app.models.price_history import PriceHistory
from app.models.referral import Referral
from app.models.trade import Trade
from app.models.treasury import Treasury, TreasuryLog
from app.models.user import RefreshToken, Session, User
from app.models.wallet import Transaction, Wallet

# Test users
TEST_USERS = [
    {"email": "alice@test.com", "username": "alice_trades"},
    {"email": "bob@test.com", "username": "bob_predicts"},
    {"email": "carol@test.com", "username": "carol_markets"},
    {"email": "david@test.com", "username": "david_hodl"},
    {"email": "eve@test.com", "username": "eve_speculator"},
    {"email": "frank@test.com", "username": "frank_trader"},
    {"email": "grace@test.com", "username": "grace_winner"},
    {"email": "henry@test.com", "username": "henry_analyst"},
    {"email": "iris@test.com", "username": "iris_trader"},
    {"email": "jack@test.com", "username": "jack_degen"},
]

TEST_PASSWORD = "testpass123"

MARKETS_DATA = [
    # Politics
    {"slug": "trump-2024-wins", "question": "Will Donald Trump win the 2024 US Presidential Election?", "category": "Politics", "subcategory": "US Elections", "yes_price": 0.52, "volume": 2500000, "liquidity": 500000, "closing_days": 120},
    {"slug": "biden-approval-45", "question": "Will Biden's approval rating exceed 45% in Q4 2024?", "category": "Politics", "subcategory": "US Politics", "yes_price": 0.38, "volume": 850000, "liquidity": 180000, "closing_days": 60},
    {"slug": "uk-labour-majority", "question": "Will Labour win a majority in the 2024 UK General Election?", "category": "Politics", "subcategory": "UK Politics", "yes_price": 0.72, "volume": 1200000, "liquidity": 250000, "closing_days": 90},
    # Tech
    {"slug": "apple-vision-pro-500k", "question": "Will Apple Vision Pro sales exceed 500K units in 2024?", "category": "Tech", "subcategory": "Apple", "yes_price": 0.45, "volume": 680000, "liquidity": 150000, "closing_days": 180},
    {"slug": "openai-agi-2025", "question": "Will OpenAI achieve AGI by end of 2025?", "category": "Tech", "subcategory": "AI", "yes_price": 0.25, "volume": 3200000, "liquidity": 800000, "closing_days": 540},
    {"slug": "bitcoin-100k-2024", "question": "Will Bitcoin exceed $100,000 in 2024?", "category": "Tech", "subcategory": "Crypto", "yes_price": 0.62, "volume": 5600000, "liquidity": 1200000, "closing_days": 180},
    {"slug": "ethereum-etf-2024", "question": "Will Ethereum ETF be approved by SEC in 2024?", "category": "Tech", "subcategory": "Crypto", "yes_price": 0.55, "volume": 2100000, "liquidity": 480000, "closing_days": 120},
    # Sports
    {"slug": "nba-championship-2025", "question": "Which team will win the 2025 NBA Championship?", "category": "Sports", "subcategory": "Basketball", "yes_price": 0.30, "volume": 2100000, "liquidity": 450000, "closing_days": 400, "multi_outcome": True, "outcomes": ["Boston Celtics", "Los Angeles Lakers", "Denver Nuggets", "Golden State Warriors", "Miami Heat", "Other"]},
    {"slug": "euro-2024-winner", "question": "Which country will win Euro 2024?", "category": "Sports", "subcategory": "Soccer", "yes_price": 0.25, "volume": 3500000, "liquidity": 750000, "closing_days": 30, "multi_outcome": True, "outcomes": ["France", "England", "Germany", "Spain", "Portugal", "Italy", "Netherlands", "Other"]},
    {"slug": "olympics-2024-usa-top", "question": "Will USA top medal table at Paris 2024?", "category": "Sports", "subcategory": "Olympics", "yes_price": 0.75, "volume": 1100000, "liquidity": 240000, "closing_days": 60},
    # Science
    {"slug": "spacex-mars-2026", "question": "Will SpaceX land humans on Mars by 2026?", "category": "Science", "subcategory": "Space", "yes_price": 0.15, "volume": 2800000, "liquidity": 650000, "closing_days": 900},
    {"slug": "climate-2024-hottest", "question": "Will 2024 be the hottest year on record?", "category": "Science", "subcategory": "Climate", "yes_price": 0.82, "volume": 680000, "liquidity": 145000, "closing_days": 270},
    # Entertainment
    {"slug": "gta6-2024", "question": "Will GTA 6 be released in 2024?", "category": "Entertainment", "subcategory": "Gaming", "yes_price": 0.25, "volume": 2800000, "liquidity": 620000, "closing_days": 270},
    {"slug": "swift-tour-2b", "question": "Will Taylor Swift's Eras Tour exceed $2B revenue?", "category": "Entertainment", "subcategory": "Music", "yes_price": 0.88, "volume": 920000, "liquidity": 200000, "closing_days": 180},
    # Economics
    {"slug": "fed-rate-cut-3", "question": "Will Fed cut rates 3+ times in 2024?", "category": "Economics", "subcategory": "Monetary Policy", "yes_price": 0.48, "volume": 4200000, "liquidity": 950000, "closing_days": 270},
    {"slug": "us-recession-2024", "question": "Will US enter recession in 2024?", "category": "Economics", "subcategory": "US Economy", "yes_price": 0.35, "volume": 5100000, "liquidity": 1100000, "closing_days": 300},
    {"slug": "sp500-5000", "question": "Will S&P 500 exceed 5,000 by end of 2024?", "category": "Economics", "subcategory": "Stock Market", "yes_price": 0.68, "volume": 3500000, "liquidity": 780000, "closing_days": 270},
]

COMMENTS = [
    "Interesting market, what's the resolution criteria?",
    "I think this is underpriced given recent developments.",
    "Great opportunity here, the odds seem favorable.",
    "Does anyone have more info on how this will be resolved?",
    "This seems about right to me.",
    "I'm skeptical about this one.",
    "The volume is really picking up on this one.",
    "Liquidity looks good, easy to get in and out.",
    "Nice spread on this market.",
]

DISPUTE_EVIDENCE = [
    "Recent polls show the candidate leading by 5 points.",
    "Official election commission certified results.",
    "Multiple credible news sources report the outcome.",
    "Financial statements were released showing profitability.",
    "Official announcement from the organization confirms.",
]

FAQ_QUESTIONS = [
    ("What does this market resolve to?", "This market will resolve based on the outcome of the event described in the question."),
    ("How is the winner determined?", "The market resolves based on credible public sources."),
    ("What happens if the question is ambiguous?", "The market resolver makes a final decision using reasonable interpretation."),
    ("When can I withdraw my liquidity?", "You can withdraw anytime but limited during dispute windows."),
    ("What are the fees?", "There is a 2% fee on trades and 1% protocol fee on liquidity provider returns."),
]


async def seed():
    async_session = _get_async_session_maker()
    async with async_session() as db:
        print("Seeding database...")

        now = datetime.now(UTC)
        one_week_ago = now - timedelta(days=7)
        two_weeks_ago = now - timedelta(days=14)
        one_month_ago = now - timedelta(days=30)
        three_months_ago = now - timedelta(days=90)

        # Get or create test users with wallets
        print("Creating users...")
        users = []
        for user_data in TEST_USERS:
            result = await db.execute(select(User).where(User.email == user_data["email"]))
            user = result.scalar_one_or_none()
            if not user:
                user = User(
                    id=uuid.uuid4(),
                    email=user_data["email"],
                    username=user_data["username"],
                    password_hash=hash_password(TEST_PASSWORD),
                    is_email_verified=True,
                    is_active=True,
                )
                db.add(user)
                await db.flush()
            users.append(user)

        # Create wallets with balances
        print("Creating wallets...")
        for user in users:
            result = await db.execute(select(Wallet).where(Wallet.user_id == user.id))
            wallet = result.scalar_one_or_none()
            if not wallet:
                wallet = Wallet(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    balance=Decimal(str(randint(5000, 100000))),
                    locked_balance=Decimal(str(randint(0, 5000))),
                    currency="USDC",
                )
                db.add(wallet)

        await db.flush()

        # Create notification preferences
        print("Creating notification preferences...")
        for user in users:
            result = await db.execute(select(NotificationPreference).where(NotificationPreference.user_id == user.id))
            pref = result.scalar_one_or_none()
            if not pref:
                pref = NotificationPreference(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    email_alerts=choice([True, False]),
                    email_order_fills=choice([True, False]),
                    email_market_resolution=choice([True, False]),
                    email_weekly_digest=choice([True, False]),
                    push_alerts=choice([True, False]),
                    push_order_fills=choice([True, False]),
                    push_market_resolution=choice([True, False]),
                )
                db.add(pref)

        await db.flush()

        # Get or create markets
        print("Creating markets...")
        markets = []
        for market_data in MARKETS_DATA:
            result = await db.execute(select(Market).where(Market.slug == market_data["slug"]))
            market = result.scalar_one_or_none()
            if not market:
                closes_at = now + timedelta(days=market_data["closing_days"])
                opens_at = now - timedelta(days=randint(1, 60))

                market = Market(
                    id=uuid.uuid4(),
                    slug=market_data["slug"],
                    question=market_data["question"],
                    description=f"Detailed analysis and tracking for: {market_data['question']}",
                    category=market_data["category"],
                    subcategory=market_data.get("subcategory"),
                    status="active",
                    resolution_criteria=f"This market resolves based on official public sources regarding {market_data['question']}.",
                    resolution_source=f"https://example.com/resolution/{market_data['slug']}",
                    opens_at=opens_at,
                    closes_at=closes_at,
                    total_volume=Decimal(str(market_data["volume"])),
                    total_liquidity=Decimal(str(market_data["liquidity"])),
                    num_trades=randint(100, 5000),
                )
                db.add(market)
                await db.flush()

                # Create outcomes
                if market_data.get("multi_outcome"):
                    for idx, outcome_name in enumerate(market_data["outcomes"]):
                        outcome = Outcome(
                            id=uuid.uuid4(),
                            market_id=market.id,
                            name=outcome_name,
                            outcome_index=idx,
                        )
                        db.add(outcome)
                else:
                    for idx, name in enumerate(["Yes", "No"]):
                        outcome = Outcome(
                            id=uuid.uuid4(),
                            market_id=market.id,
                            name=name,
                            outcome_index=idx,
                        )
                        db.add(outcome)

                await db.flush()

                # Create liquidity pool
                yes_price = market_data["yes_price"]
                no_price = 1 - yes_price
                total_liquidity = market_data["liquidity"]

                pool = LiquidityPool(
                    id=uuid.uuid4(),
                    market_id=market.id,
                    yes_shares=Decimal(str(total_liquidity * no_price)),
                    no_shares=Decimal(str(total_liquidity * yes_price)),
                    collateral=Decimal(str(total_liquidity)),
                    fee_rate=Decimal("0.02"),
                    lp_token_supply=Decimal(str(total_liquidity)),
                    protocol_fees=Decimal(str(round(total_liquidity * uniform(0.005, 0.02), 8))),
                )
                db.add(pool)
                await db.flush()

                # Create LP shares for this pool
                for user in users[:5]:
                    lp_share = LPShare(
                        id=uuid.uuid4(),
                        pool_id=pool.id,
                        user_id=user.id,
                        lp_tokens=Decimal(str(uniform(100, 10000))),
                        collateral_deposited=Decimal(str(uniform(50, 5000))),
                    )
                    db.add(lp_share)

                # Create FAQs
                for idx, (question, answer) in enumerate(FAQ_QUESTIONS):
                    faq = MarketFAQ(
                        id=uuid.uuid4(),
                        market_id=market.id,
                        question=question,
                        answer=answer,
                        display_order=idx,
                    )
                    db.add(faq)

            markets.append(market)

        await db.flush()

        # Create LP shares for existing pools (that don't have LP shares yet)
        print("Creating LP shares...")
        for market in markets:
            result = await db.execute(select(LiquidityPool).where(LiquidityPool.market_id == market.id))
            pool = result.scalar_one_or_none()
            if pool:
                result = await db.execute(select(LPShare).where(LPShare.pool_id == pool.id))
                existing_shares = result.scalars().all()
                if len(existing_shares) < 5:
                    for user in users[:5]:
                        result = await db.execute(
                            select(LPShare).where(LPShare.pool_id == pool.id, LPShare.user_id == user.id)
                        )
                        existing = result.scalar_one_or_none()
                        if not existing:
                            lp_share = LPShare(
                                id=uuid.uuid4(),
                                pool_id=pool.id,
                                user_id=user.id,
                                lp_tokens=Decimal(str(uniform(100, 10000))),
                                collateral_deposited=Decimal(str(uniform(50, 5000))),
                            )
                            db.add(lp_share)

        await db.flush()

        # Create refresh tokens and sessions
        print("Creating auth tokens...")
        for user in users:
            result = await db.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))
            if not result.scalar_one_or_none():
                refresh_token = RefreshToken(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    token_hash=str(uuid.uuid4()),
                    expires_at=now + timedelta(days=30),
                    revoked=False,
                    device_info=f"Chrome on {choice(['Mac', 'Windows', 'Linux'])}",
                )
                db.add(refresh_token)
                await db.flush()

                session = Session(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    refresh_token_id=refresh_token.id,
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    ip_address=f"192.168.{randint(1, 255)}.{randint(1, 255)}",
                    created_at=two_weeks_ago,
                    last_active_at=now - timedelta(hours=randint(1, 24)),
                    expires_at=now + timedelta(days=7),
                )
                db.add(session)

        await db.flush()

        # Create referral records
        print("Creating referrals...")
        referrer = users[0]  # Alice is the main referrer
        for user in users[1:5]:
            result = await db.execute(
                select(Referral).where(Referral.referrer_id == referrer.id, Referral.referred_id == user.id)
            )
            if not result.scalar_one_or_none():
                referral = Referral(
                    id=uuid.uuid4(),
                    referrer_id=referrer.id,
                    referred_id=user.id,
                    referral_code=f"ALICE{str(uuid.uuid4())[:8].upper()}",
                    status=choice(["completed", "pending"]),
                    reward_amount=Decimal(str(uniform(0.5, 5.0))),
                    completed_at=choice([None, three_months_ago + timedelta(days=randint(1, 30))]),
                )
                db.add(referral)

        await db.flush()

        # Get active markets for disputes
        result = await db.execute(select(Market).where(Market.status == "active"))
        active_markets = list(result.scalars().all())

        # Create disputes
        print("Creating disputes...")
        for market in active_markets[:8]:
            user = choice(users)
            dispute = Dispute(
                id=uuid.uuid4(),
                market_id=market.id,
                user_id=user.id,
                evidence=choice(DISPUTE_EVIDENCE),
                evidence_url=f"https://example.com/evidence/{uuid.uuid4()}",
                status=choice(["open", "open", "resolved"]),
            )
            db.add(dispute)

        await db.flush()

        # Create market flags
        print("Creating market flags...")
        for market in markets[:5]:
            user = choice(users)
            result = await db.execute(
                select(MarketFlag).where(MarketFlag.market_id == market.id, MarketFlag.user_id == user.id)
            )
            if not result.scalar_one_or_none():
                flag = MarketFlag(
                    id=uuid.uuid4(),
                    market_id=market.id,
                    user_id=user.id,
                    reason=choice(["Misleading information", "Invalid resolution criteria", "Duplicate market"]),
                    status=choice(["open", "reviewed"]),
                )
                db.add(flag)

        await db.flush()

        # Create trades (skip if exists)
        print("Creating trades...")
        trade_count = 0
        for market in markets:
            # Get outcomes for this market
            result = await db.execute(select(Outcome).where(Outcome.market_id == market.id).order_by(Outcome.outcome_index))
            outcomes = list(result.scalars().all())
            if not outcomes:
                continue

            # Check if trades exist
            result = await db.execute(select(Trade).where(Trade.market_id == market.id).limit(1))
            if result.scalar_one_or_none():
                continue

            num_trades = randint(30, 150)
            for _ in range(num_trades):
                outcome = choice(outcomes)
                user = choice(users)
                trade = Trade(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    market_id=market.id,
                    outcome=outcome.name.lower(),
                    side=choice(["buy", "sell"]),
                    price=Decimal(str(uniform(0.05, 0.95))),
                    amount=Decimal(str(uniform(10, 1000))),
                    executed_at=now - timedelta(hours=randint(0, 720)),
                )
                db.add(trade)
                trade_count += 1

        await db.flush()

        # Create price history
        print("Creating price history...")
        for market in markets:
            result = await db.execute(select(Outcome).where(Outcome.market_id == market.id).order_by(Outcome.outcome_index))
            outcomes = list(result.scalars().all())

            for outcome in outcomes[:2]:  # Yes and No outcomes
                # Check if price history exists
                result = await db.execute(
                    select(PriceHistory).where(PriceHistory.outcome_id == outcome.id).limit(1)
                )
                if result.scalar_one_or_none():
                    continue

                for day in range(30):
                    snapshot = PriceHistory(
                        id=uuid.uuid4(),
                        market_id=market.id,
                        outcome_id=outcome.id,
                        price=Decimal(str(uniform(0.3, 0.7))),
                        total_volume=Decimal(str(randint(1000, 100000))),
                        snapshot_at=now - timedelta(days=day, hours=randint(0, 23)),
                    )
                    db.add(snapshot)

        await db.flush()

        # Create transactions
        print("Creating transactions...")
        tx_count = 0
        for user in users:
            result = await db.execute(select(Wallet).where(Wallet.user_id == user.id))
            wallet = result.scalar_one_or_none()
            if not wallet:
                continue

            wallet_balance = Decimal(0)

            for _ in range(randint(5, 20)):
                tx_type = choice(["deposit", "trade_buy", "trade_sell", "liquidity_add", "liquidity_remove", "settlement_win"])
                if tx_type == "deposit":
                    amount = Decimal(str(uniform(100, 10000)))
                    wallet_balance += amount
                else:
                    amount = Decimal(str(uniform(10, 5000)))
                    wallet_balance -= amount

                tx = Transaction(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    wallet_id=wallet.id,
                    type=tx_type,
                    amount=amount,
                    balance_after=wallet_balance,
                    reference_id=str(uuid.uuid4()),
                    reference_type=choice(["order", "liquidity_pool", "market_settlement"]),
                    status="completed",
                    extra_data={"memo": f"Random {tx_type} transaction"},
                )
                db.add(tx)
                tx_count += 1

            # Update wallet balance
            wallet.balance = wallet_balance

        await db.flush()

        # Create treasury and treasury logs
        print("Creating treasury...")
        result = await db.execute(select(Treasury).limit(1))
        treasury = result.scalar_one_or_none()
        if not treasury:
            treasury = Treasury(
                id=uuid.uuid4(),
                balance=Decimal("500000.00"),
                total_fees_collected=Decimal("25000.00"),
                total_fees_distributed=Decimal("5000.00"),
            )
            db.add(treasury)
            await db.flush()

            # Add treasury logs
            for _ in range(10):
                log = TreasuryLog(
                    id=uuid.uuid4(),
                    treasury_id=treasury.id,
                    event=choice(["fee_collected", "distribution"]),
                    amount=Decimal(str(uniform(100, 5000))),
                    reference_type=choice(["trade", "liquidity"]),
                    reference_id=str(uuid.uuid4()),
                )
                db.add(log)

        await db.flush()

        # Create notifications
        print("Creating notifications...")
        for user in users:
            for _ in range(randint(3, 15)):
                notification = Notification(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    type=choice(["order_fill", "market_resolution", "dispute_new", "price_alert"]),
                    title=f"Notification from {choice(['Polymarket', 'System', 'Market Resolver'])}",
                    body=f"This is a sample notification about {choice(['your order being filled', 'a market you follow', 'a new dispute', 'price movement'])}.",
                    data={"market_id": str(choice(markets).id) if markets else None},
                    read_at=choice([None, now - timedelta(days=randint(0, 7))]),
                    channel=choice(["in_app", "email"]),
                )
                db.add(notification)

        await db.flush()

        # Create alerts
        print("Creating alerts...")
        for user in users[:5]:
            for market in markets[:5]:
                result = await db.execute(
                    select(Alert).where(Alert.user_id == user.id, Alert.market_id == market.id).limit(1)
                )
                if result.scalar_one_or_none():
                    continue

                alert = Alert(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    market_id=market.id,
                    outcome=choice(["yes", "no", None]),
                    condition=choice(["above", "below"]),
                    trigger_price=Decimal(str(uniform(0.2, 0.8))),
                    triggered=choice([True, False]),
                    triggered_at=choice([None, now - timedelta(days=randint(1, 10))]),
                )
                db.add(alert)

        await db.flush()

        # Create comments
        print("Creating comments...")
        comment_count = 0
        for market in markets[:10]:
            # Check if comments exist
            result = await db.execute(select(Comment).where(Comment.market_id == market.id).limit(1))
            if result.scalar_one_or_none():
                continue

            num_comments = randint(3, 12)
            for _ in range(num_comments):
                user = choice(users)
                comment = Comment(
                    id=uuid.uuid4(),
                    market_id=market.id,
                    user_id=user.id,
                    content=choice(COMMENTS),
                    depth=0,
                    is_deleted=choice([False, False, False, True]),
                    created_at=now - timedelta(hours=randint(0, 500)),
                )
                db.add(comment)
                comment_count += 1

                # Add replies to some comments
                if uniform(0, 1) < 0.3:
                    reply = Comment(
                        id=uuid.uuid4(),
                        market_id=market.id,
                        user_id=choice(users).id,
                        parent_id=comment.id,
                        content=f"Reply to: {comment.content[:30]}...",
                        depth=1,
                        created_at=comment.created_at + timedelta(hours=randint(1, 12)),
                    )
                    db.add(reply)
                    comment_count += 1

        await db.flush()

        # Create positions
        print("Creating positions...")
        position_count = 0
        for market in markets[:8]:
            # Get outcomes
            result = await db.execute(select(Outcome).where(Outcome.market_id == market.id).order_by(Outcome.outcome_index))
            outcomes = list(result.scalars().all())
            if not outcomes:
                continue

            # Check if positions exist
            result = await db.execute(select(Position).where(Position.market_id == market.id).limit(1))
            if result.scalar_one_or_none():
                continue

            for user in users[:4]:
                outcome = choice(outcomes)
                position = Position(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    market_id=market.id,
                    outcome_id=outcome.id,
                    shares_held=Decimal(str(uniform(50, 2000))),
                    average_price=Decimal(str(uniform(0.1, 0.9))),
                    realized_pnl=Decimal(str(uniform(-500, 2000))),
                )
                db.add(position)
                position_count += 1

        await db.flush()

        # Create pending orders
        print("Creating pending orders...")
        order_count = 0
        for market in markets:
            # Get outcomes
            result = await db.execute(select(Outcome).where(Outcome.market_id == market.id).order_by(Outcome.outcome_index))
            outcomes = list(result.scalars().all())
            if not outcomes:
                continue

            # Check if pending orders exist
            result = await db.execute(
                select(Order).where(Order.market_id == market.id, Order.status == "pending").limit(1)
            )
            if result.scalar_one_or_none():
                continue

            for user in users[:3]:
                outcome = choice(outcomes)
                order = Order(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    market_id=market.id,
                    outcome_id=outcome.id,
                    side=choice(["buy", "sell"]),
                    order_type=choice(["limit", "fill_or_kill"]),
                    amount=Decimal(str(uniform(50, 500))),
                    price=Decimal(str(uniform(0.05, 0.95))),
                    remaining_amount=Decimal(str(uniform(50, 500))),
                    status="pending",
                    client_order_id=str(uuid.uuid4()),
                    created_at=now - timedelta(hours=randint(0, 48)),
                )
                db.add(order)
                order_count += 1

        await db.commit()

        # Get counts from database
        print("\n=== Seeding Complete! ===")
        tables = [
            ("Users", "users"),
            ("Wallets", "wallets"),
            ("Markets", "markets"),
            ("Outcomes", "outcomes"),
            ("Liquidity Pools", "liquidity_pools"),
            ("LP Shares", "lp_shares"),
            ("Orders (pending)", "orders"),
            ("Positions", "positions"),
            ("Trades", "trades"),
            ("Comments", "comments"),
            ("Disputes", "disputes"),
            ("Alerts", "alerts"),
            ("Notifications", "notifications"),
            ("Referrals", "referrals"),
            ("Transactions", "transactions"),
            ("Market Flags", "market_flags"),
            ("Treasury", "treasury"),
            ("Treasury Logs", "treasury_logs"),
            ("Refresh Tokens", "refresh_tokens"),
            ("Sessions", "sessions"),
        ]

        for name, table in tables:
            result = await db.execute(text(f"SELECT COUNT(*) FROM {table}"))
            count = result.scalar()
            print(f"  {name}: {count}")


if __name__ == "__main__":
    asyncio.run(seed())
