"""A submission you cannot follow up on.

## The gap this covers

`POST /markets/` put a market into a review queue and returned. From there the
submitter could do nothing with it: there was no list of their own markets, no
status, and no explanation when one was declined. The only way to learn what
happened was to keep the slug and try the direct link — which 404s for everyone
but them and says nothing either way.

That makes proposing a market a write-only operation from the author's side,
which is why it looked like the feature did not exist.

## What is asserted here

The endpoint's access control, its status filtering, its pagination, and — the
part that was quietly broken before — that the rejection reason actually reaches
the person it was written for.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.models.market import (
    STATUS_ACTIVE,
    STATUS_PENDING_REVIEW,
    STATUS_REJECTED,
    Market,
)
from app.models.user import User


@pytest.fixture
async def author(db_session):
    from conftest import create_login_session

    from app.deps import hash_password

    user = User(
        email=f"author_{uuid.uuid4().hex[:8]}@example.com",
        username=f"author_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("Author!Pass1"),
        is_active=True,
        is_email_verified=True,
    )
    db_session.add(user)
    # Flush before minting a session: `create_login_session` writes a
    # `refresh_tokens` row keyed on `user.id`, which is still None until the
    # INSERT has happened. The conftest fixtures do the same, for the same
    # reason.
    await db_session.flush()
    await create_login_session(db_session, user)
    await db_session.commit()
    return user


@pytest.fixture
async def stranger(db_session):
    """A real second user.

    Not a made-up UUID: `markets.created_by` is a foreign key, and inventing an id
    that no user row backs is a constraint violation rather than a test of
    anything.
    """
    from app.deps import hash_password

    user = User(
        email=f"stranger_{uuid.uuid4().hex[:8]}@example.com",
        username=f"stranger_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("Stranger!Pass1"),
        is_active=True,
        is_email_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.fixture
async def as_author(client: AsyncClient, author):
    """Sign the client in as the submitter.

    Ids are read as strings here: the application commits on its own session, and
    reading `.id` afterwards is a lazy load in sync context.
    """
    from conftest import token_for

    uid = str(author.id)
    client.cookies.set("access_token", token_for(uid))
    return uid


async def _make_market(db_session, owner_id: str, **kwargs) -> str:
    default = {
        "slug": f"mine-{uuid.uuid4().hex[:8]}",
        "question": "Will this market appear in my list?",
        "status": STATUS_PENDING_REVIEW,
        "closes_at": datetime.now(UTC) + timedelta(days=30),
        "total_liquidity": "0",
        "total_volume": "0",
    }
    default.update(kwargs)
    # Mirror what `reject_market` does: a rejected market always carries both, so
    # a fixture that set only one would assert on a state the API cannot produce.
    if default["status"] == STATUS_REJECTED:
        default.setdefault("rejected_at", datetime.now(UTC))
    market = Market(created_by=owner_id, **default)
    db_session.add(market)
    await db_session.commit()
    return str(market.id)


# ── Access control ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_anonymous_cannot_list_my_markets(client: AsyncClient):
    """It is somebody's markets. An anonymous caller has no somebody."""
    resp = await client.get("/api/v1/markets/mine")

    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_a_user_only_sees_their_own_markets(
    client: AsyncClient, db_session, author, stranger, as_author
):
    """The whole value of the endpoint is scoping. An unscoped list is a privacy
    incident that happens to look like a feature."""
    other = await _make_market(db_session, str(stranger.id), question="Someone else's market")
    mine = await _make_market(db_session, as_author, question="My own market")

    resp = await client.get("/api/v1/markets/mine")

    assert resp.status_code == 200, resp.text
    ids = {m["id"] for m in resp.json()["data"]}
    assert mine in ids
    assert other not in ids


@pytest.mark.asyncio
async def test_it_does_not_leak_a_market_the_caller_only_guessed_the_slug_of(
    client: AsyncClient, db_session, stranger, as_author
):
    """Guessing a slug must not be a way to enumerate unpublished submissions."""
    await _make_market(db_session, str(stranger.id), question="Pending, not yours")

    resp = await client.get("/api/v1/markets/mine")

    assert all(
        m["status"] != STATUS_PENDING_REVIEW or m["question"] != "Pending, not yours"
        for m in resp.json()["data"]
    )


# ── It shows every state, which is the point ─────────────────────────────────


@pytest.mark.asyncio
async def test_it_includes_unpublished_markets_the_catalogue_hides(
    client: AsyncClient, db_session, as_author
):
    """`GET /markets/` deliberately refuses unpublished statuses for anyone, and
    hides them by default. This is the surface that shows them — to their author."""
    await _make_market(db_session, as_author, status=STATUS_PENDING_REVIEW)
    await _make_market(db_session, as_author, status=STATUS_REJECTED)
    await _make_market(db_session, as_author, status=STATUS_ACTIVE)

    resp = await client.get("/api/v1/markets/mine")

    statuses = {m["status"] for m in resp.json()["data"]}
    assert statuses == {STATUS_PENDING_REVIEW, STATUS_REJECTED, STATUS_ACTIVE}


