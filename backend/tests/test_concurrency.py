"""Integration tests for concurrent operations and race conditions (issue #96).

The services take explicit row locks in a fixed order (market -> pool -> wallet)
to serialize racing writers. These tests exercise that ordering under real
concurrency:

* two users placing orders on the same market simultaneously
* the same ``client_order_id`` submitted concurrently (idempotency under race)
* two LPs adding liquidity to the same pool simultaneously
* two admins resolving the same market simultaneously

Unlike the shared ``client`` fixture (which overrides ``get_db`` with one
session • serializing all requests), these tests use one client per request so
every request opens its own pooled session/connection and the handlers
genuinely interleave.
"""
import asyncio
import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest
from conftest import create_login_session, token_for
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.models.liquidity import LiquidityPool, LPShare
from app.models.order import Order
from app.models.wallet import Wallet


def _client() -> AsyncClient:
    """A fresh client with no get_db override • one session per request."""
    from app.app import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _make_user(db_session, tag: str):
    """Second participant with a funded wallet (test_user is the first)."""
    from app.deps import hash_password
    from app.models.user import User

    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"{tag}_{uid}@example.com",
        username=f"{tag}_{uid}",
        password_hash=hash_password("Conc!Pass1"),  # noqa: S106 -- test fixture password
        is_email_verified=True,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(Wallet(user_id=user.id, balance="1000.00", locked_balance="0", currency="USDC"))
    # Authenticated requests need a live session (tokens carry its `sid`).
    await create_login_session(db_session, user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _order_count(db_session, market_id) -> int:
    return (
        await db_session.execute(
            select(func.count()).select_from(Order).where(Order.market_id == market_id)
        )
    ).scalar_one()


def _reported_balance(resp) -> Decimal:
    return Decimal(str(resp.json()["data"]["wallet_balance"]))


# ── Concurrent order placement ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_orders_two_users(test_user, test_market, db_session):
    """Two users buying on the same market at once: both fill, wallets stay consistent."""
    market_id = test_market.id  # captured up front: refresh/expire would make later access async-unsafe
    other = await _make_user(db_session, "racer")
    user_ids = [test_user.id, other.id]

    async with _client() as client_a, _client() as client_b:
        client_a.cookies.set("access_token", token_for(test_user.id))
        client_b.cookies.set("access_token", token_for(other.id))

        resp_a, resp_b = await asyncio.gather(
            client_a.post("/api/v1/orders/", json={
                "market_id": str(test_market.id),
                "outcome": "yes",
                "side": "buy",
                "order_type": "market",
                "amount": 10.0,
            }),
            client_b.post("/api/v1/orders/", json={
                "market_id": str(test_market.id),
                "outcome": "no",
                "side": "buy",
                "order_type": "market",
                "amount": 10.0,
            }),
        )

    assert resp_a.status_code == 200, resp_a.text
    assert resp_b.status_code == 200, resp_b.text
    assert resp_a.json()["success"] is True
    assert resp_b.json()["success"] is True
    assert resp_a.json()["data"]["status"] in ("filled", "partial")
    assert resp_b.json()["data"]["status"] in ("filled", "partial")

    # Both orders were persisted • no lost update under the market/pool locks.
    assert await _order_count(db_session, market_id) == 2

    # populate_existing re-reads the rows the fixtures created • a plain select
    # would return those identity-mapped instances with pre-order balances.
    wallet_rows = (
        await db_session.execute(
            select(Wallet)
            .where(Wallet.user_id.in_(user_ids))
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    wallets = {w.user_id: w for w in wallet_rows}

    for user, resp in ((test_user, resp_a), (other, resp_b)):
        wallet = wallets[user.id]
        assert wallet.balance >= 0, "wallet balance went negative"
        assert wallet.locked_balance >= 0, "locked balance went negative"
        # Each response reports the balance after its own order • the final
        # committed balance must match the reported one exactly.
        assert wallet.balance == _reported_balance(resp), (
            f"stale wallet: db={wallet.balance} reported={_reported_balance(resp)}"
        )


@pytest.mark.asyncio
async def test_concurrent_same_client_order_id(test_user, test_market, db_session):
    """Race on idempotency: two submits of one client_order_id create ONE order."""
    client_order_id = f"conc-dup-{uuid.uuid4().hex[:8]}"
    payload = {
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "order_type": "market",
        "amount": 5.0,
        "client_order_id": client_order_id,
    }

    async with _client() as client:
        client.cookies.set("access_token", token_for(test_user.id))
        resp_1, resp_2 = await asyncio.gather(
            client.post("/api/v1/orders/", json=payload),
            client.post("/api/v1/orders/", json=payload),
        )

    # The market row lock serializes both requests: first fills, second replays.
    assert resp_1.status_code == 200, resp_1.text
    assert resp_2.status_code == 200, resp_2.text
    statuses = {r.json()["data"]["status"] for r in (resp_1, resp_2)}
    assert statuses == {"filled", "duplicate"}, statuses

    # Exactly one row despite two concurrent submissions.
    assert await _order_count(db_session, test_market.id) == 1
    order_ids = {r.json()["data"]["order_id"] for r in (resp_1, resp_2)}
    assert len(order_ids) == 1, "duplicate response must reference the original order"


@pytest.mark.asyncio
async def test_concurrent_orders_same_user(test_user, test_market, db_session):
    """Same user firing two orders at once: wallet serialized, never overdrawn."""
    async with _client() as client:
        client.cookies.set("access_token", token_for(test_user.id))
        payload = {
            "market_id": str(test_market.id),
            "outcome": "yes",
            "side": "buy",
            "order_type": "market",
            "amount": 10.0,
        }
        resp_1, resp_2 = await asyncio.gather(
            client.post("/api/v1/orders/", json=payload),
            client.post("/api/v1/orders/", json=payload),
        )

    assert resp_1.status_code == 200, resp_1.text
    assert resp_2.status_code == 200, resp_2.text
    assert await _order_count(db_session, test_market.id) == 2

    # populate_existing: the fixture's Wallet instance is in this session's
    # identity map, so a plain select would hand back the pre-order balance.
    wallet = (
        await db_session.execute(
            select(Wallet)
            .where(Wallet.user_id == test_user.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert wallet.balance >= 0, "concurrent orders overdrew the wallet"
    assert wallet.locked_balance >= 0
    # Balances strictly decrease with each fill, so the last-completed order
    # reports the lowest balance • it must equal the committed final balance.
    expected_final = min(_reported_balance(resp_1), _reported_balance(resp_2))
    assert wallet.balance == expected_final, (
        f"lost update: db={wallet.balance} expected={expected_final}"
    )


# ── Concurrent liquidity operations ───────────────────────────────────────────

async def _pool_state(db_session, market_id) -> tuple[Decimal, Decimal]:
    pool = (
        await db_session.execute(
            select(LiquidityPool)
            .where(LiquidityPool.market_id == market_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    lp_sum = (
        await db_session.execute(
            select(func.coalesce(func.sum(LPShare.lp_tokens), 0)).where(
                LPShare.pool_id == pool.id
            )
        )
    ).scalar_one()
    return pool.lp_token_supply, Decimal(lp_sum)


@pytest.mark.asyncio
async def test_concurrent_add_liquidity(test_user, test_market, db_session):
    """Two LPs depositing at once: token minting stays conserved."""
    market_id = test_market.id  # capture before anything can expire the instance
    other = await _make_user(db_session, "lp_racer")
    user_ids = [test_user.id, other.id]

    supply_before, shares_before = await _pool_state(db_session, market_id)

    async with _client() as client_a, _client() as client_b:
        client_a.cookies.set("access_token", token_for(test_user.id))
        client_b.cookies.set("access_token", token_for(other.id))
        resp_a, resp_b = await asyncio.gather(
            client_a.post(f"/api/v1/markets/{test_market.id}/liquidity", json={"amount": 25.0}),
            client_b.post(f"/api/v1/markets/{test_market.id}/liquidity", json={"amount": 25.0}),
        )

    assert resp_a.status_code == 200, resp_a.text
    assert resp_b.status_code == 200, resp_b.text

    db_session.expire_all()
    supply_after, shares_after = await _pool_state(db_session, market_id)

    # Tokens minted must equal the increase of the pool's supply • a race in
    # the mint accounting would break this delta conservation.
    assert supply_after - supply_before == shares_after - shares_before, (
        f"LP token drift: supply +{supply_after - supply_before}, "
        f"shares +{shares_after - shares_before}"
    )
    assert shares_after > shares_before, "both deposits should have minted shares"

    holders = (
        await db_session.execute(
            select(func.count()).select_from(LPShare).where(
                LPShare.user_id.in_(user_ids)
            )
        )
    ).scalar_one()
    assert holders == 2, "both LPs must hold a share position"

    wallet_rows = (
        await db_session.execute(
            select(Wallet)
            .where(Wallet.user_id.in_(user_ids))
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    assert len(wallet_rows) == 2
    for wallet in wallet_rows:
        assert wallet.balance >= 0
        assert wallet.balance < Decimal("1000.00"), "deposit should have debited the wallet"


# ── Concurrent market resolution ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_market_resolution(admin_user, test_market, db_session):
    """Two admins resolving at once: exactly one wins, the other is rejected."""
    outcome = next(o for o in test_market.outcomes if o.name == "Yes")
    outcome_id = str(outcome.id)  # refresh(test_market) expires the outcome rows
    payload = {"winning_outcome_id": outcome_id}

    async with _client() as client_a, _client() as client_b:
        client_a.cookies.set("access_token", token_for(admin_user.id))
        client_b.cookies.set("access_token", token_for(admin_user.id))
        with patch("app.api.markets.resolve_market.apply_async") as mock_enqueue:
            resp_a, resp_b = await asyncio.gather(
                client_a.post(f"/api/v1/markets/{test_market.slug}/resolve", json=payload),
                client_b.post(f"/api/v1/markets/{test_market.slug}/resolve", json=payload),
            )

    # The Redis SETNX lock, the enqueue dedup key, and the status guard each
    # independently prevent a double resolution. The endpoint now also takes a
    # row lock on the market (needed so the settlement worker can't read a
    # pre-commit status), which serialises these two requests: the loser
    # observes the winner's committed `resolving` state and reports it as a
    # validation error rather than racing into the Redis lock.
    winners = [r for r in (resp_a, resp_b) if r.status_code == 200]
    losers = [r for r in (resp_a, resp_b) if r.status_code != 200]
    assert len(winners) == 1, (
        f"exactly one resolve must win, got: "
        f"{[(r.status_code, r.text) for r in (resp_a, resp_b)]}"
    )
    assert len(losers) == 1
    assert losers[0].status_code in (400, 409, 422), losers[0].text
    assert mock_enqueue.call_count == 1, "settlement task must be enqueued exactly once"

    await db_session.refresh(test_market)
    assert test_market.status == "resolving"
    assert str(test_market.winning_outcome_id) == outcome_id
    assert test_market.resolved_at is not None
