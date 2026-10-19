"""Markets with more than two outcomes.

## The gap

`MarketOutcomeCreate.outcome_index` was capped at `le=1`, so every index above 1
was a 422. Everything around it had been written for N outcomes all along:
`is_parimutuel` decides by name rather than by counting, `outcome_prices` weights
by each outcome's own pool, and `create_market` builds one `LiquidityPool` per
outcome. The cap lived only in the request schema — the database constraint was
always `>= 0` — so the feature read as supported and rejected it.

The form offered an "Add Outcome" control that could build a five-way market the
API then refused, which is worse than never offering it: it looks like the tool
is broken rather than unavailable.

## What is asserted here

That N outcomes work end to end, and that each way of getting it *wrong* is
refused with something the caller can act on rather than a database error.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.models.market import STATUS_PENDING_REVIEW


@pytest.fixture
async def as_author(client: AsyncClient, db_session):
    """A signed-in, email-verified submitter.

    The fixture every create path needs: unverified accounts are refused before
    they reach validation, so without this every assertion below would be testing
    the 403 instead of the thing it names.
    """
    from conftest import create_login_session, token_for

    from app.deps import hash_password
    from app.models.user import User

    user = User(
        email=f"outcomes_{uuid.uuid4().hex[:8]}@example.com",
        username=f"outcomes_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("Outcomes!Pass1"),
        is_active=True,
        is_email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    user_id = str(user.id)
    await create_login_session(db_session, user)
    await db_session.commit()

    client.cookies.set("access_token", token_for(user_id))
    return user_id


def _closes(days: int = 30) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def _payload(slug: str, names: list[str], **extra) -> dict:
    return {
        "question": "Will more than two outcomes work?",
        "slug": slug,
        "closes_at": _closes(),
        "outcomes_create": [
            {"name": n, "outcome_index": i} for i, n in enumerate(names)
        ],
        **extra,
    }


# ── Schema ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("label", "expected", "outcomes"),
    [
        ("a single outcome", "at least 2 outcomes", [{"name": "A", "outcome_index": 0}]),
        # `UNIQUE (market_id, outcome_index)` would answer this with a database
        # integrity error, which tells a caller nothing they can fix.
        ("duplicate indices", "no gaps or duplicates", [{"name": "A", "outcome_index": 0}, {"name": "B", "outcome_index": 0}]),
        # The index is a position: prices, the tape and the outcome list are all
        # ordered by it, so 0,1,3 renders a gap.
        ("a gap in the indices", "no gaps or duplicates", [{"name": "A", "outcome_index": 0}, {"name": "B", "outcome_index": 2}]),
        ("duplicate names", "distinct names", [{"name": "Same", "outcome_index": 0}, {"name": "same", "outcome_index": 1}]),
        ("a blank name", "needs a name", [{"name": "A", "outcome_index": 0}, {"name": "   ", "outcome_index": 1}]),
        ("no outcomes at all", "at least 2 outcomes", []),
    ],
)
def test_a_malformed_outcome_set_is_refused(label, expected, outcomes):
    from app.schemas.market import CreateMarketRequest

    with pytest.raises(Exception, match=expected):
        CreateMarketRequest(
            question="Will more than two outcomes work?",
            slug="will-it-work",
            closes_at=datetime.now(UTC) + timedelta(days=30),
            outcomes_create=outcomes,
        )


def test_the_ceiling_is_enforced():
    """An outcome appears in every orderbook response and trade row, so unbounded
    is a way to make one market expensive for everyone."""
    from app.schemas.market import MAX_OUTCOMES, CreateMarketRequest

    at_limit = [{"name": f"O{i}", "outcome_index": i} for i in range(MAX_OUTCOMES)]
    CreateMarketRequest(
        question="Will the ceiling work?",
        slug="will-it-work",
        closes_at=datetime.now(UTC) + timedelta(days=30),
        outcomes_create=at_limit,
    )

    with pytest.raises(Exception):
        CreateMarketRequest(
            question="Will the ceiling work?",
            slug="will-it-work",
            closes_at=datetime.now(UTC) + timedelta(days=30),
            outcomes_create=at_limit + [{"name": "One more", "outcome_index": MAX_OUTCOMES}],
        )


# ── End to end ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_eight_way_market_can_be_created_and_read_back(
    client: AsyncClient, db_session, as_author
):
    from sqlalchemy import select

    from app.models.market import Outcome

    names = ["Manchester City", "Arsenal", "Liverpool", "Chelsea", "Tottenham", "Everton", "Brighton", "Other"]

    resp = await client.post("/api/v1/markets/", json=_payload("epl-champions-2027", names))

    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["status"] == STATUS_PENDING_REVIEW
    # Every outcome, in index order — the ordering the tape and prices rely on.
    returned = [o["name"] for o in body["outcomes"]]
    assert returned == names

    stored = (
        await db_session.execute(
            select(Outcome).where(Outcome.market_id == body["id"]).order_by(Outcome.outcome_index)
        )
    ).scalars().all()
    assert [o.name for o in stored] == names


@pytest.mark.asyncio
async def test_a_many_outcome_market_gets_a_pool_per_outcome(
    client: AsyncClient, db_session, as_author
):
    """One binary pool for an eight-way market left every outcome priced off the
    same reserve, so the market reported Yes 75 / No 25 no matter what the
    outcomes were. That was a real bug and the reason this path is worth pinning.
    """
    from sqlalchemy import func, select

    from app.models.liquidity import LiquidityPool
    from app.models.market import Outcome

    names = ["A", "B", "C", "D", "E", "F"]
    resp = await client.post("/api/v1/markets/", json=_payload("six-way-market", names))
    assert resp.status_code == 200, resp.text
    market_id = resp.json()["data"]["id"]

    outcome_ids = (
        await db_session.execute(
            select(Outcome.id).where(Outcome.market_id == market_id)
        )
    ).scalars().all()

    pool_count = await db_session.execute(
        select(func.count(LiquidityPool.id)).where(
            LiquidityPool.outcome_id.in_(outcome_ids)
        )
    )
    assert pool_count.scalar() == len(names)


@pytest.mark.asyncio
async def test_a_binary_market_is_still_binary(
    client: AsyncClient, db_session, as_author
):
    """Raising the ceiling must not change what a two-outcome market does."""
    resp = await client.post(
        "/api/v1/markets/",
        json=_payload("still-binary", ["Yes", "No"], category="meta"),
    )

    assert resp.status_code == 200, resp.text
    assert [o["name"] for o in resp.json()["data"]["outcomes"]] == ["Yes", "No"]


@pytest.mark.asyncio
async def test_omitting_outcomes_still_defaults_to_yes_and_no(
    client: AsyncClient, db_session, as_author
):
    resp = await client.post(
        "/api/v1/markets/",
        json={
            "question": "Will the default pair still be created?",
            "slug": "default-pair-still-works",
            "closes_at": _closes(),
        },
    )

    assert resp.status_code == 200, resp.text
    assert [o["name"] for o in resp.json()["data"]["outcomes"]] == ["Yes", "No"]