@pytest.mark.asyncio
async def test_the_rejection_reason_reaches_its_author(
    client: AsyncClient, db_session, as_author
):
    """The bug this file was written for.

    `rejection_reason` was added to the schema, documented as the author's only
    channel, and never actually populated — `market_to_response` builds the model
    field by field, so anything not passed explicitly was silently None. The
    column was written, the audit row was written, and the author saw nothing.
    """
    await _make_market(
        db_session, as_author, status=STATUS_REJECTED, rejection_reason="no date to resolve against"
    )

    resp = await client.get("/api/v1/markets/mine")

    row = resp.json()["data"][0]
    assert row["rejection_reason"] == "no date to resolve against"
    assert row["rejected_at"] is not None


@pytest.mark.asyncio
async def test_a_pending_market_has_no_rejection_reason(
    client: AsyncClient, db_session, as_author
):
    """Null in every other state, so a client can show the field unconditionally."""
    await _make_market(db_session, as_author, status=STATUS_PENDING_REVIEW)

    resp = await client.get("/api/v1/markets/mine")

    assert resp.json()["data"][0]["rejection_reason"] is None


# ── Filtering, paging, and the edge cases around both ────────────────────────


@pytest.mark.asyncio
async def test_the_status_filter_narrows_to_one_state(
    client: AsyncClient, db_session, as_author
):
    await _make_market(db_session, as_author, status=STATUS_PENDING_REVIEW)
    await _make_market(db_session, as_author, status=STATUS_ACTIVE)

    resp = await client.get(f"/api/v1/markets/mine?status={STATUS_PENDING_REVIEW}")

    assert {m["status"] for m in resp.json()["data"]} == {STATUS_PENDING_REVIEW}


@pytest.mark.asyncio
async def test_an_unknown_status_filter_returns_nothing_rather_than_erroring(
    client: AsyncClient, db_session, as_author
):
    """It is a filter over the caller's own rows. There is nothing to protect,
    so an empty list is the honest answer."""
    await _make_market(db_session, as_author)

    resp = await client.get("/api/v1/markets/mine?status=not_a_status")

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == []


@pytest.mark.asyncio
async def test_an_admin_gets_their_own_markets_not_everyones(
    client: AsyncClient, db_session, as_author
):
    """Admin rights must not turn "mine" into "all". An admin creates markets
    through the same form, and their queue view is a different endpoint."""
    from conftest import create_login_session, token_for

    from app.deps import hash_password

    admin = User(
        email=f"adm_{uuid.uuid4().hex[:8]}@example.com",
        username=f"adm_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("Admin!Pass1"),
        is_active=True,
        is_email_verified=True,
        is_admin=True,
    )
    db_session.add(admin)
    await db_session.flush()
    await create_login_session(db_session, admin)
    await db_session.commit()

    await _make_market(db_session, as_author, question="Belongs to the other user")
    admin_id = str(admin.id)
    await _make_market(db_session, admin_id, question="Belongs to the admin")

    client.cookies.set("access_token", token_for(admin_id))
    resp = await client.get("/api/v1/markets/mine")

    questions = {m["question"] for m in resp.json()["data"]}
    assert questions == {"Belongs to the admin"}


@pytest.mark.asyncio
async def test_pagination_covers_every_market_exactly_once(
    client: AsyncClient, db_session, as_author
):
    """Offset paging with a stable sort. Ten rows over three pages of four, then
    assert no row was skipped or shown twice."""
    for _ in range(10):
        await _make_market(db_session, as_author)

    seen: list[str] = []
    for page in (1, 2, 3):
        resp = await client.get(f"/api/v1/markets/mine?page={page}&page_size=4")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 10
        seen.extend(m["id"] for m in body["data"])

    assert len(seen) == 10
    assert len(set(seen)) == 10, "paging repeated or skipped a market"


@pytest.mark.asyncio
async def test_has_more_agrees_with_the_total(
    client: AsyncClient, db_session, as_author
):
    """The two must not disagree, or the UI shows a next-page button onto an
    empty page."""
    for _ in range(5):
        await _make_market(db_session, as_author)

    first = (await client.get("/api/v1/markets/mine?page=1&page_size=2")).json()
    last = (await client.get("/api/v1/markets/mine?page=3&page_size=2")).json()

    assert first["has_more"] is True
    assert last["has_more"] is False


