"""A ban says why.

## The problem

`PATCH /admin/users/{id}/ban` took no body. It deactivated the account, cancelled
every resting order, revoked every session — and recorded a summary of
`f"Banned {user.email}"`. So:

- the **user** was told only "Account is inactive", with nothing to appeal;
- the **next admin** opening the record had no way to tell a justified ban from a
  mistake, because the reason was never captured anywhere;
- an **auditor** asking "why was this account deactivated in March" had a date,
  an actor, and no answer.

The amount of machinery a ban performs — cancelling orders, releasing reserved
funds, revoking sessions — makes an unexplained one worse, not better. An
operator locking someone out with no stated ground has done something they cannot
later justify.

## What is required, and what is not

`reason` is **required**, bounded, and must be more than whitespace. A blank
string is the same as no reason, and a reason nobody had to think about is the
one that ends up as "n/a" in the audit six months later.

`note` is optional and longer: "chargeback fraud, three attempts at 0.01 USDC
cards" as a note under "suspected fraud" as a reason.

Unbanning takes an optional note and **clears** the reason, so a live account
never reads as banned. The history is not lost — it is in the audit trail, with
the actor, IP and user agent.

## Why the reason is stored on the user *and* in the audit

Not duplication for its own sake. The audit trail answers "what happened"; the
column answers "what does this record show right now", including to the banned
user. The **actor** is stored only in the audit — one place that knows who did it,
so there is nothing to disagree with.
"""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.models.user import User


@pytest.fixture
async def target_user(test_user):
    return test_user


async def _ban(client: AsyncClient, user_id, body: dict | None):
    """`body=None` sends **no body at all**.

    The first version substituted a default reason when the body was `None`,
    which quietly meant the "no reason given" test could never fail - it was
    sending a reason. A helper that rescues the case under test is worse than no
    helper.
    """
    kwargs = {} if body is None else {"json": body}
    return await client.patch(f"/api/v1/admin/users/{user_id}/ban", **kwargs)


async def _row(db_session, user_id: str) -> dict:
    """Read the stored row with raw SQL.

    Deliberately not the ORM. The application commits on its own session, and this
    session's identity map still holds the row as it was *before* that commit -
    so `expire_all()` followed by an ORM select returns the pre-ban values and the
    test passes or fails against a row that no longer exists. A statement against
    the table bypasses the map entirely.
    """
    from sqlalchemy import text

    result = await db_session.execute(
        text("SELECT is_active, ban_reason, banned_at FROM users WHERE id = :uid"),
        {"uid": user_id},
    )
    return dict(result.one()._mapping)


@pytest.fixture
def uid(target_user) -> str:
    """The target's id as a plain string, read before anything commits.

    The app's request runs on its own session, and its commit expires every
    attribute on this session's objects. Reading `target_user.id` afterwards is a
    lazy load in sync context, which raises `MissingGreenlet` - an error about
    greenlets that has nothing to do with what the test is checking.
    """
    return str(target_user.id)


@pytest.fixture(autouse=True)
async def _as_admin(client: AsyncClient, admin_user):
    """Every request here is an admin request.

    Autouse because a test that forgets it gets a 401 and reads as "the ban was
    refused" rather than "nobody was signed in" — which is the more alarming
    reading and the wrong one.
    """
    from conftest import token_for

    client.cookies.set("access_token", token_for(admin_user.id))


# ── The reason is required ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_ban_without_a_reason_is_refused(
    client: AsyncClient, admin_user, target_user, uid
):
    resp = await _ban(client, uid, None)

    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_a_ban_with_a_blank_reason_is_refused(
    client: AsyncClient, admin_user, target_user, uid
):
    """Whitespace is not a reason, and it must not pass validation as one."""
    resp = await _ban(client, uid, {"reason": "   "})

    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_an_over_long_reason_is_refused(
    client: AsyncClient, admin_user, target_user, uid
):
    resp = await _ban(client, uid, {"reason": "x" * 2000})

    assert resp.status_code == 422, resp.text


# ── The reason is stored and surfaced ────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_reason_is_stored_on_the_account(
    client: AsyncClient, db_session, admin_user, target_user, uid
):
    """It has to be readable later, which means it cannot exist only in a log."""
    resp = await _ban(client, uid, {"reason": "suspected fraud"})

    assert resp.status_code == 200, resp.text
    stored = await _row(db_session, uid)
    assert stored["ban_reason"] == "suspected fraud"
    assert stored["banned_at"] is not None


@pytest.mark.asyncio
async def test_the_banned_user_is_told_why(
    client: AsyncClient, admin_user, target_user, uid
):
    """They cannot appeal something they were not told.

    This is the whole point of capturing the reason: the login failure used to say
    only "Account is inactive", which is indistinguishable from an email problem,
    a password problem, or a bug.
    """
    await _ban(client, uid, {"reason": "suspected fraud"})

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": target_user.email, "password": "User!Pass1"},
    )

    assert resp.status_code == 403, resp.text
    assert "suspected fraud" in resp.text


@pytest.mark.asyncio
async def test_the_reason_reaches_the_audit_trail(
    client: AsyncClient, db_session, admin_user, target_user, uid
):
    """The trail is how this is explained to whoever asks in six months."""
    from sqlalchemy import select

    from app.models.audit import AdminAuditEvent

    await _ban(client, uid, {"reason": "chargeback fraud"})

    rows = (
        (
            await db_session.execute(
                select(AdminAuditEvent).where(
                    AdminAuditEvent.action == "user_banned",
                    AdminAuditEvent.target_id == uid,
                )
            )
        )
        .scalars()
        .all()
    )

    assert rows, "the ban was not audited at all"
    payload = rows[-1].payload or {}
    assert payload.get("reason") == "chargeback fraud"
    assert "chargeback fraud" in (rows[-1].summary or "")


