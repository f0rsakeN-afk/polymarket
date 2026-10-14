"""The two privileged actions that were not privileged actions.

## Dispute adjudication

`POST /disputes/{id}/adjudicate` was admin-gated, and nothing else. An upheld
ruling resolves the market and queues settlement - it decides who gets paid - and
it had no step-up and no audit row.

It was missed because it lives in `api/disputes.py` rather than `api/admin.py`.
Worse, the test that claims every privileged action is audited reads
`PRIVILEGED_ACTIONS`, a list defined in the same module as the actions it claims
to cover - so it was *structurally incapable* of noticing an action elsewhere.
That is a gap in the guard, not just in the endpoint, and the guard is fixed
below as well as the endpoint.

## Reading a user's financial record

`GET /admin/users/{id}` returned profile fields only. An admin told "this user
says they lost money" had nothing to look at, while every answer was already in
the ledger. It now returns counts, a wallet, and derived findings - and because
"who looked at whose finances" is a question an operator has to answer, the read
is audited too.

A read needs no step-up - there is no irreversible action - but recording it is
not optional.
"""

import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest
from conftest import token_for
from httpx import AsyncClient
from sqlalchemy import select

from app.models.audit import AdminAuditEvent
from app.models.order import Order
from app.models.trade import Trade


async def _audit_rows(db_session, action: str):
    result = await db_session.execute(
        select(AdminAuditEvent).where(AdminAuditEvent.action == action)
    )
    return list(result.scalars().all())


async def _as_admin(client, user):
    client.cookies.set("access_token", token_for(user.id))


async def _open_dispute(db_session, user, market) -> str:
    from app.models.dispute import Dispute

    dispute = Dispute(
        market_id=market.id,
        user_id=user.id,
        evidence="The outcome was mispriced",
        status="open",
    )
    db_session.add(dispute)
    await db_session.commit()
    await db_session.refresh(dispute)
    return str(dispute.id)


# ── Dispute adjudication ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_ruling_with_the_wrong_password_is_refused(
    client: AsyncClient, db_session, admin_user, test_user, test_market
):
    """The guard, not the schema.

    This deliberately supplies a well-formed body with a *wrong* password. Omitting
    the field entirely is refused by Pydantic before the handler runs, so a test
    written that way passes even with `require_step_up` deleted - it would be
    asserting 422, which says nothing about whether the guard is present.
    """
    from app.models.dispute import Dispute

    dispute_id = await _open_dispute(db_session, test_user, test_market)
    await _as_admin(client, admin_user)

    with patch("app.workers.tasks.resolve_market.delay"):
        resp = await client.post(
            f"/api/v1/disputes/{dispute_id}/adjudicate",
            json={"ruling": "upheld", "password": "definitely-not-it"},
        )

    assert resp.status_code >= 400
    assert resp.json().get("error_code") == "STEP_UP_PASSWORD_INVALID"
    dispute = await db_session.get(Dispute, uuid.UUID(dispute_id))
    await db_session.refresh(dispute)
    assert dispute.status == "open", "the dispute was ruled despite a failed step-up"


@pytest.mark.asyncio
async def test_omitting_credentials_is_refused_by_the_schema(
    client: AsyncClient, db_session, admin_user, test_user, test_market
):
    """The contract also says so up front, which is a separate guarantee."""
    dispute_id = await _open_dispute(db_session, test_user, test_market)
    await _as_admin(client, admin_user)

    with patch("app.workers.tasks.resolve_market.delay"):
        resp = await client.post(
            f"/api/v1/disputes/{dispute_id}/adjudicate",
            json={"ruling": "upheld"},
        )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_a_failed_step_up_on_a_ruling_is_audited(
    client: AsyncClient, db_session, admin_user, test_user, test_market
):
    """An actor guessing at admin credentials is itself worth a row.

    This is the mirror of what `admin.py` does for fee distribution, and it was
    the piece missing from the first version of this change - the trail recorded
    successful rulings and nothing about the attempts against it.
    """
    dispute_id = await _open_dispute(db_session, test_user, test_market)
    await _as_admin(client, admin_user)

    resp = await client.post(
        f"/api/v1/disputes/{dispute_id}/adjudicate",
        json={"ruling": "upheld", "password": "definitely-not-it"},
    )
    assert resp.status_code >= 400

    rows = await _audit_rows(db_session, "step_up_failed")
    assert rows, "a failed step-up on a money-paying action was not recorded"
    assert rows[0].target_id == dispute_id


