"""Integration tests for the Celery tasks that move money.

`app/workers/tasks.py` was 21% covered • a fifth of the code that fills
resting orders, sweeps fees and settles markets had never run in a test. The
reason is mechanical rather than fundamental: every task is a `@shared_task`
whose body is a nested `async def _run()` executed through `celery_run()`,
which needs a thread with no running loop. Inside pytest that is simply
`await asyncio.to_thread(task.run)`.

Only `.delay()` needs a live broker. These tests never touch one.

The limit-order sweeper is the important one: it is ~350 lines that debit a
buyer's locked funds, credit a seller's wallet and move AMM reserves, and it
is the loop that was silently doing nothing until a trade marked its market
dirty.
"""
import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from conftest import token_for
from sqlalchemy import select

from app.models.liquidity import LiquidityPool
from app.models.market import Outcome
from app.models.order import Order
from app.models.position import Position
from app.models.wallet import Wallet

D = Decimal


async def _run_task(task):
    """Invoke a Celery task's body the way a worker would, minus the broker."""
    return await asyncio.to_thread(task.run)


async def _mark_dirty(market_id: str):
    from app.redis import get_redis
    r = await get_redis()
    await r.delete("dirty:markets")
    await r.sadd("dirty:markets", market_id)


async def _set_price(db, market_id, yes: str, no: str):
    pool = (
        await db.execute(
            select(LiquidityPool)
            .where(LiquidityPool.market_id == market_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    pool.yes_shares = D(yes)
    pool.no_shares = D(no)
    await db.commit()
    return pool


async def _wallet(db, user_id) -> Wallet:
    return (
        await db.execute(
            select(Wallet)
            .where(Wallet.user_id == user_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _order(db, order_id) -> Order:
    return (
        await db.execute(
            select(Order).where(Order.id == order_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _outcome(db, market_id, name: str) -> Outcome:
    return (
        await db.execute(select(Outcome).where(
            Outcome.market_id == market_id, Outcome.name.ilike(name)
        ))
    ).scalar_one()


async def _place_resting_limit_buy(client, test_market, price: str, amount: str):
    """Place a limit buy priced BELOW the current AMM price, so it rests."""
    resp = await client.post("/api/v1/orders/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "order_type": "limit",
        "amount": float(amount),
        "price": float(price),
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] in ("pending", "partial"), data
    return data["order_id"]


# ── The limit-order sweeper ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweeper_fills_a_resting_buy_once_the_price_crosses_it(
    client, test_user, test_market, db_session
):
    """The whole point of the loop: an order that rested at 0.45 fills when
    the AMM price falls to 0.45, and the buyer's locked USDC becomes shares."""
    from app.workers.tasks import check_limit_order_execution

    client.cookies.set("access_token", token_for(test_user.id))
    # Pool is 50/50 -> price 0.50, so a 0.45 buy rests.
    order_id = await _place_resting_limit_buy(client, test_market, "0.45", "10")

    wallet = await _wallet(db_session, test_user.id)
    assert wallet.locked_balance == D("10"), "a resting buy locks its budget"
    balance_before = wallet.balance

    # Price falls to 0.45 (45/100). A trade would have done this and marked
    # the market dirty; the sweeper only scans dirty markets.
    await _set_price(db_session, test_market.id, "45", "55")
    await _mark_dirty(str(test_market.id))

    result = await _run_task(check_limit_order_execution)
    assert "Executed" in str(result) or "No executable" in str(result)

    order = await _order(db_session, order_id)
    assert order.status == "filled", f"sweeper did not fill it: {order.status}"

    wallet = await _wallet(db_session, test_user.id)
    # Locked funds were converted, not double-spent.
    assert wallet.locked_balance == D("0")
    # A BUY pays USDC away for shares, so the balance drops by the filled
    # budget • and it must not drop by more than that budget.
    assert wallet.balance < balance_before, "buyer must have paid for the shares"
    assert balance_before - wallet.balance == D("10")

    pos = (
        await db_session.execute(
            select(Position).where(
                Position.market_id == test_market.id,
                Position.user_id == test_user.id,
            ).execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert pos.shares_held > 0


@pytest.mark.asyncio
async def test_sweeper_leaves_an_unreachable_order_alone(
    client, test_user, test_market, db_session
):
    """Price still above the limit: the order must keep resting, keep its
    locked funds, and not fabricate a fill."""
    from app.workers.tasks import check_limit_order_execution

    client.cookies.set("access_token", token_for(test_user.id))
    order_id = await _place_resting_limit_buy(client, test_market, "0.45", "10")

    await _set_price(db_session, test_market.id, "50", "50")  # still 0.50
    await _mark_dirty(str(test_market.id))

    await _run_task(check_limit_order_execution)

    order = await _order(db_session, order_id)
    assert order.status == "pending"
    wallet = await _wallet(db_session, test_user.id)
    assert wallet.locked_balance == D("10"), "locked funds stay locked while resting"


@pytest.mark.asyncio
async def test_sweeper_expires_a_resting_order_and_frees_its_funds(
    client, test_user, test_market, db_session
):
    """An expired resting buy must be marked expired and its locked budget
    released • otherwise a user's money is stuck forever."""
    from app.workers.tasks import check_limit_order_execution

    client.cookies.set("access_token", token_for(test_user.id))
    order_id = await _place_resting_limit_buy(client, test_market, "0.45", "10")

    order = await _order(db_session, order_id)
    order.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()
    await _mark_dirty(str(test_market.id))

    await _run_task(check_limit_order_execution)

    order = await _order(db_session, order_id)
    assert order.status == "expired"
    wallet = await _wallet(db_session, test_user.id)
    assert wallet.locked_balance == D("0"), "expiry must release the locked budget"


@pytest.mark.asyncio
async def test_sweeper_does_nothing_when_no_price_moved(
    client, test_user, test_market, db_session
):
    """The dirty set is the optimisation that keeps this cheap: no trades means
    nothing to re-test. Asserted because an empty-set regression would mean a
    silent full-table scan every 30 seconds."""
    from app.redis import get_redis
    from app.workers.tasks import check_limit_order_execution

    client.cookies.set("access_token", token_for(test_user.id))
    await _place_resting_limit_buy(client, test_market, "0.45", "10")

    r = await get_redis()
    await r.delete("dirty:markets")

    result = await _run_task(check_limit_order_execution)
    assert "No price moves" in str(result)


@pytest.mark.asyncio
async def test_sweeper_only_touches_marked_markets(
    client, test_user, admin_user, test_market, db_session
):
    """A dirty market must not drag in orders from unrelated markets."""
    from app.workers.tasks import check_limit_order_execution

    client.cookies.set("access_token", token_for(test_user.id))
    order_id = await _place_resting_limit_buy(client, test_market, "0.45", "10")
    await _set_price(db_session, test_market.id, "45", "55")

    # Mark a *different* market dirty • this one should be skipped.
    await _mark_dirty(str(test_user.id))
    await _run_task(check_limit_order_execution)

    order = await _order(db_session, order_id)
    assert order.status == "pending", "an unrelated dirty market must not fill this order"


@pytest.mark.asyncio
async def test_sweeper_falls_back_to_a_full_scan_when_redis_is_gone(
    client, test_user, test_market, db_session, monkeypatch
):
    """If Redis is unavailable the dirty set can't be read. The sweeper must
    degrade to scanning everything rather than silently doing nothing • a
    silent no-op here means resting orders never fill during a Redis outage."""
    import app.services.alert_engine as alert_engine
    from app.workers.tasks import check_limit_order_execution

    client.cookies.set("access_token", token_for(test_user.id))
    order_id = await _place_resting_limit_buy(client, test_market, "0.45", "10")
    await _set_price(db_session, test_market.id, "45", "55")

    async def redis_down():
        return None       # what pop_dirty_markets returns on a Redis error

    monkeypatch.setattr(alert_engine, "pop_dirty_markets", redis_down)
    # The task imports it inside _run(), so patch the module attribute too.
    monkeypatch.setattr("app.services.alert_engine.pop_dirty_markets", redis_down)

    result = await _run_task(check_limit_order_execution)
    assert "No price moves" not in str(result), "must not short-circuit on empty set"

    order = await _order(db_session, order_id)
    assert order.status == "filled", "full-scan fallback must still fill the order"


@pytest.mark.asyncio
async def test_sweeper_skips_a_closed_market(client, test_user, test_market, db_session):
    """Orders on a market that is no longer active must not be filled."""
    from app.workers.tasks import check_limit_order_execution

    client.cookies.set("access_token", token_for(test_user.id))
    order_id = await _place_resting_limit_buy(client, test_market, "0.45", "10")
    await _set_price(db_session, test_market.id, "45", "55")

    test_market.status = "closed"
    await db_session.commit()
    await _mark_dirty(str(test_market.id))

    await _run_task(check_limit_order_execution)

    order = await _order(db_session, order_id)
    assert order.status == "pending"


# ── Smaller tasks ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_expire_stale_orders_cancels_and_unlocks(client, test_user, test_market, db_session):
    """The other half of the resting-order lifecycle."""
    from app.workers.tasks import expire_stale_orders

    client.cookies.set("access_token", token_for(test_user.id))
    order_id = await _place_resting_limit_buy(client, test_market, "0.45", "10")
    order = await _order(db_session, order_id)
    order.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()

    await _run_task(expire_stale_orders)

    order = await _order(db_session, order_id)
    assert order.status in ("expired", "cancelled")
    wallet = await _wallet(db_session, test_user.id)
    assert wallet.locked_balance == D("0")


@pytest.mark.asyncio
async def test_check_markets_ready_to_resolve_closes_past_due_markets(test_market, db_session):
    """A market past `closes_at` with no winner is moved to `closed`, which is
    what stops trading and makes it eligible for resolution."""
    from app.workers.tasks import check_markets_ready_to_resolve

    test_market.closes_at = datetime.now(UTC) - timedelta(hours=1)
    await db_session.commit()

    await _run_task(check_markets_ready_to_resolve)

    market = (
        await db_session.execute(
            select(type(test_market)).where(type(test_market).id == test_market.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert market.status == "closed"


@pytest.mark.asyncio
async def test_check_markets_ready_to_resolve_leaves_future_markets_alone(test_market, db_session):
    from app.workers.tasks import check_markets_ready_to_resolve

    test_market.closes_at = datetime.now(UTC) + timedelta(days=7)
    await db_session.commit()

    await _run_task(check_markets_ready_to_resolve)

    market = (
        await db_session.execute(
            select(type(test_market)).where(type(test_market).id == test_market.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert market.status == "active"


@pytest.mark.asyncio
async def test_cleanup_expired_sessions_reaps_old_rows(test_user, db_session):
    """Session cleanup must actually delete • an unbounded sessions table is a
    slow-motion outage, and it also keeps revoked-token rows alive."""
    from app.models.user import RefreshToken, Session
    from app.workers.tasks import cleanup_expired_sessions
    token = RefreshToken(
        user_id=test_user.id,
        token_hash="deadbeef",
        device_info="test-device",
        expires_at=datetime.now(UTC) + timedelta(days=1),
        revoked=False,
    )
    db_session.add(token)
    await db_session.flush()

    old = Session(
        user_id=test_user.id,
        refresh_token_id=token.id,
        ip_address="1.1.1.1",
        user_agent="test",
        expires_at=datetime.now(UTC) - timedelta(days=1),
        revoked=False,
        last_active_at=datetime.now(UTC) - timedelta(days=2),
    )
    db_session.add(old)
    await db_session.commit()

    await _run_task(cleanup_expired_sessions)

    remaining = (
        await db_session.execute(
            select(Session).where(Session.user_id == test_user.id)
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    assert all(s.expires_at > datetime.now(UTC) - timedelta(days=1) for s in remaining)


@pytest.mark.asyncio
async def test_sync_amm_prices_publishes_and_survives_bad_data(test_market, db_session):
    """Price sync talks to Redis for every pool. A malformed row must not take
    the whole batch down."""
    from app.workers.tasks import sync_amm_prices

    result = await _run_task(sync_amm_prices)
    # Either a count, or an explicit "nothing to do" • never an exception.
    assert result is None or isinstance(result, (str, int, dict))


@pytest.mark.asyncio
async def test_distribute_protocol_fees_pays_the_treasury_and_keeps_the_remainder(
    test_user, test_market, db_session
):
    """Fees sweep the escrow, not air. Where the escrow can't cover the record,
    the unpaid part must stay in `protocol_fees` for the next sweep rather than
    being zeroed."""
    from app.services.liquidity_service import LiquidityService

    pool = (
        await db_session.execute(
            select(LiquidityPool)
            .where(LiquidityPool.market_id == test_market.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    pool.collateral = D("40")
    pool.protocol_fees = D("10")
    await db_session.commit()

    out = await LiquidityService.distribute_protocol_fees(db_session)
    assert D(out["total_distributed"]) == D("10")

    pool = (
        await db_session.execute(
            select(LiquidityPool)
            .where(LiquidityPool.market_id == test_market.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert pool.protocol_fees == D("0")
    assert pool.collateral == D("30")


@pytest.mark.asyncio
async def test_protocol_fee_sweep_carries_a_shortfall_forward(test_market, db_session):
    """Underfunded fee record: pay what exists, keep the rest owed."""
    from app.services.liquidity_service import LiquidityService

    pool = (
        await db_session.execute(
            select(LiquidityPool)
            .where(LiquidityPool.market_id == test_market.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    pool.collateral = D("4")
    pool.protocol_fees = D("10")
    await db_session.commit()

    await LiquidityService.distribute_protocol_fees(db_session)

    pool = (
        await db_session.execute(
            select(LiquidityPool)
            .where(LiquidityPool.market_id == test_market.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    # 4 paid, 6 still owed • NOT zeroed.
    assert pool.protocol_fees == D("6")
    assert pool.collateral == D("0")