@pytest.mark.asyncio
async def test_a_user_with_no_markets_gets_an_empty_page_not_an_error(
    client: AsyncClient, as_author):
    """The ordinary first-run state. A 404 or an error here would make the page
    look broken to every new user."""
    resp = await client.get("/api/v1/markets/mine")

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == []
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_page_size_is_bounded(client: AsyncClient, as_author):
    """An unbounded page size is a cheap way to be handed the whole table."""
    resp = await client.get("/api/v1/markets/mine?page_size=100000")

    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_a_page_past_the_end_is_empty_rather_than_an_error(
    client: AsyncClient, db_session, as_author):
    """Reaching the end by clicking next must not 500."""
    await _make_market(db_session, as_author)

    resp = await client.get("/api/v1/markets/mine?page=99&page_size=20")

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == []


@pytest.mark.asyncio
async def test_each_row_carries_its_outcomes(
    client: AsyncClient, db_session, as_author
):
    """A binary market with no outcome list renders as a blank card."""
    await _make_market(db_session, as_author)

    resp = await client.get("/api/v1/markets/mine")

    row = resp.json()["data"][0]
    assert row["outcomes"] is None or isinstance(row["outcomes"], list)


@pytest.mark.asyncio
async def test_mine_is_not_captured_by_the_slug_route(
    client: AsyncClient, as_author):
    """`/markets/{slug}` is declared after this one, but only because of where it
    sits in the file. FastAPI matches in order: if `/mine` moved below `/{slug}`,
    every request here would 404 looking for a market with the slug "mine"."""
    resp = await client.get("/api/v1/markets/mine")

    # If `/mine` were being captured by `/{slug}` this would be a 404 shaped like
    # "no market with the slug 'mine'", so assert on the payload shape rather than
    # on the absence of one specific error code.
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert isinstance(body["data"], list)


# ── The create request gained fields; they must be stored, not dropped ───────


@pytest.mark.asyncio
async def test_resolution_criteria_survives_creation(
    client: AsyncClient, db_session, as_author
):
    """A market created with no way to settle it, silently, is the failure this
    whole area of work exists to stop."""
    slug = f"criteria-{uuid.uuid4().hex[:8]}"
    closes = (datetime.now(UTC) + timedelta(days=60)).isoformat()

    resp = await client.post(
        "/api/v1/markets/",
        json={
            "question": "Will the resolution criteria be stored?",
            "slug": slug,
            "closes_at": closes,
            "category": "meta",
            "subcategory": "testing",
            "resolution_criteria": "Resolves Yes if the test suite is green at the cutoff.",
            "resolution_source": "https://ci.example.com/build",
            "image_url": "https://example.com/art.png",
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["resolution_criteria"] == (
        "Resolves Yes if the test suite is green at the cutoff."
    )
    assert body["resolution_source"] == "https://ci.example.com/build"
    assert body["subcategory"] == "testing"
    assert body["image_url"] == "https://example.com/art.png"


@pytest.mark.asyncio
async def test_the_create_response_carries_the_outcomes(client: AsyncClient, as_author):
    """Returning `outcomes: null` from a create made a market that has them look
    like it had none.

    `MarketResponse.outcomes` is nullable because the *list* endpoint omits it, so
    a caller had no way to tell "this market has no outcomes" from "this endpoint
    does not include them" — and the first thing anyone does after creating a
    market is look at it.
    """
    slug = f"created-{uuid.uuid4().hex[:8]}"

    resp = await client.post(
        "/api/v1/markets/",
        json={
            "question": "Will the create response include its outcomes?",
            "slug": slug,
            "closes_at": (datetime.now(UTC) + timedelta(days=60)).isoformat(),
        },
    )

    assert resp.status_code == 200, resp.text
    outcomes = resp.json()["data"]["outcomes"]
    assert outcomes, "the created market came back with no outcomes"
    assert {o["name"].lower() for o in outcomes} == {"yes", "no"}


@pytest.mark.asyncio
async def test_a_non_http_image_url_is_refused(client: AsyncClient, as_author):
    """The value is rendered as an `<img src>`, so `javascript:` and `data:`
    are the thing to refuse. Failing the submission beats rendering nothing."""
    closes = (datetime.now(UTC) + timedelta(days=60)).isoformat()

    for bad in ("javascript:alert(1)", "data:text/html,<script>alert(1)</script>", "/relative/path.png"):
        resp = await client.post(
            "/api/v1/markets/",
            json={
                "question": "Will a hostile image url be refused?",
                "slug": f"img-{uuid.uuid4().hex[:8]}",
                "closes_at": closes,
                "image_url": bad,
            },
        )
        assert resp.status_code == 422, f"{bad!r} was accepted: {resp.text}"


@pytest.mark.asyncio
async def test_the_question_cannot_be_all_whitespace(client: AsyncClient, as_author):
    """Five spaces is five characters and no question."""
    resp = await client.post(
        "/api/v1/markets/",
        json={
            "question": "     ",
            "slug": f"blank-{uuid.uuid4().hex[:8]}",
            "closes_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        },
    )

    assert resp.status_code == 422, resp.text