@pytest.mark.asyncio
async def test_a_ruling_is_written_to_the_admin_audit_trail(
    client: AsyncClient, db_session, admin_user, test_user, test_market
):
    """The gap. This endpoint was previously invisible.

    Without a row, a disputed settlement has no record of who ruled on it - and
    the whole point of the audit trail is that a question about money has an
    answer.
    """
    dispute_id = await _open_dispute(db_session, test_user, test_market)
    await _as_admin(client, admin_user)

    with patch("app.workers.tasks.resolve_market.delay"):
        resp = await client.post(
            f"/api/v1/disputes/{dispute_id}/adjudicate",
            json={"ruling": "dismissed", "password": "Admin!Pass1"},
        )
    assert resp.status_code == 200, resp.text

    rows = await _audit_rows(db_session, "dispute_adjudicated")
    assert rows, "a dispute ruling produced no audit row - it is invisible"
    assert rows[0].target_id == dispute_id, "the row does not name the dispute"
    assert rows[0].actor_id is not None, "the row does not name who ruled"
    assert (rows[0].payload or {}).get("ruling") == "dismissed"


@pytest.mark.asyncio
async def test_a_failed_ruling_is_audited_too(
    client: AsyncClient, db_session, admin_user, test_user, test_market
):
    """A log holding only what went through is a log of what was permitted."""
    await _as_admin(client, admin_user)

    resp = await client.post(
        f"/api/v1/disputes/{uuid.uuid4()}/adjudicate",
        json={"ruling": "dismissed", "password": "Admin!Pass1"},
    )
    assert resp.status_code == 404

    rows = await _audit_rows(db_session, "dispute_adjudicated")
    assert rows, "an attempt to rule on a dispute that does not exist was not recorded"
    assert rows[0].success == "failure"


@pytest.mark.asyncio
async def test_a_2fa_admin_cannot_rule_with_a_password_alone(
    client: AsyncClient, db_session, admin_user, test_user, test_market
):
    """The server decides the required factor, not the client."""
    dispute_id = await _open_dispute(db_session, test_user, test_market)
    admin_user.is_2fa_enabled = True
    admin_user.totp_secret_encrypted = "irrelevant-for-this-assertion"
    await db_session.commit()
    await _as_admin(client, admin_user)

    with patch("app.workers.tasks.resolve_market.delay"):
        resp = await client.post(
            f"/api/v1/disputes/{dispute_id}/adjudicate",
            json={"ruling": "upheld", "password": "Admin!Pass1"},
        )

    assert resp.status_code >= 400
    assert resp.json().get("error_code") == "STEP_UP_2FA_REQUIRED"


# ── Reading a user's financial record ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_detail_can_answer_a_balance_question(
    client: AsyncClient, db_session, admin_user, test_user, test_market
):
    """It used to return profile fields only, which answers nothing.

    The ledger to answer "where did my money go" already existed - `balance_after`
    on every transaction, `reference_id` pointing at the order that caused it.
    """
    db_session.add(
        Trade(
            user_id=test_user.id,
            market_id=test_market.id,
            outcome="Yes",
            side="buy",
            price=Decimal("0.4"),
            amount=Decimal(5),
        )
    )
    await db_session.commit()
    await _as_admin(client, admin_user)

    resp = await client.get(f"/api/v1/admin/users/{test_user.id}")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    assert data["wallet"]["balance"] is not None, "no wallet balance - cannot check a balance"
    assert data["counts"]["trades"] == 1
    assert "orders" in data["counts"] and "positions" in data["counts"]
    assert isinstance(data["findings"], list)


@pytest.mark.asyncio
async def test_user_detail_returns_rows_on_request_not_by_default(
    client: AsyncClient, db_session, admin_user, test_user, test_market
):
    """Counts by default, detail on request.

    A user with years of trades would make an unconditional dump unusable, and an
    unbounded response to an investigation query is how an endpoint becomes a
    denial-of-service lever an admin can aim at their own server.
    """
    db_session.add(
        Trade(
            user_id=test_user.id,
            market_id=test_market.id,
            outcome="Yes",
            side="buy",
            price=Decimal("0.4"),
            amount=Decimal(1),
        )
    )
    await db_session.commit()
    await _as_admin(client, admin_user)

    lean = (await client.get(f"/api/v1/admin/users/{test_user.id}")).json()["data"]
    assert "trades" not in lean, "every trade is dumped by default"

    detailed = (
        await client.get(f"/api/v1/admin/users/{test_user.id}?include=trades")
    ).json()["data"]
    assert len(detailed["trades"]) == 1
    assert detailed["trades"][0]["price"] == "0.40000000", (
        "money must serialise as a string - float() on money is how a balance "
        "reconciliation goes wrong"
    )


