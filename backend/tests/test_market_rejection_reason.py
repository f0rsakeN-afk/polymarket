"""A rejection says why.

Same reasoning as `test_ban_reason.py`, applied to the other admin decision that
had no explanation attached.

`POST /admin/markets/{id}/reject` took no body. It set the market to `rejected`,
recorded `summary="Rejected market {slug}"`, and told the author nothing. The
author keeps read access to their own submission, so the market row is the only
place the reason can reach them — and a submission rejected with no reason cannot
be fixed, because nobody can tell whether the problem was the wording, the
category, or the resolution criteria.

This is the same failure mode as the ban: an operator performing an irreversible
thing with no recorded ground, and a person on the receiving end with nothing to
appeal.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.models.market import STATUS_REJECTED
from app.models.user import User


async def _reject(client: AsyncClient, market_id, body: dict | None):
    """`body=None` sends **no body at all**, so the "no reason given" case is real.

    A helper that substitutes a default here would make the test that exists to
    prove a body is required unable to fail.
    """
    kwargs = {} if body is None else {"json": body}
    return await client.post(f"/api/v1/admin/markets/{market_id}/reject", **kwargs)


@pytest.fixture
async def pending_market(db_session, admin_user):
    """A market actually in the review queue.

    `_pending_market` refuses to moderate anything not in `pending_review`, and
    the shared `test_market` fixture is `active` — so rejecting it would fail on
    the state check before the reason was ever validated.
    """
    from datetime import UTC, datetime, timedelta

    from app.models.market import STATUS_PENDING_REVIEW, Market

    market = Market(
        slug=f"reject-reason-{uuid.uuid4().hex[:8]}",
        question="Will this rejection record its reason?",
        description="test market",
        category="meta",
        status=STATUS_PENDING_REVIEW,
        created_by=admin_user.id,
        closes_at=datetime.now(UTC) + timedelta(days=30),
        total_liquidity="0",
        total_volume="0",
    )
    db_session.add(market)
    await db_session.commit()
    return market


@pytest.fixture
def mid(pending_market) -> str:
    """The market id as a plain string, read before anything commits.

    Reading `.id` after a request would be a lazy load in sync context — the
    application commits on its own session and expires this one's objects.
    """
    return str(pending_market.id)


@pytest.fixture(autouse=True)
async def _as_admin(client: AsyncClient, admin_user):
    """Autouse so a test that forgets it fails as 401, not as "the reject was refused"."""
    from conftest import token_for

    client.cookies.set("access_token", token_for(admin_user.id))


async def _row(db_session, market_id: str) -> dict:
    """Read through raw SQL, not the ORM.

    The application commits on its own session; this session's identity map still
    holds the pre-rejection row, so an ORM select returns values that no longer
    exist and the test asserts against a phantom.
    """
    result = await db_session.execute(
        text("SELECT status, rejection_reason, rejected_at FROM markets WHERE id = :mid"),
        {"mid": market_id},
    )
    return dict(result.one()._mapping)


# ── The reason is required ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_rejection_without_a_reason_is_refused(
    client: AsyncClient, admin_user, pending_market, mid
):
    resp = await _reject(client, mid, None)

    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_a_rejection_with_a_blank_reason_is_refused(
    client: AsyncClient, admin_user, pending_market, mid
):
    """Whitespace is not a reason, and must not pass as one."""
    resp = await _reject(client, mid, {"reason": "  "})

    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_an_over_long_reason_is_refused(
    client: AsyncClient, admin_user, pending_market, mid
):
    resp = await _reject(client, mid, {"reason": "x" * 2000})

    assert resp.status_code == 422, resp.text


# ── The reason is stored and surfaced ────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_reason_is_stored_on_the_market(
    client: AsyncClient, db_session, admin_user, pending_market, mid
):
    """It has to be readable later, which means it cannot exist only in a log."""
    resp = await _reject(client, mid, {"reason": "resolution criteria are unresolvable"})

    assert resp.status_code == 200, resp.text
    row = await _row(db_session, mid)
    assert row["rejection_reason"] == "resolution criteria are unresolvable"
    assert row["rejected_at"] is not None
    assert row["status"] == STATUS_REJECTED


@pytest.mark.asyncio
async def test_the_author_can_see_why_their_submission_was_declined(
    client: AsyncClient, db_session, admin_user, test_user, pending_market, mid
):
    """The author keeps read access to their own submission, so this column is the
    only channel the reason has. Without it the market simply vanishes."""
    slug = pending_market.slug
    # Reassign to the account that will read it. The fixture's market belongs to
    # `admin_user`, so reading it as `test_user` 404s — correctly, and for a
    # reason that has nothing to do with the reason field under test.
    from conftest import token_for
    from sqlalchemy import text

    author_id = str(test_user.id)
    await db_session.execute(
        text("UPDATE markets SET created_by = :uid WHERE id = :mid"),
        {"uid": author_id, "mid": mid},
    )
    await db_session.commit()
    await _reject(client, mid, {"reason": "too ambiguous to resolve"})

    client.cookies.set("access_token", token_for(author_id))
    resp = await client.get(f"/api/v1/markets/{slug}")

    assert resp.status_code == 200, resp.text
    assert "too ambiguous to resolve" in resp.text


@pytest.mark.asyncio
async def test_the_reason_reaches_the_audit_trail(
    client: AsyncClient, db_session, admin_user, pending_market, mid
):
    """The trail is how this is explained to whoever asks in six months."""
    from sqlalchemy import select

    from app.models.audit import AdminAuditEvent

    await _reject(client, mid, {"reason": "duplicate of an existing market"})

    rows = (
        (
            await db_session.execute(
                select(AdminAuditEvent).where(
                    AdminAuditEvent.action == "market_rejected",
                    AdminAuditEvent.target_id == mid,
                )
            )
        )
        .scalars()
        .all()
    )

    assert rows, "the rejection was not audited at all"
    assert (rows[-1].payload or {}).get("reason") == "duplicate of an existing market"
    assert "duplicate of an existing market" in (rows[-1].summary or "")


# ── The things that must still be true ──────────────────────────────────────


@pytest.mark.asyncio
async def test_a_non_admin_still_cannot_reject_with_a_reason(
    client: AsyncClient, test_user, pending_market, mid
):
    """The body is not a way in. A reason makes no difference to authorisation."""
    from conftest import token_for

    client.cookies.set("access_token", token_for(str(test_user.id)))

    resp = await _reject(client, mid, {"reason": "because I said so"})

    assert resp.status_code in (401, 403), resp.text


@pytest.mark.asyncio
async def test_the_author_cannot_reject_their_own_market(
    client: AsyncClient, db_session, pending_market, mid
):
    """Ownership is not authority.

    An author who could decline their own submission could pull a market off the
    review queue without an operator ever seeing it — which is a way to avoid
    review, not a way to fix a market.
    """
    from conftest import create_login_session

    from app.deps import hash_password

    author = User(
        email=f"author_{uuid.uuid4().hex[:8]}@example.com",
        username=f"author_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("Author!Pass1"),
        is_active=True,
        is_email_verified=True,
    )
    db_session.add(author)
    await db_session.flush()
    await create_login_session(db_session, author)
    await db_session.commit()
    author_id = str(author.id)
    from sqlalchemy import text

    # Raw SQL, because assigning `pending_market.created_by` would be a lazy-load
    # hazard once the commit below expires the fixture's objects.
    await db_session.execute(
        text("UPDATE markets SET created_by = :aid WHERE id = :mid"),
        {"aid": author_id, "mid": mid},
    )
    await db_session.commit()

    from conftest import token_for

    client.cookies.set("access_token", token_for(author_id))
    resp = await _reject(client, mid, {"reason": "changed my mind"})

    assert resp.status_code in (401, 403), resp.text
    row = await _row(db_session, mid)
    assert row["rejection_reason"] is None, "a non-admin got a rejection through"


@pytest.mark.asyncio
async def test_a_malformed_market_id_is_a_422_not_a_crash(
    client: AsyncClient, admin_user
):
    """Guard ordering: the id must be parsed before it reaches the driver.

    `uuid.UUID("nope")` raises `ValueError` inside the query, which surfaces as a
    500 on a caller mistake and leaves the session in a failed state.
    """
    resp = await _reject(client, "not-a-uuid", {"reason": "because"})

    assert resp.status_code in (404, 422), resp.text


@pytest.mark.asyncio
async def test_an_already_rejected_market_keeps_its_original_reason(
    client: AsyncClient, db_session, admin_user, pending_market, mid
):
    """Re-rejection is refused, so the recorded reason cannot be silently rewritten.

    A rejected market is no longer pending, so a second decline is a 422 rather
    than a second decision. That matters for the reason as much as the status: an
    audit row reading "rejected: wrong" and a market reading "rejected: right"
    would be two records of one event that disagree.
    """
    await _reject(client, mid, {"reason": "first, the real one"})

    second = await _reject(client, mid, {"reason": "second, a rewrite"})
    assert second.status_code == 422, second.text

    row = await _row(db_session, mid)
    assert row["rejection_reason"] == "first, the real one"


@pytest.mark.asyncio
async def test_an_approved_market_is_not_rejection_stamped(
    client: AsyncClient, db_session, admin_user, pending_market, mid
):
    """A pending market carries no rejection fields.

    If the columns were set at creation rather than at rejection, an approved
    market would read as declined.
    """
    row = await _row(db_session, mid)

    assert row["rejection_reason"] is None
    assert row["rejected_at"] is None


@pytest.mark.asyncio
async def test_the_rejection_reason_is_in_the_admin_list(
    client: AsyncClient, admin_user, pending_market, mid
):
    """An admin triaging a queue needs to see the reason without opening each one."""
    await _reject(client, mid, {"reason": "duplicate of an existing market"})

    resp = await client.get("/api/v1/admin/markets?status=rejected")

    assert resp.status_code == 200, resp.text
    assert "duplicate of an existing market" in resp.text


@pytest.mark.asyncio
async def test_a_valid_reason_still_performs_the_rejection(
    client: AsyncClient, db_session, admin_user, pending_market, mid
):
    """A required field must not become a reason to skip the safety work.

    The status change is what takes the market off the review queue and out of
    the catalogue; it has to happen whichever reason was given.
    """
    await _reject(client, mid, {"reason": "unresolvable question"})

    row = await _row(db_session, mid)
    assert row["status"] == STATUS_REJECTED