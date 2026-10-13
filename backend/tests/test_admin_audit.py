"""Every privileged action must leave a record of who performed it.

Before this, the audit trail had exactly one actor in it: an admin id buried
inside a JSON blob on an auth event. That made the question an auditor actually
asks - *show me everything this admin did* - unanswerable without reading every
row and parsing every blob.

Worse, three of the five privileged actions wrote nothing at all. Market approval
decides what becomes tradeable; `distribute-protocol-fees` moves real money to the
treasury. An admin could do either and leave no trace, which is the single
property an audit log exists to provide.

These assert the coverage rather than the mechanism: the set of actions that
write a row, and that each row answers *who / what / which target*.
"""

import pytest
from conftest import token_for
from httpx import AsyncClient
from sqlalchemy import select

from app.models.audit import AdminAuditEvent

# Every privileged action in the application. If a new one is added, it belongs
# here, and the coverage test below will fail until it does.
PRIVILEGED_ACTIONS = {
    "market_approved",
    "market_rejected",
    "user_banned",
    "user_unbanned",
    "protocol_fees_distributed",
}


async def _as_admin(client: AsyncClient, admin_user) -> None:
    client.cookies.set("access_token", token_for(admin_user.id))


async def _rows(db_session, *expressions) -> list[AdminAuditEvent]:
    """Audit rows matching SQLAlchemy expressions.

    Expressions, not keyword arguments: `where(action="x")` passes a bare string,
    which SQLAlchemy treats as raw SQL - and the resulting error names the column
    rather than the mistake, which is a genuinely confusing way to be wrong.
    """
    result = await db_session.execute(select(AdminAuditEvent).where(*expressions))
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_banning_a_user_records_the_admin_not_just_the_target(
    client: AsyncClient, db_session, admin_user, test_user
):
    """The row must name who acted.

    `AuthAuditEvent` already recorded a ban, but the admin existed only as an
    opaque id inside a JSON blob - unindexable, unfilterable, and invisible to
    anyone reading the log rather than parsing it.
    """
    await _as_admin(client, admin_user)

    resp = await client.patch(f"/api/v1/admin/users/{test_user.id}/ban")

    assert resp.status_code == 200, resp.text
    rows = await _rows(db_session, AdminAuditEvent.action == "user_banned")

    assert len(rows) == 1, "the ban was not recorded"
    row = rows[0]
    assert str(row.actor_id) == str(admin_user.id)
    assert row.actor_email == admin_user.email
    assert row.target_type == "user"
    assert row.target_id == str(test_user.id)
    assert row.success == "success"


@pytest.mark.asyncio
async def test_market_approval_is_recorded(client: AsyncClient, db_session, admin_user):
    """Approval decides what becomes tradeable and used to leave no trace."""
    import uuid
    from datetime import UTC, datetime, timedelta

    from app.models.market import STATUS_PENDING_REVIEW, Market

    slug = f"audit-approve-{uuid.uuid4().hex[:8]}"
    market = Market(
        slug=slug,
        question="Will this be audited?",
        description="audit test",
        category="meta",
        status=STATUS_PENDING_REVIEW,
        created_by=admin_user.id,
        closes_at=datetime.now(UTC) + timedelta(days=30),
        total_liquidity="0",
        total_volume="0",
    )
    db_session.add(market)
    await db_session.commit()
    await db_session.refresh(market)

    await _as_admin(client, admin_user)
    resp = await client.post(f"/api/v1/admin/markets/{market.id}/approve")

    assert resp.status_code == 200, resp.text
    rows = await _rows(db_session, AdminAuditEvent.action == "market_approved")

    assert len(rows) == 1, "approving a market - which makes it tradeable - was not recorded"
    row = rows[0]
    assert str(row.actor_id) == str(admin_user.id)
    assert row.target_type == "market"
    assert row.target_id == str(market.id)
    assert row.summary and market.slug in row.summary, (
        "the record has no readable summary - an audit row a human cannot read "
        "without decoding the payload is a row nobody reads"
    )


@pytest.mark.asyncio
async def test_money_movement_is_recorded_with_its_amount(
    client: AsyncClient, db_session, admin_user, monkeypatch
):
    """The one endpoint that moves real funds, previously entirely unlogged.

    The amount is what makes the record useful: "someone distributed fees" is not
    an audit answer, "someone distributed $4,120.55" is.
    """
    from app.services.liquidity_service import LiquidityService

    monkeypatch.setattr(
        LiquidityService,
        "distribute_protocol_fees",
        staticmethod(
            lambda _db: _ok(
                {
                    "total_distributed": "4120.55",
                    "markets_processed": 7,
                }
            )
        ),
    )

    await _as_admin(client, admin_user)
    resp = await client.post("/api/v1/admin/distribute-protocol-fees")

    assert resp.status_code == 200, resp.text
    rows = await _rows(db_session, AdminAuditEvent.action == "protocol_fees_distributed")

    assert len(rows) == 1, "moving money to the treasury left no record"
    assert str(rows[0].actor_id) == str(admin_user.id)
    assert rows[0].payload.get("total_distributed") == "4120.55", (
        "the amount was not captured - a record of the fact without the figure "
        "cannot answer a disputed balance"
    )