# ── Unban clears it, so the state is unambiguous ─────────────────────────────


@pytest.mark.asyncio
async def test_unban_clears_the_reason(
    client: AsyncClient, db_session, admin_user, target_user, uid
):
    """An account that reads as banned because a stale reason is still attached
    is a support ticket waiting to happen."""
    await _ban(client, uid, {"reason": "suspected fraud"})
    await client.patch(f"/api/v1/admin/users/{uid}/unban")

    stored = await _row(db_session, uid)

    assert stored["ban_reason"] is None
    assert stored["banned_at"] is None
    assert stored["is_active"] is True


@pytest.mark.asyncio
async def test_after_an_unban_the_user_can_sign_in_again(
    client: AsyncClient, admin_user, target_user, uid
):
    """The end-to-end point: a ban is reversible, and saying so is the test."""
    await _ban(client, uid, {"reason": "suspected fraud"})
    await client.patch(f"/api/v1/admin/users/{uid}/unban")

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": target_user.email, "password": "User!Pass1"},
    )

    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_unban_records_its_own_note(
    client: AsyncClient, db_session, admin_user, target_user, uid
):
    """Reversing a decision is also a decision, and it needs the same record."""
    from sqlalchemy import select

    from app.models.audit import AdminAuditEvent

    await _ban(client, uid, {"reason": "suspected fraud"})
    resp = await client.patch(
        f"/api/v1/admin/users/{uid}/unban",
        json={"note": "appeal upheld, customer confirmed identity"},
    )

    assert resp.status_code == 200, resp.text
    rows = (
        (
            await db_session.execute(
                select(AdminAuditEvent).where(
                    AdminAuditEvent.action == "user_unbanned"
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows
    assert "appeal upheld" in (rows[-1].summary or "")


# ── Ordering, and the things that must still be true ─────────────────────────


@pytest.mark.asyncio
async def test_the_reason_does_not_change_why_orders_were_cancelled(
    client: AsyncClient, db_session, admin_user, test_user, test_market
):
    """A reason is metadata. The ban must still do the safety work it was written
    for, or a nicer dialog would have quietly cost us the fund release."""
    from sqlalchemy import select

    from app.models.order import Order

    # Field values match the shape the rest of the suite uses: lowercase
    # `side`/`order_type`/`status`, and `amount` rather than `quantity`.
    # Read every id as a plain string *now*, while still in async context.
    # `test_market.outcomes` is a lazy relationship: the commit below expires it,
    # and touching it afterwards is IO from sync context, which asyncpg refuses.
    outcome = next(o for o in test_market.outcomes if o.name.lower() == "yes")
    order_user_id = str(test_user.id)
    order_market_id = str(test_market.id)
    outcome_id = str(outcome.id)
    order = Order(
        user_id=order_user_id,
        market_id=order_market_id,
        outcome_id=outcome_id,
        side="buy",
        order_type="limit",
        amount=Decimal("10.0"),
        price=Decimal("0.5"),
        remaining_amount=Decimal("10.0"),
        status="pending",
    )
    db_session.add(order)
    await db_session.commit()
    order_id = str(order.id)

    resp = await _ban(client, str(test_user.id), {"reason": "abuse"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["cancelled_order_ids"], "the resting order was not released"

    db_session.expire_all()
    status = (
        await db_session.execute(select(Order.status).where(Order.id == order_id))
    ).scalar()
    assert status in ("cancelled", "filled", "partial_cancelled")


@pytest.mark.asyncio
async def test_a_non_admin_still_cannot_ban_with_a_reason(
    client: AsyncClient, test_user, target_user, uid
):
    """The body is not a way in. A reason makes no difference to authorisation."""
    from conftest import token_for

    client.cookies.set("access_token", token_for(test_user.id))

    resp = await _ban(client, uid, {"reason": "because I said so"})

    assert resp.status_code in (401, 403), resp.text


@pytest.mark.asyncio
async def test_a_malformed_user_id_is_still_a_422_not_a_crash(
    client: AsyncClient, admin_user
):
    """Guard ordering: the id must be parsed before it reaches the driver."""
    resp = await client.patch(
        "/api/v1/admin/users/not-a-uuid/ban", json={"reason": "suspected fraud"}
    )

    assert resp.status_code in (404, 422), resp.text


@pytest.mark.asyncio
async def test_two_admins_banning_in_sequence_keeps_the_latest_reason(
    client: AsyncClient, db_session, admin_user, target_user, uid
):
    """The most recent reason is the one on the account. A stale one showing is
    worse than none, because it reads as current."""
    await _ban(client, uid, {"reason": "first, mistaken"})
    await client.patch(f"/api/v1/admin/users/{uid}/unban")
    await _ban(client, uid, {"reason": "second, confirmed"})

    stored = await _row(db_session, uid)

    assert stored["ban_reason"] == "second, confirmed"


@pytest.mark.asyncio
async def test_banning_an_admin_is_refused_even_with_a_reason(
    client: AsyncClient, admin_user, db_session
):
    """Escalation guard, unchanged by the new field."""
    # `password_hash` is NOT NULL; omitting it makes this test fail on a database
    # constraint rather than on the escalation guard it is checking.
    from app.deps import hash_password

    other = User(
        email=f"admin2_{uuid.uuid4().hex[:8]}@example.com",
        username=f"admin2_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("Admin!Pass2"),
        is_admin=True,
        is_active=True,
        is_email_verified=True,
    )
    db_session.add(other)
    await db_session.commit()

    resp = await _ban(client, str(other.id), {"reason": "because I am an admin"})

    assert resp.status_code == 403, resp.text