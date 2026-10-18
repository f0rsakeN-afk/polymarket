"""Telling the author what happened to their submission.

## The gap

`POST /admin/markets/{id}/approve` and `.../reject` changed a market's status and
wrote an audit row. Nothing reached the person who proposed it. Submitting a
market therefore opened a loop with no reply: the author could only find out by
going and looking, and a market that never went live is indistinguishable from
one that was quietly dropped.

The status and the reason are both visible now — `/markets/mine` and
`rejection_reason` — but a page nobody knows to visit is not a notification.
These assertions cover the proactive half.

## What is deliberately not sent

A notification to the moderator's own account when they approve their own market.
They just did it; being told is noise, and it would teach people to ignore the
channel.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select


@pytest.fixture
async def author(db_session) -> str:
    """The author's id, as a plain string.

    Deliberately not the ORM object, for two reasons that both bite here.
    `commit()` expires every attribute, so a later fixture reading `author.id`
    triggers a refresh *inside its own flush* — which is where `Could not refresh
    instance '<User>'` comes from. And returning the object invites
    `where(Notification.user_id == author)`, which passes a `User` where a
    column value belongs. A string sidesteps both.
    """
    from app.deps import hash_password
    from app.models.user import User

    user = User(
        email=f"author_{uuid.uuid4().hex[:8]}@example.com",
        username=f"author_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("Author!Pass1"),
        is_active=True,
        is_email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    # Read while still persistent, before the commit expires it.
    author_id = str(user.id)
    await db_session.commit()
    return author_id


@pytest.fixture
async def pending_market(db_session, author):
    from datetime import UTC, datetime, timedelta

    from app.models.market import STATUS_PENDING_REVIEW, Market

    market = Market(
        slug=f"notify-{uuid.uuid4().hex[:8]}",
        question="Will the author hear about this?",
        description="notification test",
        category="meta",
        status=STATUS_PENDING_REVIEW,
        created_by=author,
        closes_at=datetime.now(UTC) + timedelta(days=30),
        total_liquidity="0",
        total_volume="0",
    )
    db_session.add(market)
    await db_session.flush()
    await db_session.commit()
    return market


@pytest.fixture(autouse=True)
async def _as_admin(client: AsyncClient, admin_user):
    from conftest import token_for

    client.cookies.set("access_token", token_for(admin_user.id))


async def _notifications_for(db_session, user_id) -> list:
    from app.models.notification import Notification

    return (
        (
            await db_session.execute(
                select(Notification).where(Notification.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )


# ── Approval ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_author_is_told_when_their_market_goes_live(
    client: AsyncClient, db_session, author, pending_market
):
    market_id = str(pending_market.id)

    resp = await client.post(f"/api/v1/admin/markets/{market_id}/approve")

    assert resp.status_code == 200, resp.text
    notes = await _notifications_for(db_session, author)
    assert notes, "approval reached the audit trail and nowhere the author"
    assert notes[-1].type == "market_submission_reviewed"
    # The question, not the slug. A slug is how *we* address a market; the author
    # recognises it by what they wrote, and several of their submissions may have
    # near-identical slugs.
    assert pending_market.question in (notes[-1].body or "")
    # The slug still travels, for the link.
    assert (notes[-1].data or {}).get("market_slug") == pending_market.slug


@pytest.mark.asyncio
async def test_the_notification_names_the_market(
    client: AsyncClient, db_session, author, pending_market
):
    """"Your market went live" is useless when there are nine of them."""
    resp = await client.post(f"/api/v1/admin/markets/{pending_market.id}/approve")
    assert resp.status_code == 200, resp.text

    notes = await _notifications_for(db_session, author)
    assert pending_market.question in (notes[-1].title + (notes[-1].body or ""))


@pytest.mark.asyncio
async def test_approval_does_not_notify_the_moderator_about_their_own_market(
    client: AsyncClient, db_session, admin_user, pending_market
):
    """They just did it. Being told is noise, and noise teaches people to ignore
    the channel."""
    from sqlalchemy import text

    await db_session.execute(
        text("UPDATE markets SET created_by = :uid WHERE id = :mid"),
        {"uid": str(admin_user.id), "mid": str(pending_market.id)},
    )
    await db_session.commit()

    resp = await client.post(f"/api/v1/admin/markets/{pending_market.id}/approve")
    assert resp.status_code == 200, resp.text

    assert await _notifications_for(db_session, str(admin_user.id)) == []


# ── Rejection ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_author_is_told_when_their_market_is_declined(
    client: AsyncClient, db_session, author, pending_market
):
    market_id = str(pending_market.id)

    resp = await client.post(
        f"/api/v1/admin/markets/{market_id}/reject",
        json={"reason": "the resolution criteria name no date"},
    )

    assert resp.status_code == 200, resp.text
    notes = await _notifications_for(db_session, author)
    assert notes, "the decline reached the audit trail and nowhere the author"
    assert notes[-1].type == "market_submission_declined"


@pytest.mark.asyncio
async def test_the_decline_notification_carries_the_reason(
    client: AsyncClient, db_session, author, pending_market
):
    """The reason is the entire content of a decline. "Your market was declined"
    with nothing attached is the notification equivalent of the bug this whole
    area started from."""
    resp = await client.post(
        f"/api/v1/admin/markets/{pending_market.id}/reject",
        json={"reason": "too ambiguous to settle fairly"},
    )
    assert resp.status_code == 200, resp.text

    notes = await _notifications_for(db_session, author)
    assert "too ambiguous to settle fairly" in (notes[-1].body or "")


@pytest.mark.asyncio
async def test_the_decline_notification_links_to_the_market(
    client: AsyncClient, db_session, author, pending_market
):
    """So the bell's link has somewhere to go."""
    resp = await client.post(
        f"/api/v1/admin/markets/{pending_market.id}/reject",
        json={"reason": "not resolvable"},
    )
    assert resp.status_code == 200, resp.text

    notes = await _notifications_for(db_session, author)
    assert (notes[-1].data or {}).get("market_slug") == pending_market.slug


# ── The decision still happens if the notification cannot ───────────────────


@pytest.mark.asyncio
async def test_a_decline_still_lands_when_notification_dispatch_raises(
    client: AsyncClient, db_session, author, pending_market, monkeypatch
):
    """The moderator pressed decline. A failure to write a convenience row must
    not turn that into an error and make them press it again.

    This is the shape of the bug worth preventing: a notification that can veto
    the action it is reporting on. The audit and the status change happen first
    and stand on their own.
    """
    from app.api import admin as admin_module
    from app.models.market import STATUS_REJECTED

    async def boom(*args, **kwargs):
        raise RuntimeError("redis is down")

    monkeypatch.setattr(admin_module.NotificationService, "dispatch", boom)

    resp = await client.post(
        f"/api/v1/admin/markets/{pending_market.id}/reject",
        json={"reason": "still needs saying"},
    )

    # The action succeeded; only the courtesy notification failed.
    assert resp.status_code == 200, resp.text

    from sqlalchemy import text

    row = (
        await db_session.execute(
            text(
                "SELECT status, rejection_reason FROM markets WHERE id = :mid"
            ),
            {"mid": str(pending_market.id)},
        )
    ).one()
    assert row[0] == STATUS_REJECTED
    assert row[1] == "still needs saying"