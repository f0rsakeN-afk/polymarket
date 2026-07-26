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
from app.models.comment import Comment
from app.models.faq import MarketFAQ
from app.models.liquidity import LiquidityPool
from app.models.market import Market, Outcome
from app.models.order import Order
from app.models.position import Position
from app.models.trade import Trade
from app.models.user import User
from app.models.wallet import Wallet

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


async def seed():
    async with async_session_maker() as db:
        print("Seeding database...")

        # Create test users with wallets (skip if exists)
        print("Creating users...")
        users = []
        for user_data in TEST_USERS:
            result = await db.execute(
                text(f"SELECT id FROM users WHERE email = '{user_data['email']}' LIMIT 1")
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
                    password_hash="hashed_password_here",
                    is_verified=True,
                )
                db.add(user)
                users.append(user)

        await db.flush()

        # Create wallets with balances (skip if exists)
        print("Creating wallets...")
        for user in users:
            result = await db.execute(
                text(f"SELECT id FROM wallets WHERE user_id = '{user.id}' LIMIT 1")
            )
            if not result.fetchone():
                wallet = Wallet(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    balance=Decimal(str(randint(5000, 100000))),
                    locked_balance=Decimal(0),
                    currency="USDC",
                )
                db.add(wallet)

        await db.flush()

        # Create markets (skip if exists)
        print("Creating markets...")
        markets = []
        now = datetime.now(UTC)

        for market_data in MARKETS_DATA:
            result = await db.execute(
                text(f"SELECT id FROM markets WHERE slug = '{market_data['slug']}' LIMIT 1")
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
                description=market_data.get("description"),
                category=market_data["category"],
                subcategory=market_data.get("subcategory"),
                status="active",
                opens_at=opens_at,
                closes_at=closes_at,
                total_volume=Decimal(str(market_data["volume"])),
                total_liquidity=Decimal(str(market_data["liquidity"])),
                num_trades=randint(100, 5000),
            )
            db.add(market)
            markets.append(market)

            await db.flush()

            # Create outcomes (skip if exists)
            result = await db.execute(
                text(f"SELECT id FROM outcomes WHERE market_id = '{market.id}' LIMIT 1")
            )
            if result.fetchone():
                continue

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

            # Create liquidity pool (skip if exists)
            result = await db.execute(
                text(f"SELECT id FROM liquidity_pools WHERE market_id = '{market.id}' LIMIT 1")
            )
            if result.fetchone():
                continue

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
            )
            db.add(pool)

            # Create FAQs (skip if exists)
            result = await db.execute(
                text(f"SELECT id FROM market_faqs WHERE market_id = '{market.id}' LIMIT 1")
            )
            if not result.fetchone():
                faq_templates = [
                    {"question": "What does this market resolve to?", "answer": "This market will resolve based on the outcome of the event described in the question."},
                    {"question": "How is the winner determined?", "answer": "The market resolves based on credible public sources."},
                    {"question": "What happens if the question is ambiguous?", "answer": "The market resolver makes a final decision using reasonable interpretation."},
                ]
                for idx, faq_data in enumerate(faq_templates):
                    faq = MarketFAQ(
                        id=uuid.uuid4(),
                        market_id=market.id,
                        question=faq_data["question"],
                        answer=faq_data["answer"],
                        display_order=idx,
                    )
                    db.add(faq)

        await db.flush()

        # Create trades (skip if exists)
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

        # Create comments (skip if exists)
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
                    created_at=now - timedelta(hours=randint(0, 500)),
                )
                db.add(comment)
                comment_count += 1

        # Create positions (skip if exists)
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

        await db.commit()
        print("Seeding complete!")
        print(f"  - {len(users)} users")
        print(f"  - {len(markets)} markets")
        print(f"  - {trade_count} trades")
        print(f"  - {comment_count} comments")
        print(f"  - {position_count} positions")

        # Create pending orders for orderbook depth
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
                    order_type="limit",
                    amount=Decimal(str(uniform(50, 500))),
                    price=price,
                    remaining_amount=Decimal(str(uniform(50, 500))),
                    status="pending",
                    client_order_id=str(uuid.uuid4()),
                    created_at=now - timedelta(hours=randint(0, 48)),
                )
                db.add(order)
                order_count += 1

        await db.flush()
        await db.commit()
        print(f"  - {order_count} pending orders")


if __name__ == "__main__":
    asyncio.run(seed())
