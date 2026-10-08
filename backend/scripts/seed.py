"""
Seed script for PredictX.
Run with: python -m scripts.seed
"""
import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from random import choice, randint, uniform

from sqlalchemy import select, text

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
# ── Demo accounts ─────────────────────────────────────────────────────────────
# Exactly two accounts are meant to be logged into. Both are documented in the
# README so a reviewer can get in without reading this file.
#
#   admin@predictx.io  - admin: moderation, market approval, resolution
#   demo@predictx.io   - regular trader: portfolio, positions, wallet
#
# They share one password, overridable with SEED_PASSWORD.
TEST_PASSWORD = os.environ.get("SEED_PASSWORD", "testpass123")
DEMO_ADMIN_EMAIL = "admin@predictx.io"
DEMO_USER_EMAIL = "demo@predictx.io"

# ── Background cast ───────────────────────────────────────────────────────────
# Not login accounts. They exist so activity is not all attributed to one
# person: the trade feed, comment threads and leaderboards look fabricated if
# every row is the demo user. Same password, so they are usable, but the two
# above are the documented way in.
BACKGROUND_USERS = [
    "alice", "bob", "carol", "david", "eve", "frank",
    "grace", "henry", "iris", "jack", "kelly", "liam",
    "mia", "noah", "olivia", "peter", "quinn", "ruby",
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

# Chart history. One point per step, spanning roughly a month - wide enough that
# a market resolved up to 30 days ago still has its settlement inside the series.
HISTORY_POINTS = 48
HISTORY_STEP_MINUTES = 60 * 16

# Markets pre-resolved so the settlement and claim flow can be demonstrated.
# Winner must match an existing outcome name on that market.
RESOLVED_MARKETS = [
    {"slug": "trump-2024-wins", "winner": "Yes"},
    {"slug": "ethereum-etf-2024", "winner": "No"},
    {"slug": "swift-tour-2b", "winner": "Yes"},
    {"slug": "olympics-2024-usa-top", "winner": "No"},
    {"slug": "gta6-2024", "winner": "No"},
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
    "The resolution wording is ambiguous — does 'exceed' include exactly 100K?",
    "Taking a small position. Not a conviction bet, just sizing in.",
    "This price is way off from the consensus on the polling sites.",
    "Anyone else seeing the book thin on the bid side?",
    "Adding liquidity here, the spread widened after the last headline.",
    "I got filled at a much better price yesterday. Worth checking the history.",
    "Remind me to take profit if this clears 0.80.",
    "The dates on this are tight. Watch the close date.",
    "Good entry for anyone who missed the last move.",
    "Long term I think this resolves yes, short term the tape says no.",
    "The fees make this harder to trade than it looks.",
    "Checked the primary source, it's tracking well behind this price.",
    "Splitting my position across the top 3 outcomes instead of just one.",
    "Volume is dead here. Better liquidity on the neighbouring market.",
    "This is a coin flip and the price reflects that. Leaving it alone.",
    "Made my mistake earlier, averaging down now.",
]

DISPUTE_EVIDENCE = [
    "Recent polls show the candidate leading by 5 points.",
    "Official election commission certified results.",
    "Multiple credible news sources report the outcome.",
    "Financial statements were released showing profitability.",
    "Official announcement from the organization confirms.",
]

def _outcome_weights(n: int) -> list[float]:
    """Share weights for a parimutuel market's outcomes.

    Normalised to sum to 1, because price_i = shares_i / SUM(shares) and the
    outcome prices must total 1. Shaped like a plausible favourite/long-tail
    distribution - an even split makes every line overlap, and a purely random
    one produces a favourite below 0.2 which reads as noise.
    """
    raw = [1.0 / (i + 1) ** 1.4 for i in range(n)]
    total = sum(raw)
    return [r / total for r in raw]


def _planned_resolved_at(slug: str, now):
    """When a market in RESOLVED_MARKETS settles.

    Deterministic from the slug, and shared by the history generator and the
    resolver so the two cannot disagree: if they did, the series would either run
    past its own settlement or stop short of it.
    """
    return now - timedelta(days=(hash(slug) % 27) + 3, hours=6)


async def _finalise_history(db, market_id, outcome, resolved_at, settled: float = 1.0):
    """Push an outcome's price history to its settlement value.

    The last snapshot before resolution becomes exactly $1.00 for the winner and
    $0.00 for the losers. Without this, a resolved market's chart still ends on a
    mid-range price, so it disagrees with the $1-per-share payout shown next to
    it.
    """
    rows = list(
        (
            await db.execute(
                select(PriceHistory)
                .where(PriceHistory.outcome_id == outcome.id)
                .order_by(PriceHistory.snapshot_at.desc())
                .limit(1)
            )
        ).scalars().all()
    )
    if not rows:
        return
    last = rows[0]
    last.price = Decimal(str(settled))
    # Keep it inside the pre-resolution window so it is the tip of the series.
    last.snapshot_at = resolved_at - timedelta(hours=1)


async def _outcome_prices(db, market_id, outcomes) -> dict:
    """Current price per outcome id, keyed by outcome id.

    Reads the same pools the API prices from, so seeded trades and seeded chart
    history agree with what the application will actually show. Reusing the
    service would be better still, but the seed must not depend on app state that
    a schema change could invalidate - this mirrors the parimutuel rule: an
    outcome's price is its pool's share of the market total.

    Keys are `str(outcome.id)` everywhere, including for callers who hold a
    UUID. Mixing the two is not a type error, it is a silent miss: the
    parimutuel branch keyed by `str(pool.outcome_id)` while callers asked for
    `outcome.id`, so every parimutuel lookup returned the 0.5 default and the
    eight-way market's trades and chart all sat at an even split.
    """
    rows = list(
        (
            await db.execute(
                select(LiquidityPool).where(LiquidityPool.market_id == market_id)
            )
        ).scalars().all()
    )

    prices: dict = {}
    by_outcome = {str(p.outcome_id): p for p in rows if p.outcome_id is not None}
    total = sum((float(p.yes_shares) for p in rows), 0.0)

    if total > 0 and by_outcome:
        for outcome_id, pool in by_outcome.items():
            prices[outcome_id] = float(pool.yes_shares) / total
        return prices

    # Binary: one pool, so the denominator is that pool's own two reserves.
    #
    # It is NOT the market-wide total of yes_shares. Dividing the NO reserve by
    # yes_shares alone gives 744000/456000 = 1.63 - a price above 1, which then
    # fed the trade and history generators and put fills at 0.99 on a market
    # sitting at 0.38.
    pool = next((p for p in rows if p.outcome_id is None), None)
    if pool is None:
        return {str(o.id): 0.5 for o in outcomes}

    pool_total = float(pool.yes_shares) + float(pool.no_shares)
    for outcome in outcomes:
        if pool_total <= 0:
            prices[str(outcome.id)] = 0.5
            continue
        reserve = (
            float(pool.yes_shares)
            if outcome.name.lower() == "yes"
            else float(pool.no_shares)
        )
        prices[str(outcome.id)] = reserve / pool_total
    return prices


def _price_path(end_price: float, points: int, volatility: float = 0.06):
    """A price series for one outcome that ends exactly at `end_price`.

    Returns `points` prices ordered oldest → newest, so the last value equals
    `end_price`.

    Seeded prices used to be `uniform(0.3, 0.7)` per day: pure noise,
    uncorrelated with the market's actual price. So the chart's right-hand tip and
    the big price number beside it disagreed the moment the page loaded, which
    reads as a broken chart.

    Backwards random walk, then rescaled so the endpoint lands on the real price.
    A flat random walk's endpoint is arbitrary, so the final value is overwritten
    and the step before it nudged to keep the curve smooth.
    """
    if points <= 1:
        return [end_price]

    # Random walk, damped so it cannot wander far from where it started.
    path = [end_price]
    value = end_price
    for _ in range(points - 1):
        # Drift back toward the end price so the series converges on it, which
        # is what makes the shape read as a market finding its level.
        pull = (end_price - value) * 0.18
        value = value + pull + uniform(-volatility, volatility)
        value = min(max(value, 0.01), 0.99)
        path.append(value)

    path.reverse()  # oldest first
    path[-1] = end_price
    return path


def _trade_price(outcome_price: float) -> float:
    """A fill price near, but not exactly at, the market.

    Old behaviour drew `uniform(0.05, 0.95)` independently of the market, so the
    trade feed showed fills at 0.90 on a market priced 0.15. Average gap between a
    seeded trade and the market it belonged to was 0.29 - which anyone can spot by
    putting the feed next to the price.

    Now: small ticks around the mid, weighted toward it, clamped to a valid band
    and never below one tick (1 cent) so a fill price is always tradeable.
    """
    ticks = [0, 0, 0, -1, -1, 1, 1, -2, 2]
    price = outcome_price + 0.01 * choice(ticks) + uniform(-0.004, 0.004)
    return round(min(max(price, 0.01), 0.99), 4)


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
        two_weeks_ago = now - timedelta(days=14)
        three_months_ago = now - timedelta(days=90)

        # Get or create test users with wallets
        print("Creating users...")
        users = []
        # The demo admin first, so it leads the list everywhere the UI shows
        # "recent activity by user".
        all_users_spec = [
            {"email": DEMO_ADMIN_EMAIL, "username": "admin", "is_admin": True},
            {"email": DEMO_USER_EMAIL, "username": "demo", "is_admin": False},
            *(
                {
                    "email": f"{name}@predictx.io",
                    "username": name,
                    "is_admin": False,
                }
                for name in BACKGROUND_USERS
            ),
        ]
        for user_data in all_users_spec:
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
                    is_admin=user_data.get("is_admin", False),
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
                # Two independent randints could produce locked > balance, which
                # ck_wallets_locked_lte_balance correctly rejects - and it did,
                # intermittently, because both draws came from overlapping ranges.
                # Deriving locked from balance makes the invariant hold by
                # construction instead of by luck.
                balance = Decimal(str(randint(5000, 100000)))
                locked = balance * Decimal(str(round(uniform(0, 0.4), 4)))
                wallet = Wallet(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    balance=balance,
                    locked_balance=locked,
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
                #
                # `multi_outcome` here means "no YES/NO pair" - which covers a
                # two-way named market as well as an eight-way one. Decided by
                # shape, not by count, matching MarketService.is_parimutuel.
                outcome_names = (
                    list(market_data["outcomes"])
                    if market_data.get("multi_outcome")
                    else ["Yes", "No"]
                )
                outcome_rows = []
                for idx, name in enumerate(outcome_names):
                    outcome = Outcome(
                        id=uuid.uuid4(),
                        market_id=market.id,
                        name=name,
                        outcome_index=idx,
                    )
                    db.add(outcome)
                    outcome_rows.append(outcome)

                await db.flush()

                total_liquidity = Decimal(str(market_data["liquidity"]))

                if outcome_names == ["Yes", "No"]:
                    # Binary: one pool, yes/no reserves summing to total_liquidity.
                    #
                    # price(YES) = yes_shares / (yes_shares + no_shares), so the
                    # YES reserve must be seeded WITH `yes_price` of the
                    # collateral. Seeding the inverse made every binary market
                    # open at 1 - its declared price: "Bitcoin above $100K"
                    # declared 0.62 was showing 0.38.
                    yes_price = Decimal(str(market_data["yes_price"]))
                    pool = LiquidityPool(
                        id=uuid.uuid4(),
                        market_id=market.id,
                        outcome_id=None,
                        yes_shares=Decimal(str(total_liquidity * yes_price)),
                        no_shares=Decimal(str(total_liquidity * (1 - yes_price))),
                        collateral=total_liquidity,
                        fee_rate=Decimal("0.02"),
                        lp_token_supply=total_liquidity,
                        protocol_fees=Decimal(
                            str(
                                round(
                                    total_liquidity
                                    * Decimal(str(uniform(0.005, 0.02))),
                                    8,
                                )
                            )
                        ),
                    )
                    db.add(pool)
                    await db.flush()
                else:
                    # Parimutuel: one pool PER OUTCOME, no binary pool. Shares are
                    # distributed so price_i = shares_i / SUM(shares), i.e. the
                    # outcome prices sum to 1.
                    #
                    # The old seed wrote a single binary pool here with
                    # yes_price/no_price derived from the market-level price - so
                    # an eight-way market reported "Yes 75 / No 25", which are
                    # not any of its outcomes.
                    weights = _outcome_weights(len(outcome_rows))
                    for outcome, weight in zip(outcome_rows, weights):
                        shares = Decimal(str(total_liquidity * Decimal(str(weight))))
                        db.add(
                            LiquidityPool(
                                id=uuid.uuid4(),
                                market_id=market.id,
                                outcome_id=outcome.id,
                                yes_shares=shares,
                                no_shares=Decimal(0),
                                collateral=Decimal(str(total_liquidity / len(outcome_rows))),
                                fee_rate=Decimal("0.02"),
                                lp_token_supply=Decimal(str(total_liquidity / len(outcome_rows))),
                                protocol_fees=Decimal(
                                    str(
                                        round(
                                            (total_liquidity / len(outcome_rows))
                                            * Decimal(str(uniform(0.005, 0.02))),
                                            8,
                                        )
                                    )
                                ),
                            )
                        )
                    await db.flush()

                # Create LP shares, spread across whichever pools this market has.
                # A parimutuel market has one pool per outcome and no single
                # `pool` variable, so this must iterate the rows.
                market_pools = list(
                    (
                        await db.execute(
                            select(LiquidityPool).where(
                                LiquidityPool.market_id == market.id
                            )
                        )
                    ).scalars().all()
                )
                for target_pool in market_pools:
                    for user in users[:5]:
                        db.add(
                            LPShare(
                                id=uuid.uuid4(),
                                pool_id=target_pool.id,
                                user_id=user.id,
                                lp_tokens=Decimal(str(uniform(100, 10000))),
                                collateral_deposited=Decimal(str(uniform(50, 5000))),
                            )
                        )

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
            # Every pool for this market: a parimutuel market has one per
            # outcome and no binary pool, so `scalar_one_or_none()` would raise
            # MultipleResultsFound.
            result = await db.execute(
                select(LiquidityPool).where(LiquidityPool.market_id == market.id)
            )
            market_pools = result.scalars().all()
            for pool in market_pools:
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
        await db.commit()

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

            # Trades are priced against the outcome's REAL current price, so the
            # feed agrees with the market it belongs to.
            prices = await _outcome_prices(db, market.id, outcomes)

            num_trades = randint(60, 220)
            for _ in range(num_trades):
                outcome = choice(outcomes)
                user = choice(users)
                trade = Trade(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    market_id=market.id,
                    outcome=outcome.name.lower(),
                    side=choice(["buy", "sell"]),
                    price=Decimal(str(_trade_price(prices.get(str(outcome.id), 0.5)))),
                    amount=Decimal(str(uniform(10, 1000))),
                    executed_at=now - timedelta(hours=uniform(0, 720)),
                )
                db.add(trade)
                trade_count += 1

        await db.flush()

        # Create price history
        print("Creating price history...")
        for market in markets:
            result = await db.execute(select(Outcome).where(Outcome.market_id == market.id).order_by(Outcome.outcome_index))
            outcomes = list(result.scalars().all())
            if not outcomes:
                continue

            prices = await _outcome_prices(db, market.id, outcomes)

            # EVERY outcome, not outcomes[:2]. An eight-way market was getting a
            # chart for only its first two outcomes and blank lines for the other
            # six, which looked like the chart was broken rather than the data
            # being absent.
            # A resolved market's series must stop at its resolution date, so its
            # window is only as long as it traded for. An active one runs to now.
            #
            # Keyed off RESOLVED_MARKETS rather than `market.resolved_at`,
            # because resolution runs later in this script - at this point the
            # row is still `active` and has no resolved_at, so the check would
            # never fire and every series would run past its own settlement.
            planned = next(
                (r for r in RESOLVED_MARKETS if r["slug"] == market.slug), None
            )
            resolved_at = None
            if planned:
                # Deterministic, so a re-seed produces the same shape: 3-30 days
                # before now, matching the range the resolver draws from.
                resolved_at = _planned_resolved_at(market.slug, now)
                span = max((now - resolved_at).total_seconds() / 60, 60)
                points = max(int(span // HISTORY_STEP_MINUTES) + 1, 4)
            else:
                points = HISTORY_POINTS

            for outcome in outcomes:
                # Check if price history exists
                result = await db.execute(
                    select(PriceHistory).where(PriceHistory.outcome_id == outcome.id).limit(1)
                )
                if result.scalar_one_or_none():
                    continue

                end = prices.get(str(outcome.id), 0.5)
                series = _price_path(end, points=points)
                base_volume = Decimal(str(randint(1000, 100000)))

                # series is oldest-first; walk it backwards in time so the newest
                # snapshot is the live price.
                #
                # For a resolved market the newest snapshot is its resolution
                # date, not now: the series has to stop at settlement, or the
                # chart runs past it and its tip disagrees with the $1.00 payout
                # shown beside it.
                anchor = resolved_at if planned else now
                for idx, price in enumerate(reversed(series)):
                    snapshot = PriceHistory(
                        id=uuid.uuid4(),
                        market_id=market.id,
                        outcome_id=outcome.id,
                        price=Decimal(str(round(price, 6))),
                        total_volume=base_volume * Decimal(str(1 + (len(series) - idx) * 0.01)),
                        snapshot_at=anchor - timedelta(minutes=idx * HISTORY_STEP_MINUTES),
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

            # Start from the wallet's EXISTING balance, not zero. Starting at zero and
            # then assigning `wallet.balance = wallet_balance` overwrote the
            # seeded balance with just this loop's net delta, which could land
            # near zero while `locked_balance` kept its seeded value -
            # violating ck_wallets_locked_lte_balance.
            wallet_balance = Decimal(wallet.balance)

            for _ in range(randint(5, 20)):
                is_deposit = choice(
                    ["deposit", "trade_buy", "trade_sell", "liquidity_add", "liquidity_remove", "settlement_win"]
                ) == "deposit"
                # A debit can only be recorded against funds the wallet holds.
                # Picking one before any deposit drove the balance negative and
                # violated ck_wallets_balance_nonneg - the constraint was right to
                # reject it, so the generator is what needed fixing.
                if is_deposit or wallet_balance <= 0:
                    tx_type = "deposit"
                    amount = Decimal(str(uniform(100, 10000)))
                    wallet_balance += amount
                else:
                    tx_type = choice(
                        ["trade_buy", "trade_sell", "liquidity_add", "liquidity_remove", "settlement_win"]
                    )
                    amount = Decimal(str(uniform(10, 5000)))
                    # Clamp so the closing balance can never go negative.
                    amount = min(amount, wallet_balance)
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
            # Clamp the seeded escrow against the closing balance. Debits above
            # can take the balance below the locked figure, and
            # ck_wallets_locked_lte_balance rejects that.
            wallet.locked_balance = min(
                Decimal(wallet.locked_balance), wallet_balance
            )

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
                    title=f"Notification from {choice(['PredictX', 'System', 'Market Resolver'])}",
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
        # Every market, so no market page opens on an empty thread.
        for market in markets:
            # Check if comments exist
            result = await db.execute(select(Comment).where(Comment.market_id == market.id).limit(1))
            if result.scalar_one_or_none():
                continue

            num_comments = randint(4, 14)
            for _ in range(num_comments):
                user = choice(users)
                comment = Comment(
                    id=uuid.uuid4(),
                    market_id=market.id,
                    user_id=user.id,
                    content=choice(COMMENTS),
                    depth=0,
                    # One in ten, not one in four: moderation is still demonstrable but the thread
                    # does not read as half-destroyed.
                    is_deleted=choice([False] * 9 + [True]),
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
        # Every market and every trader, not markets[:8] × users[:4]. Half the
        # markets had no positions and 6 of 10 users had none, so the portfolio
        # page was nearly empty and the market page showed no holders.
        for market in markets:
            # Get outcomes
            result = await db.execute(select(Outcome).where(Outcome.market_id == market.id).order_by(Outcome.outcome_index))
            outcomes = list(result.scalars().all())
            if not outcomes:
                continue

            # Check if positions exist
            result = await db.execute(select(Position).where(Position.market_id == market.id).limit(1))
            if result.scalar_one_or_none():
                continue

            prices = await _outcome_prices(db, market.id, outcomes)
            for user in users:
                # Not every user in every market: a position implies a
                # conviction. Roughly half, so the portfolio has breadth without
                # looking auto-populated.
                if uniform(0, 1) > 0.5:
                    continue
                outcome = choice(outcomes)
                current = prices.get(str(outcome.id), 0.5)
                # Average price near the current one, so unrealised P&L is
                # plausible in both directions rather than always deeply negative
                # against an unrelated entry price.
                entry = min(max(current + uniform(-0.12, 0.12), 0.01), 0.99)
                shares = Decimal(str(round(uniform(50, 2000), 2)))
                position = Position(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    market_id=market.id,
                    outcome_id=outcome.id,
                    shares_held=shares,
                    average_price=Decimal(str(round(entry, 4))),
                    realized_pnl=Decimal(str(round(uniform(-500, 2000), 2))),
                )
                db.add(position)
                position_count += 1

        await db.flush()

        # Resolve a few markets so settlement, claims and the Resolved badge are
        # demoable. All 17 markets were `active`, which meant the most
        # distinctive part of the system - $1 per correct share, claimed through
        # the escrow - could not be shown at all.
        print("Resolving some markets...")
        resolved_count = 0
        for market_data in RESOLVED_MARKETS:
            market = next(
                (m for m in markets if m.slug == market_data["slug"]), None
            )
            if market is None or market.status == "resolved":
                continue

            outcomes = list(
                (
                    await db.execute(
                        select(Outcome)
                        .where(Outcome.market_id == market.id)
                        .order_by(Outcome.outcome_index)
                    )
                ).scalars().all()
            )
            winner_name = market_data["winner"]
            winner = next(
                (o for o in outcomes if o.name.lower() == winner_name.lower()), None
            )
            if winner is None:
                continue

            market.status = "resolved"
            market.winning_outcome_id = winner.id
            # Same date the history was generated against.
            market.resolved_at = _planned_resolved_at(market.slug, now)
            market.closes_at = market.resolved_at - timedelta(days=randint(1, 5))

            # The winning outcome settles at $1.00 per share, so its final
            # history point is 1.0 and the losers' is 0.0 - which is what a
            # settled chart should show.
            await _finalise_history(db, market.id, winner, market.resolved_at)
            for loser in outcomes:
                if loser.id != winner.id:
                    await _finalise_history(db, market.id, loser, market.resolved_at, settled=0)
            resolved_count += 1

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

            prices = await _outcome_prices(db, market.id, outcomes)
            for user in users[:8]:
                outcome = choice(outcomes)
                amount = Decimal(str(round(uniform(50, 500), 2)))
                # remaining <= amount, always. Both were independent randoms
                # before, so roughly a third of resting orders claimed more
                # unfilled than they were ever sized for - a state the order
                # service can never produce.
                remaining = (
                    amount * Decimal(str(round(uniform(0.1, 1.0), 4)))
                ).quantize(Decimal("0.01"))
                order = Order(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    market_id=market.id,
                    outcome_id=outcome.id,
                    side=choice(["buy", "sell"]),
                    order_type="limit",
                    amount=amount,
                    price=Decimal(str(_trade_price(prices.get(str(outcome.id), 0.5)))),
                    remaining_amount=remaining,
                    status="pending",
                    client_order_id=str(uuid.uuid4()),
                    created_at=now - timedelta(hours=uniform(0, 48)),
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