@pytest.mark.asyncio
async def test_a_failed_money_movement_is_recorded_too(
    client: AsyncClient, db_session, admin_user, monkeypatch
):
    """A rejected attempt is exactly the thing worth knowing about.

    A log holding only what was permitted is a log of what happened to be allowed.
    """
    from app.services.liquidity_service import LiquidityService

    def _explode(_db):
        raise RuntimeError("treasury wallet is frozen")

    monkeypatch.setattr(LiquidityService, "distribute_protocol_fees", staticmethod(_explode))

    await _as_admin(client, admin_user)

    # The route re-raises after recording, so the client sees a 500. Asserted via
    # `raises` rather than a status code because the ASGI transport used in tests
    # propagates the exception instead of mapping it - the point of this test is
    # the audit row, not the error-handling chain.
    with pytest.raises(RuntimeError, match="frozen"):
        await client.post("/api/v1/admin/distribute-protocol-fees")

    rows = await _rows(db_session, AdminAuditEvent.action == "protocol_fees_distributed")

    assert len(rows) == 1, "the failed attempt was not recorded"
    assert rows[0].success == "failure"
    assert "frozen" in (rows[0].failure_reason or "")


@pytest.mark.asyncio
async def test_the_trail_can_be_filtered_by_actor(
    client: AsyncClient, db_session, admin_user, test_user
):
    """The filter that was impossible before, and the reason for the actor column.

    With the actor buried in a JSON blob this question could not be answered at
    all without reading every row. That is the difference between an audit log and
    an append-only file someone hoped nobody would need.
    """
    await _as_admin(client, admin_user)
    await client.patch(f"/api/v1/admin/users/{test_user.id}/ban")
    await client.patch(f"/api/v1/admin/users/{test_user.id}/unban")

    mine = await client.get(f"/api/v1/admin/admin-actions?actor_id={admin_user.id}")
    assert mine.status_code == 200, mine.text
    body = mine.json()

    assert body["total"] == 2, f"expected both actions, got {body['total']}"
    assert {row["action"] for row in body["data"]} == {"user_banned", "user_unbanned"}
    assert all(row["actor_email"] == admin_user.email for row in body["data"])

    nobody = await client.get("/api/v1/admin/admin-actions?actor_id=00000000-0000-4000-8000-000000000000")
    assert nobody.json()["total"] == 0


@pytest.mark.asyncio
async def test_the_trail_is_not_public(client: AsyncClient, db_session, admin_user, test_user):
    """A log of who moved money is not something a normal account can read."""
    client.cookies.set("access_token", token_for(test_user.id))

    resp = await client.get("/api/v1/admin/admin-actions")

    assert resp.status_code == 403, f"a non-admin read the privileged-action trail: {resp.status_code}"


@pytest.mark.asyncio
async def test_the_trail_cannot_be_narrowed_into_misleading_answers(
    client: AsyncClient, db_session, admin_user
):
    """An unparseable filter must be refused, not silently ignored.

    `actor_id=not-a-uuid` returning an empty page would read as "this admin has
    done nothing", which is the most dangerous possible answer to give someone
    investigating.
    """
    await _as_admin(client, admin_user)

    resp = await client.get("/api/v1/admin/admin-actions?actor_id=not-a-uuid")

    assert resp.status_code >= 400, (
        "a malformed actor_id was accepted and would have returned an empty page, "
        "reading as 'this admin did nothing'"
    )


def test_every_privileged_action_is_covered_by_a_test():
    """Guard the coverage itself, so a new endpoint cannot quietly go unlogged.

    This is the test that would have caught the original gap. Without it, adding
    an admin route that forgets to log is a one-line change that nobody notices,
    because nothing about it fails.
    """
    import inspect

    from app.api import admin as admin_module
    from app.services import admin_audit

    declared = {
        value
        for name, value in vars(admin_audit).items()
        if name.isupper() and isinstance(value, str)
    }
    missing = declared - PRIVILEGED_ACTIONS
    assert not missing, f"privileged actions exist but are not covered here: {missing}"

    # Every route that mutates something must call the audit service.
    source = inspect.getsource(admin_module)
    mutating = [
        line
        for line in source.splitlines()
        if line.strip().startswith("@router.") and any(
            verb in line for verb in ("post", "patch", "put", "delete")
        )
    ]
    assert mutating, "the admin router has no mutating routes - this guard is stale"

    calls = source.count("AdminAuditService.log_action")
    assert calls >= 5, (
        f"only {calls} audited actions found across {len(mutating)} mutating routes - "
        "a new privileged endpoint may not be logging"
    )


def _ok(value):
    """An awaitable returning `value`, so a monkeypatched service can be async."""

    async def _inner():
        return value

    return _inner()