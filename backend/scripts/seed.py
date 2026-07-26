"""
Seed script for Polymarket.
Run with: python -m scripts.seed
"""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from random import choice, randint, uniform

from sqlalchemy import text

from app.database import async_session_maker
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
from app.models.user import RefreshToken, Session, User
from app.models.wallet import Transaction, Wallet
from app.models.treasury import Treasury, TreasuryLog
from app.models.alert import Alert

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
    async with async_session_maker() as db:
        print("Seeding database...")

        now = datetime.now(UTC)
        one_week_ago = now - timedelta(days=7)
        two_weeks_ago = now - timedelta(days=14)
        one_month_ago = now - timedelta(days=30)
        three_months_ago = now - timedelta(days=90)

        # Create test users with wallets (skip if exists)
        print("Creating users...")
        users = []
        for user_data in TEST_USERS:
            result = await db.execute(
                text("SELECT id FROM users WHERE email = :email LIMIT 1"),
                {"email": user_data["email"]},
            )
            existing = result.fetchone()
            if existing:
                user = User(id=existing[0])
                users.append(user)
            else:
                user = User(
                    id=uuid.uuid4(),
                    email=user_data["email"],
                    username=user_data["username"],
                    password_hash=hash_password(TEST_PASSWORD),
                    is_verified=True,
                    is_active=True,
                )
                db.add(user)
                users.append(user)

        await db.flush()

        # Create wallets with balances
        print("Creating wallets...")
        wallets = []
        for user in users:
            result = await db.execute(
                text("SELECT id FROM wallets WHERE user_id = :user_id LIMIT 1"),
                {"user_id": str(user.id)},
            )
            existing = result.fetchone()
            if existing:
                wallets.append(Wallet(id=existing[0], user_id=user.id))
            else:
                wallet = Wallet(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    balance=Decimal(str(randint(5000, 100000))),
                    locked_balance=Decimal(str(randint(0, 5000))),
                    currency="USDC",
                )
                db.add(wallet)
                wallets.append(wallet)

        await db.flush()

        # Create notification preferences
        print("Creating notification preferences...")
        for user in users:
            result = await db.execute(
                text("SELECT id FROM notification_preferences WHERE user_id = :user_id LIMIT 1"),
                {"user_id": str(user.id)},
            )
            if not result.fetchone():
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

        # Create markets (skip if exists)
        print("Creating markets...")
        markets = []
        for market_data in MARKETS_DATA:
            result = await db.execute(
                text("SELECT id FROM markets WHERE slug = :slug LIMIT 1"),
                {"slug": market_data["slug"]},
            )
            existing = result.fetchone()
            if existing:
                market = Market(id=existing[0])
                markets.append(market)
                continue

            closes_at = now + timedelta(days=market_data["closing_days"])
            opens_at = now - timedelta(days=randint(1, 60))

            market = Market(
                id=uuid.uuid4(),
                slug=market_data["slug"],
                question=market_data["question"],
                description=f"Detailed analysis and tracking for: {market_data['question']}",
                category=market_data["category"],
                subcategory=market_data.get("subcategory"),
                status=choice(["active", "active", "active", "closed"]),
                resolution_criteria=f"This market resolves based on official public sources regarding {market_data['question']}.",
                resolution_source=f"https://example.com/resolution/{market_data['slug']}",
                opens_at=opens_at,
                closes_at=closes_at,
                total_volume=Decimal(str(market_data["volume"])),
                total_liquidity=Decimal(str(market_data["liquidity"])),
                num_trades=randint(100, 5000),
            )
            db.add(market)
            markets.append(market)

            await db.flush()

            # Create outcomes
            result = await db.execute(
                text("SELECT id FROM outcomes WHERE market_id = :market_id LIMIT 1"),
                {"market_id": str(market.id)},
            )
            if not result.fetchone():
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
                    yes_outcome = Outcome(
                        id=uuid.uuid4(),
                        market_id=market.id,
                        name="Yes",
                        outcome_index=0,
                    )
                    no_outcome = Outcome(
                        id=uuid.uuid4(),
                        market_id=market.id,
                        name="No",
                        outcome_index=1,
                    )
                    db.add(yes_outcome)
                    db.add(no_outcome)

            await db.flush()

            # Create liquidity pool
            result = await db.execute(
                text(f"SELECT id FROM liquidity_pools WHERE market_id = '{market.id}' LIMIT 1")
            )
            if not result.fetchone():
                yes_price = market_data["yes_price"]
                no_price = 1 - yes_price
                total_liquidity = market_data["liquidity"]

                yes_shares = total_liquidity * no_price
                no_shares = total_liquidity * yes_price

                pool = LiquidityPool(
                    id=uuid.uuid4(),
                    market_id=market.id,
                    yes_shares=Decimal(str(yes_shares)),
                    no_shares=Decimal(str(no_shares)),
                    collateral=Decimal(str(total_liquidity)),
                    fee_rate=Decimal("0.02"),
                    lp_token_supply=Decimal(str(total_liquidity)),
                    protocol_fees=Decimal(str(round(total_liquidity * uniform(0.005, 0.02), 8))),
                )
                db.add(pool)

                # Create LP shares for different users
                for i, user in enumerate(users[:5]):
                    lp_share = LPShare(
                        id=uuid.uuid4(),
                        pool_id=pool.id,
                        user_id=user.id,
                        lp_tokens=Decimal(str(uniform(100, 10000))),
                        collateral_deposited=Decimal(str(uniform(50, 5000))),
                    )
                    db.add(lp_share)

            await db.flush()

            # Create FAQs
            result = await db.execute(
                text(f"SELECT id FROM market_faqs WHERE market_id = '{market.id}' LIMIT 1")
            )
            if not result.fetchone():
                for idx, (question, answer) in enumerate(FAQ_QUESTIONS):
                    faq = MarketFAQ(
                        id=uuid.uuid4(),
                        market_id=market.id,
                        question=question,
                        answer=answer,
                        display_order=idx,
                    )
                    db.add(faq)

        await db.flush()

        # Create refresh tokens and sessions
        print("Creating auth tokens...")
        for user in users:
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
                text("SELECT id FROM referrals WHERE referrer_id = :referrer_id AND referred_id = :referred_id LIMIT 1"),
                {"referrer_id": str(referrer.id), "referred_id": str(user.id)},
            )
            if not result.fetchone():
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

        # Create disputes
        print("Creating disputes...")
        active_markets = [m for m in markets if m.status == "active"]
        for market in active_markets[:5]:
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
        for market in markets[:3]:
            user = choice(users)
            flag = MarketFlag(
                id=uuid.uuid4(),
                market_id=market.id,
                user_id=user.id,
                reason=choice(["Misleading information", "Invalid resolution criteria", "Duplicate market"]),
                status=choice(["open", "reviewed"]),
            )
            db.add(flag)

        await db.flush()

        # Create trades
        print("Creating trades...")
        trade_count = 0
        for market in markets:
            result = await db.execute(
                text(f"SELECT id FROM trades WHERE market_id = '{market.id}' LIMIT 1")
            )
            if result.fetchone():
                continue

            outcomes_result = await db.execute(
                text(f"SELECT * FROM outcomes WHERE market_id = '{market.id}' ORDER BY outcome_index")
            )
            outcomes = list(outcomes_result.fetchall())

            if not outcomes:
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
            outcomes_result = await db.execute(
                text(f"SELECT * FROM outcomes WHERE market_id = '{market.id}' ORDER BY outcome_index")
            )
            outcomes = list(outcomes_result.fetchall())

            for outcome in outcomes[:2]:  # Yes and No outcomes
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
        for wallet in wallets:
            wallet_balance = wallet.balance or Decimal(0)
            for _ in range(randint(5, 20)):
                tx_type = choice(["deposit", "trade_buy", "trade_sell", "liquidity_add", "liquidity_remove", "settlement_win"])
                if tx_type == "deposit":
                    amount = Decimal(str(uniform(100, 10000)))
                    balance_after = wallet_balance + amount
                else:
                    amount = Decimal(str(uniform(10, 5000)))
                    balance_after = wallet_balance - amount

                tx = Transaction(
                    id=uuid.uuid4(),
                    user_id=wallet.user_id,
                    wallet_id=wallet.id,
                    type=tx_type,
                    amount=amount,
                    balance_after=balance_after,
                    reference_id=str(uuid.uuid4()),
                    reference_type=choice(["order", "liquidity_pool", "market_settlement"]),
                    status="completed",
                    extra_data={"memo": f"Random {tx_type} transaction"},
                )
                db.add(tx)
                tx_count += 1

        await db.flush()

        # Create treasury and treasury logs
        print("Creating treasury...")
        result = await db.execute(text("SELECT id FROM treasury LIMIT 1"))
        if not result.fetchone():
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
                alert = Alert(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    market_id=market.id,
                    outcome=choice(["yes", "no", None]),
                    condition=choice(["above", "below"]),
                    trigger_price=Decimal(str(uniform(0.2, 0.8))),
                    triggered=choice([True, False]),
                    triggered_at=choice([None, (now - timedelta(days=randint(1, 10))).isoformat()]),
                )
                db.add(alert)

        await db.flush()

        # Create comments
        print("Creating comments...")
        comment_count = 0
        for market in markets[:10]:
            result = await db.execute(
                text(f"SELECT id FROM comments WHERE market_id = '{market.id}' LIMIT 1")
            )
            if result.fetchone():
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
            result = await db.execute(
                text(f"SELECT id FROM positions WHERE market_id = '{market.id}' LIMIT 1")
            )
            if result.fetchone():
                continue

            outcomes_result = await db.execute(
                text(f"SELECT * FROM outcomes WHERE market_id = '{market.id}' ORDER BY outcome_index")
            )
            outcomes = list(outcomes_result.fetchall())

            for user in users[:4]:
                if outcomes:
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

        # Create orders
        print("Creating pending orders...")
        order_count = 0
        for market in markets:
            result = await db.execute(
                text(f"SELECT id FROM orders WHERE market_id = '{market.id}' AND status = 'pending' LIMIT 1")
            )
            if result.fetchone():
                continue

            outcomes_result = await db.execute(
                text(f"SELECT * FROM outcomes WHERE market_id = '{market.id}' ORDER BY outcome_index")
            )
            outcomes = list(outcomes_result.fetchall())
            if not outcomes:
                continue

            for user in users[:3]:
                outcome = choice(outcomes)
                price = Decimal(str(uniform(0.05, 0.95)))
                order = Order(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    market_id=market.id,
                    outcome_id=outcome.id,
                    side=choice(["buy", "sell"]),
                    order_type=choice(["limit", "fill_or_kill"]),
                    amount=Decimal(str(uniform(50, 500))),
                    price=price,
                    remaining_amount=Decimal(str(uniform(50, 500))),
                    status="pending",
                    client_order_id=str(uuid.uuid4()),
                    created_at=now - timedelta(hours=randint(0, 48)),
                )
                db.add(order)
                order_count += 1

        await db.commit()

        # Count and print summary
        markets_count = len(markets)

        # Get counts from database
        trades_result = await db.execute(text("SELECT COUNT(*) FROM trades"))
        trades_count = trades_result.scalar()

        comments_result = await db.execute(text("SELECT COUNT(*) FROM comments"))
        comments_count = comments_result.scalar()

        positions_result = await db.execute(text("SELECT COUNT(*) FROM positions"))
        positions_count = positions_result.scalar()

        orders_result = await db.execute(text("SELECT COUNT(*) FROM orders WHERE status = 'pending'"))
        orders_count = orders_result.scalar()

        transactions_result = await db.execute(text("SELECT COUNT(*) FROM transactions"))
        transactions_count = transactions_result.scalar()

        disputes_result = await db.execute(text("SELECT COUNT(*) FROM disputes"))
        disputes_count = disputes_result.scalar()

        alerts_result = await db.execute(text("SELECT COUNT(*) FROM alerts"))
        alerts_count = alerts_result.scalar()

        notifications_result = await db.execute(text("SELECT COUNT(*) FROM notifications"))
        notifications_count = notifications_result.scalar()

        referrals_result = await db.execute(text("SELECT COUNT(*) FROM referrals"))
        referrals_count = referrals_result.scalar()

        print("\n=== Seeding Complete! ===")
        print(f"  Users: {len(users)}")
        print(f"  Markets: {markets_count}")
        print(f"  Trades: {trades_count}")
        print(f"  Comments: {comments_count}")
        print(f"  Positions: {positions_count}")
        print(f"  Pending Orders: {orders_count}")
        print(f"  Transactions: {transactions_count}")
        print(f"  Disputes: {disputes_count}")
        print(f"  Alerts: {alerts_count}")
        print(f"  Notifications: {notifications_count}")
        print(f"  Referrals: {referrals_count}")
        print(f"  LP Shares: {len(users) * 5}")  # 5 LP shares per user per pool
        print(f"  Referral Codes: {len(users) - 1}")


if __name__ == "__main__":
    asyncio.run(seed())