@pytest.mark.asyncio
async def test_detail_is_capped(client: AsyncClient, db_session, admin_user, test_user, test_market):
    db_session.add_all(
        [
            Trade(
                user_id=test_user.id,
                market_id=test_market.id,
                outcome="Yes",
                side="buy",
                price=Decimal("0.4"),
                amount=Decimal(1),
            )
            for _ in range(5)
        ]
    )
    await db_session.commit()
    await _as_admin(client, admin_user)

    resp = await client.get(f"/api/v1/admin/users/{test_user.id}?include=trades&limit=2")

    assert resp.status_code == 200
    assert len(resp.json()["data"]["trades"]) == 2


@pytest.mark.asyncio
async def test_user_detail_flags_an_open_order(
    client: AsyncClient, db_session, admin_user, test_user, test_market
):
    """Findings computed, not left for the admin to derive.

    A user holding funds locked in an order they cannot reach is a support case
    before it is a dispute, and nothing on the page would otherwise say so.
    """
    db_session.add(
        Order(
            user_id=test_user.id,
            market_id=test_market.id,
            outcome_id=test_market.outcomes[0].id,
            side="buy",
            order_type="limit",
            amount=Decimal(10),
            price=Decimal("0.4"),
            status="pending",
        )
    )
    await db_session.commit()
    await _as_admin(client, admin_user)

    data = (await client.get(f"/api/v1/admin/users/{test_user.id}")).json()["data"]

    assert data["counts"]["open_orders"] == 1
    assert "has_open_orders" in data["findings"]


@pytest.mark.asyncio
async def test_reading_a_financial_record_is_audited(
    client: AsyncClient, db_session, admin_user, test_user
):
    """"Who looked at whose finances" has to be answerable."""
    await _as_admin(client, admin_user)

    resp = await client.get(f"/api/v1/admin/users/{test_user.id}")
    assert resp.status_code == 200

    rows = await _audit_rows(db_session, "user_record_viewed")
    assert rows, "an admin pulled a user's financial record and nothing recorded it"
    assert rows[0].target_id == str(test_user.id)


@pytest.mark.asyncio
async def test_reading_a_financial_record_still_needs_admin(
    client: AsyncClient, test_user
):
    """Audit records a read; that must not make it available to everyone."""
    client.cookies.set("access_token", token_for(test_user.id))

    resp = await client.get(f"/api/v1/admin/users/{test_user.id}")

    assert resp.status_code in (401, 403)


# ── The guard itself ──────────────────────────────────────────────────────────


def test_the_adjudication_contract_still_demands_credentials():
    """The requirement is pinned in the schema, not only in the handler.

    The previous guard asserted that every name in `PRIVILEGED_ACTIONS` appeared in
    a test - a list defined in the same module as the actions it claimed to cover,
    which is why it never saw `api/disputes.py`. Checking the published schema
    instead catches the shape of the contract: if someone reverts
    `AdjudicateDisputeRequest` to plain `BaseModel`, the endpoint goes back to
    accepting a bare session, and every behavioural test here starts failing at
    422 instead of ever reaching the guard.
    """
    from app.app import app

    spec = app.openapi()
    schema_ref = (
        spec["paths"]["/api/v1/disputes/{dispute_id}/adjudicate"]["post"]
        .get("requestBody", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
    ).get("$ref", "")
    assert schema_ref, "the adjudication endpoint no longer declares a request body"

    properties = spec["components"]["schemas"][schema_ref.split("/")[-1]]["properties"]
    assert "password" in properties, (
        "the adjudication schema no longer requires credentials - a bare admin "
        "session could resolve a market and pay out"
    )
    assert "ruling" in properties


def test_the_adjudication_route_is_still_registered():
    """A coverage list naming an action is not evidence the action exists."""
    from app.app import app

    assert "/api/v1/disputes/{dispute_id}/adjudicate" in app.openapi()["paths"]
