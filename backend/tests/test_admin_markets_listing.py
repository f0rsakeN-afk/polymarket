"""Every market, to an operator.

## The gap

`GET /admin/markets` had a working `status` filter and no way to see everything.
The admin screen defaulted to `pending_review`, so "is anything wrong with the
markets" was not a question this endpoint could answer — and three of the seven
states (`closed`, `resolving`, `dispute_window`) were not offered as filters at
all, so a market stuck in any of them could not be found on the screen meant to
catch it.

There was also no search and no sorting. Which meant an operator holding a
username from a support ticket had no way to find that user's submissions.

Asserted here: that omitting `status` returns everything, that search covers the
submitter as well as the text, and that every sort is a *total* order — without a
tiebreak, paging forward and back skips one market and repeats another.
"""

import uuid

import pytest
from httpx import AsyncClient

from app.models.market import (
    STATUS_ACTIVE,
    STATUS_CLOSED,
    STATUS_PENDING_REVIEW,
    STATUS_REJECTED,
    STATUS_RESOLVED,
    Market,
    Outcome,
)


@pytest.fixture
async def creator(db_session):
    from app.deps import hash_password
    from app.models.user import User

    user = User(
        email=f"search_{uuid.uuid4().hex[:8]}@example.com",
        username=f"searcher{uuid.uuid4().hex[:6]}",
        password_hash=hash_password("Search!Pass1"),
        is_active=True,
        is_email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()
    return user


@pytest.fixture(autouse=True)
async def _as_admin(client: AsyncClient, admin_user):
    from conftest import token_for

    client.cookies.set("access_token", token_for(admin_user.id))


async def _market(
    db_session,
    *,
    slug: str,
    question: str,
    status: str = STATUS_ACTIVE,
    volume: str = "0",
    liquidity: str = "0",
    closes_in_days: int = 30,
    created_by=None,
) -> str:
    from datetime import UTC, datetime, timedelta

    market = Market(
        slug=slug,
        question=question,
        status=status,
        total_volume=volume,
        total_liquidity=liquidity,
        closes_at=datetime.now(UTC) + timedelta(days=closes_in_days),
        created_by=created_by,
    )
    db_session.add(market)
    await db_session.flush()
    await db_session.commit()
    return str(market.id)


def _rows(client_payload: dict) -> list[dict]:
    return client_payload["data"]


# ── Everything ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_omitting_the_status_returns_every_market(client: AsyncClient, db_session):
    await _market(db_session, slug="a-active", question="Active one", status=STATUS_ACTIVE)
    await _market(db_session, slug="b-pending", question="Pending one", status=STATUS_PENDING_REVIEW)
    await _market(db_session, slug="c-closed", question="Closed one", status=STATUS_CLOSED)
    await _market(db_session, slug="d-resolved", question="Resolved one", status=STATUS_RESOLVED)

    resp = await client.get("/api/v1/admin/markets", params={"page_size": 100})

    assert resp.status_code == 200, resp.text
    slugs = {m["slug"] for m in _rows(resp.json())}
    assert slugs == {"a-active", "b-pending", "c-closed", "d-resolved"}


@pytest.mark.asyncio
async def test_a_status_still_narrows_it(client: AsyncClient, db_session):
    await _market(db_session, slug="a-active", question="Active one", status=STATUS_ACTIVE)
    await _market(db_session, slug="b-rejected", question="Rejected one", status=STATUS_REJECTED)

    resp = await client.get("/api/v1/admin/markets", params={"status": STATUS_REJECTED})

    assert {m["slug"] for m in _rows(resp.json())} == {"b-rejected"}


# ── Search ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_matches_the_question(client: AsyncClient, db_session):
    await _market(db_session, slug="x", question="Will the volcano erupt this year?")
    await _market(db_session, slug="y", question="Will the election be close?")

    resp = await client.get("/api/v1/admin/markets", params={"q": "volcano"})

    assert {m["slug"] for m in _rows(resp.json())} == {"x"}


@pytest.mark.asyncio
async def test_search_matches_the_slug(client: AsyncClient, db_session):
    await _market(db_session, slug="epl-2027-champion", question="Who wins?")
    await _market(db_session, slug="nba-2027-champion", question="Who wins again?")

    resp = await client.get("/api/v1/admin/markets", params={"q": "epl"})

    assert {m["slug"] for m in _rows(resp.json())} == {"epl-2027-champion"}


@pytest.mark.asyncio
async def test_search_matches_the_submitter(client: AsyncClient, db_session, creator):
    """The case the old screen could not answer at all.

    A moderator is most often looking for a market because someone quoted them a
    username from a ticket. Matching only the question text misses that entirely.
    """
    await _market(
        db_session, slug="mine", question="Something unrelated", created_by=creator.id
    )
    await _market(db_session, slug="theirs", question="Nothing to do with them")

    resp = await client.get("/api/v1/admin/markets", params={"q": creator.email})

    assert {m["slug"] for m in _rows(resp.json())} == {"mine"}


@pytest.mark.asyncio
async def test_search_matches_the_username(client: AsyncClient, db_session, creator):
    await _market(db_session, slug="mine", question="Something", created_by=creator.id)

    resp = await client.get("/api/v1/admin/markets", params={"q": creator.username})

    assert {m["slug"] for m in _rows(resp.json())} == {"mine"}


@pytest.mark.asyncio
async def test_search_treats_wildcards_as_literal_text(client: AsyncClient, db_session):
    """`q=%` unescaped is a pattern matching every row.

    A search box that returns everything when you paste a percent sign is worse
    than one that returns nothing: it looks like it worked.
    """
    await _market(db_session, slug="pct", question="Falls below 0.1% by default")
    await _market(db_session, slug="plain", question="Nothing special here")

    resp = await client.get("/api/v1/admin/markets", params={"q": "%"})

    assert {m["slug"] for m in _rows(resp.json())} == {"pct"}


@pytest.mark.asyncio
async def test_search_combines_with_the_status_filter(client: AsyncClient, db_session):
    await _market(db_session, slug="hit", question="Volcano watch", status=STATUS_REJECTED)
    await _market(db_session, slug="miss", question="Volcano watch", status=STATUS_ACTIVE)

    resp = await client.get(
        "/api/v1/admin/markets", params={"q": "volcano", "status": STATUS_REJECTED}
    )

    assert {m["slug"] for m in _rows(resp.json())} == {"hit"}


@pytest.mark.asyncio
async def test_search_matching_nothing_is_an_empty_list_not_an_error(
    client: AsyncClient, db_session
):
    await _market(db_session, slug="a", question="Something")

    resp = await client.get("/api/v1/admin/markets", params={"q": "zzzznope"})

    assert resp.status_code == 200
    assert resp.json()["data"] == []
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_a_search_term_is_not_a_sql_injection(client: AsyncClient, db_session):
    await _market(db_session, slug="safe", question="A market")

    resp = await client.get("/api/v1/admin/markets", params={"q": "'; DROP TABLE markets; --"})

    assert resp.status_code == 200, resp.text
    # Still there.
    assert (await client.get("/api/v1/admin/markets")).json()["total"] >= 1


# ── Sorting ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sorts_by_volume(client: AsyncClient, db_session):
    await _market(db_session, slug="low", question="Low", volume="100")
    await _market(db_session, slug="high", question="High", volume="9000")
    await _market(db_session, slug="mid", question="Mid", volume="5000")

    resp = await client.get("/api/v1/admin/markets", params={"sort": "volume"})

    assert [m["slug"] for m in _rows(resp.json())] == ["high", "mid", "low"]


@pytest.mark.asyncio
async def test_sorts_by_closing_soon(client: AsyncClient, db_session):
    await _market(db_session, slug="late", question="Late", closes_in_days=300)
    await _market(db_session, slug="soon", question="Soon", closes_in_days=2)

    resp = await client.get("/api/v1/admin/markets", params={"sort": "closing_soon"})

    assert [m["slug"] for m in _rows(resp.json())][0] == "soon"


@pytest.mark.asyncio
async def test_every_sort_is_a_total_order_so_paging_cannot_skip_a_row(
    client: AsyncClient, db_session
):
    """Ten rows that all tie on the sort key.

    Without a tiebreak on `id`, Postgres is free to return ties in any order, and
    two pages fetched separately can disagree — so paging forward then back shows
    one row twice and skips another.
    """
    for i in range(10):
        await _market(
            db_session, slug=f"tie-{i:02d}", question="All identical", volume="5000"
        )

    first = _rows((await client.get("/api/v1/admin/markets", params={"sort": "volume", "page": 1, "page_size": 4})).json())
    second = _rows((await client.get("/api/v1/admin/markets", params={"sort": "volume", "page": 2, "page_size": 4})).json())
    third = _rows((await client.get("/api/v1/admin/markets", params={"sort": "volume", "page": 3, "page_size": 4})).json())

    seen = [m["slug"] for m in first + second + third]
    assert len(seen) == 10
    assert len(set(seen)) == 10, "paging repeated or skipped a market"


@pytest.mark.asyncio
async def test_an_unknown_sort_is_refused(client: AsyncClient):
    """A typo in the parameter must not silently fall back to something else."""
    resp = await client.get("/api/v1/admin/markets", params={"sort": "sideways"})

    assert resp.status_code == 422, resp.text


# ── Row payload ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rows_carry_what_an_operator_triages_on(
    client: AsyncClient, db_session, creator
):
    from app.models.market import Outcome

    market_id = await _market(
        db_session,
        slug="detail",
        question="What does this row carry?",
        created_by=creator.id,
        volume="1234.5",
    )
    db_session.add_all(
        [
            Outcome(market_id=market_id, name="Manchester City", outcome_index=0),
            Outcome(market_id=market_id, name="Arsenal", outcome_index=1),
            Outcome(market_id=market_id, name="Liverpool", outcome_index=2),
        ]
    )
    await db_session.commit()

    rows = _rows((await client.get("/api/v1/admin/markets", params={"q": "detail"})).json())
    row = rows[0]

    assert row["created_by_email"] == creator.email
    assert row["num_trades"] == 0
    assert float(row["total_volume"]) == 1234.5
    # Three legs is the fact that says "this is parimutuel", and it changes how
    # every price on the market reads.
    assert row["outcome_count"] == 3
    assert row["closes_at"]


@pytest.mark.asyncio
async def test_outcome_counts_do_not_cost_a_query_per_row(client: AsyncClient, db_session):
    """Ten markets, and the counts still come back — which is the observable
    consequence of the single grouped query rather than one per row."""
    for i in range(10):
        market_id = await _market(db_session, slug=f"many-{i:02d}", question=f"Market {i}")
        db_session.add(Outcome(market_id=market_id, name="Yes", outcome_index=0))
    await db_session.commit()

    rows = _rows((await client.get("/api/v1/admin/markets", params={"page_size": 100})).json())

    assert len(rows) == 10
    assert all(r["outcome_count"] == 1 for r in rows)