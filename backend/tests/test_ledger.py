"""Single-entry escrow ledger + settlement tests.

Every dollar a wallet gains from a pool must be a dollar `pool.collateral`
lost, and every pool payout must be covered by collateral that actually went
in. These tests pin the invariant that used to be missing (§6.1 of
docs/trading-engine.md): buys, splits and deposits credit the escrow; sells,
merges, LP exits, fee sweeps, claims and settlement debit it • so settlement
can never mint money, and a market can never promise more than it holds.
"""
from decimal import Decimal
from uuid import uuid4

import pytest
from conftest import token_for
from httpx import AsyncClient
from sqlalchemy import select

from app.models.liquidity import EscrowShortfallError, LiquidityPool, LPShare
from app.models.market import Market
from app.models.position import Position
from app.models.user import User
from app.models.wallet import Wallet
from app.workers.tasks import settle_market

D = Decimal


def _pool(collateral: str = "100") -> LiquidityPool:
    return LiquidityPool(market_id=uuid4(), collateral=D(collateral))


async def _get_pool(db, market_id) -> LiquidityPool:
    # populate_existing: settlement runs in its own session, so the identity-
    # mapped copy here must be refreshed from the committed row, not returned
    # stale (and never via expire_all(), which turns every later attribute
    # access into implicit sync IO → MissingGreenlet).
    return (
        await db.execute(
            select(LiquidityPool)
            .where(LiquidityPool.market_id == market_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _balance(db, user_id) -> Decimal:
    wallet = (
        await db.execute(
            select(Wallet)
            .where(Wallet.user_id == user_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    return wallet.balance


# ── Unit: escrow helpers ──────────────────────────────────────────────────────

def test_credit_collateral_adds():
    pool = _pool("100")
    pool.credit_collateral(D("12.5"))
    assert pool.collateral == D("112.5")


def test_credit_collateral_rejects_negative():
    pool = _pool("100")
    with pytest.raises(ValueError):
        pool.credit_collateral(D("-1"))
    assert pool.collateral == D("100")


def test_debit_is_bounded_by_escrow():
    """The escrow can never go negative • it is a hard payout bound.

    There is no "pay what you can" mode any more: a caller that debits less
    than it records as paid destroys the difference. A shortfall raises, and
    `can_cover` is the read-only probe callers branch on instead.
    """
    pool = _pool("10")
    assert pool.can_cover(D("10")) is True
    assert pool.can_cover(D("10.00000001")) is False
    assert pool.debit_collateral(D("10")) == D("10")
    assert pool.collateral == D("0")
    with pytest.raises(EscrowShortfallError):
        pool.debit_collateral(D("5"))
    # The failed debit left the balance exactly where it was.
    assert pool.collateral == D("0")


def test_debit_never_leaves_a_partial_payment_behind():
    """Regression: the old `allow_shortfall` path returned the available cash
    and *mutated* the balance, so a caller that then recorded the obligation as
    settled had quietly destroyed the remainder. `min(owed, available)` is now
    the caller's job, and the unpaid part stays visible in their own ledger."""
    pool = _pool("10")
    owed = D("25")
    payable = min(owed, D("10"))
    assert pool.debit_collateral(payable) == D("10")
    assert pool.collateral == D("0")
    # `owed - payable` is still owed, and the caller still holds it.
    assert owed - payable == D("15")


def test_strict_debit_raises_and_leaves_escrow_intact():
    """Trading paths fail closed: a broken ledger rolls the trade back."""
    pool = _pool("10")
    with pytest.raises(EscrowShortfallError):
        pool.debit_collateral(D("11"))
    assert pool.collateral == D("10")


def test_debit_of_zero_is_a_noop():
    pool = _pool("10")
    assert pool.debit_collateral(D("0")) == D("0")
    assert pool.collateral == D("10")


# ── Split / merge ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_split_escrows_the_full_deposit_and_merge_releases_it(
    client: AsyncClient, test_user, test_market, db_session
):
    client.cookies.set("access_token", token_for(test_user.id))
    collateral_before = (await _get_pool(db_session, test_market.id)).collateral

    resp = await client.post("/api/v1/split-merge/split", json={
        "market_id": str(test_market.id), "amount": 20.0,
    })
    assert resp.status_code == 200, resp.text

    pool = await _get_pool(db_session, test_market.id)
    assert pool.collateral == collateral_before + D("20")
    # The 2% split fee is a claim *inside* the escrow, never extra money.
    assert pool.protocol_fees == D("0.4")
    assert pool.collateral >= pool.protocol_fees

    resp = await client.post("/api/v1/split-merge/merge", json={
        "market_id": str(test_market.id), "amount": 10.0,
    })
    assert resp.status_code == 200, resp.text

    pool = await _get_pool(db_session, test_market.id)
    # 10 shares in → 10 - 2% = 9.80 leaves; the fee stays behind, recorded.
    assert pool.collateral == collateral_before + D("20") - D("9.8")
    assert pool.protocol_fees == D("0.4") + D("0.2")
    assert pool.collateral >= pool.protocol_fees


# ── AMM legs ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_amm_buy_credits_and_sell_debits_escrow(
    client: AsyncClient, test_user, test_market, db_session
):
    """Wallet delta and collateral delta are equal and opposite on both legs."""
    client.cookies.set("access_token", token_for(test_user.id))

    c0 = (await _get_pool(db_session, test_market.id)).collateral
    w0 = await _balance(db_session, test_user.id)

    resp = await client.post("/api/v1/orders/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "order_type": "market",
        "amount": 10.0,
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "filled"

    c1 = (await _get_pool(db_session, test_market.id)).collateral
    w1 = await _balance(db_session, test_user.id)
    assert c1 == c0 + D("10")          # escrow received the whole spend
    assert w1 == w0 - D("10")          # …and the wallet paid exactly it

    resp = await client.post("/api/v1/orders/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "sell",
        "order_type": "market",
        "amount": 5.0,                 # SELL amounts are shares
    })
    assert resp.status_code == 200, resp.text

    c2 = (await _get_pool(db_session, test_market.id)).collateral
    w2 = await _balance(db_session, test_user.id)
    proceeds = w2 - w1
    assert proceeds > 0
    assert c2 == c1 - proceeds         # single-entry: proceeds came *out* of the escrow
    assert c2 > 0


# ── LP add / remove ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lp_exit_is_paid_out_of_the_escrow(
    client: AsyncClient, test_user, test_market, db_session
):
    client.cookies.set("access_token", token_for(test_user.id))

    c0 = (await _get_pool(db_session, test_market.id)).collateral
    w0 = await _balance(db_session, test_user.id)

    resp = await client.post(f"/api/v1/markets/{test_market.id}/liquidity", json={"amount": 50.0})
    assert resp.status_code == 200, resp.text
    c1 = (await _get_pool(db_session, test_market.id)).collateral
    assert c1 == c0 + D("50")

    pos = await client.get(f"/api/v1/markets/{test_market.id}/liquidity")
    lp_tokens = pos.json()["data"]["lp_tokens"]      # strings serialise in JSON
    resp = await client.request(
        "DELETE", f"/api/v1/markets/{test_market.id}/liquidity",
        json={"lp_tokens": lp_tokens},
    )
    assert resp.status_code == 200, resp.text

    c2 = (await _get_pool(db_session, test_market.id)).collateral
    w2 = await _balance(db_session, test_user.id)
    payout = w2 - w0 + D("50")          # wallet moved −50 on add, +payout on remove
    assert payout > 0
    assert c1 - c2 == payout           # escrow funded the exit
    assert c2 >= 0


@pytest.mark.asyncio
async def test_lp_exit_never_exceeds_escrow_after_imbalanced_trading(
    client: AsyncClient, test_user, test_market, db_session
):
    """The old formula paid `yes_redeemed + no_redeemed` (both sides at $1),
    which could exceed the collateral actually held once trading skewed the
    reserves. The escrow is the bound."""
    client.cookies.set("access_token", token_for(test_user.id))

    # Skew the pool: buy YES so the reserve ratio is no longer 50/50.
    resp = await client.post("/api/v1/orders/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "order_type": "market",
        "amount": 40.0,
    })
    assert resp.status_code == 200, resp.text

    resp = await client.post(f"/api/v1/markets/{test_market.id}/liquidity", json={"amount": 30.0})
    assert resp.status_code == 200, resp.text

    pool = await _get_pool(db_session, test_market.id)
    collateral = pool.collateral
    supply = pool.lp_token_supply
    reserve_sum = pool.yes_shares + pool.no_shares
    # The fixture pool has supply with no holder, so this user owns a slice.
    pos = await client.get(f"/api/v1/markets/{test_market.id}/liquidity")
    lp_tokens = D(pos.json()["data"]["lp_tokens"])   # API returns strings

    w0 = await _balance(db_session, test_user.id)
    resp = await client.request(
        "DELETE", f"/api/v1/markets/{test_market.id}/liquidity",
        json={"lp_tokens": str(lp_tokens)},
    )
    assert resp.status_code == 200, resp.text

    w1 = await _balance(db_session, test_user.id)
    payout = w1 - w0
    frac = lp_tokens / supply
    assert payout > 0
    # Bounded by the pro-rata escrow slice • never the inflated reserve sum
    # the old `yes_redeemed + no_redeemed` formula would have paid out.
    assert payout <= collateral * frac + D("0.000001")
    assert payout < reserve_sum * frac
    assert (await _get_pool(db_session, test_market.id)).collateral >= 0


# ── Settlement ────────────────────────────────────────────────────────────────

async def _seed_settlement(db, test_market, test_user, admin_user, yes, no,
                           winner_shares="40", loser_shares="30",
                           lp_tokens="100", fees="5"):
    """Positions for a winner and a loser, half the LP supply held by admin,
    five dollars of recorded protocol fees. Mirrors what the API leaves
    behind before the worker runs (status `resolving` + outcome recorded)."""
    pool = await _get_pool(db, test_market.id)
    db.add_all([
        Position(
            user_id=test_user.id, market_id=test_market.id, outcome_id=yes.id,
            shares_held=D(winner_shares), average_price=D("0.5"), realized_pnl=D(0),
        ),
        Position(
            user_id=admin_user.id, market_id=test_market.id, outcome_id=no.id,
            shares_held=D(loser_shares), average_price=D("0.5"), realized_pnl=D(0),
        ),
    ])
    db.add(LPShare(
        pool_id=pool.id, user_id=admin_user.id,
        lp_tokens=D(lp_tokens), collateral_deposited=D("50"),
    ))
    pool.protocol_fees = D(fees)
    test_market.status = "resolving"
    test_market.winning_outcome_id = yes.id
    await db.commit()
    return pool


@pytest.mark.asyncio
async def test_settlement_pays_everyone_out_of_the_escrow(
    client: AsyncClient, test_user, admin_user, test_market, db_session
):
    yes = next(o for o in test_market.outcomes if o.name.lower() == "yes")
    no = next(o for o in test_market.outcomes if o.name.lower() == "no")
    await _seed_settlement(db_session, test_market, test_user, admin_user, yes, no)

    user_before = await _balance(db_session, test_user.id)
    admin_before = await _balance(db_session, admin_user.id)
    collateral_before = (await _get_pool(db_session, test_market.id)).collateral  # 100

    result = await settle_market(str(test_market.id), str(yes.id), "test-task")

    assert "Settled market" in result, result

    pool = await _get_pool(db_session, test_market.id)
    user_after = await _balance(db_session, test_user.id)
    admin_after = await _balance(db_session, admin_user.id)

    # Winner is paid 40 …
    assert user_after - user_before == D("40")
    # … loser is paid nothing, but receives the LP slice: 100/200 of the
    # residual after winners (40) and fees (5) → 55 / 2 = 27.5
    assert admin_after - admin_before == D("27.5")

    # Treasury got the recorded fees, out of the same escrow.
    treasury = (
        await db_session.execute(
            select(Wallet)
            .join(User, Wallet.user_id == User.id)
            .where(User.is_system.is_(True))
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert treasury.balance == D("5")

    # Escrow drained by exactly what was promised: 40 + 5 + 27.5 = 72.5
    assert collateral_before - pool.collateral == D("72.5")
    assert pool.collateral == D("27.5")
    assert pool.collateral >= 0
    assert pool.protocol_fees == D(0)

    # The market flipped to resolved so claim_winnings can also pay out.
    await db_session.refresh(test_market, ["status"])
    assert test_market.status == "resolved"
    pos_rows = (
        await db_session.execute(
            select(Position)
            .where(Position.market_id == test_market.id)
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    assert all(p.settled_at is not None for p in pos_rows)


@pytest.mark.asyncio
async def test_settlement_is_idempotent(
    client: AsyncClient, test_user, admin_user, test_market, db_session
):
    yes = next(o for o in test_market.outcomes if o.name.lower() == "yes")
    no = next(o for o in test_market.outcomes if o.name.lower() == "no")
    await _seed_settlement(db_session, test_market, test_user, admin_user, yes, no)

    assert "Settled market" in await settle_market(str(test_market.id), str(yes.id), "t1")
    first = {
        "user": await _balance(db_session, test_user.id),
        "admin": await _balance(db_session, admin_user.id),
        "collateral": (await _get_pool(db_session, test_market.id)).collateral,
    }

    # Redelivery: the finished-marker short-circuits before any write.
    again = await settle_market(str(test_market.id), str(yes.id), "t2")
    assert "already settled" in again
    assert await _balance(db_session, test_user.id) == first["user"]
    assert await _balance(db_session, admin_user.id) == first["admin"]
    assert (await _get_pool(db_session, test_market.id)).collateral == first["collateral"]


@pytest.mark.asyncio
async def test_settlement_refuses_a_stale_outcome(
    client: AsyncClient, test_user, admin_user, test_market, db_session
):
    yes = next(o for o in test_market.outcomes if o.name.lower() == "yes")
    no = next(o for o in test_market.outcomes if o.name.lower() == "no")
    await _seed_settlement(db_session, test_market, test_user, admin_user, yes, no)

    user_before = await _balance(db_session, test_user.id)

    # Market was re-resolved to NO; a stale task still says YES.
    result = await settle_market(str(test_market.id), str(no.id), "stale")
    assert "mismatch" in result, result

    assert await _balance(db_session, test_user.id) == user_before
    await db_session.refresh(test_market, ["status"])
    assert test_market.status == "resolving"  # untouched • no partial settle


@pytest.mark.asyncio
async def test_settlement_refuses_rather_than_underpaying_a_winner(
    client: AsyncClient, test_user, admin_user, test_market, db_session
):
    """Underfunded escrow aborts the whole settlement.

    This test used to assert the opposite: that a winner owed $400 was paid the
    $50 the escrow held, the residual went to LPs, and the market settled. That
    "capping" *is* the bug • the unpaid $350 was then stamped `settled_at`,
    so it was owed to nobody and claimable by nobody. Refusing keeps the whole
    $400 claimable, which is the only outcome that loses nothing.
    """
    yes = next(o for o in test_market.outcomes if o.name.lower() == "yes")
    no = next(o for o in test_market.outcomes if o.name.lower() == "no")
    pool = await _seed_settlement(
        db_session, test_market, test_user, admin_user, yes, no,
        winner_shares="400", fees="0",
    )
    pool.collateral = D("50")   # promises 400, holds 50
    await db_session.commit()

    user_id, admin_id, market_id = test_user.id, admin_user.id, test_market.id
    user_before = await _balance(db_session, user_id)
    admin_before = await _balance(db_session, admin_id)

    with pytest.raises(EscrowShortfallError):
        await settle_market(str(market_id), str(yes.id), "t1")

    await db_session.rollback()
    # Nobody was paid • not the winner, not the LP.
    assert await _balance(db_session, user_id) == user_before
    assert await _balance(db_session, admin_id) == admin_before
    # The escrow is untouched: still a hard bound, never negative.
    assert (await _get_pool(db_session, market_id)).collateral == D("50")


# ── Claim endpoint (manual payout path) ───────────────────────────────────────

@pytest.mark.asyncio
async def test_claim_winnings_debits_the_escrow(
    client: AsyncClient, test_user, test_market, db_session
):
    yes = next(o for o in test_market.outcomes if o.name.lower() == "yes")
    db_session.add(Position(
        user_id=test_user.id, market_id=test_market.id, outcome_id=yes.id,
        shares_held=D("40"), average_price=D("0.5"), realized_pnl=D(0),
    ))
    test_market.status = "resolved"
    test_market.winning_outcome_id = yes.id
    await db_session.commit()

    c0 = (await _get_pool(db_session, test_market.id)).collateral
    w0 = await _balance(db_session, test_user.id)

    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.post(f"/api/v1/markets/{test_market.slug}/claim")
    assert resp.status_code == 200, resp.text

    assert (await _balance(db_session, test_user.id)) == w0 + D("40")
    assert (await _get_pool(db_session, test_market.id)).collateral == c0 - D("40")


@pytest.mark.asyncio
async def test_claim_refuses_to_pay_an_unfunded_escrow(
    client: AsyncClient, test_user, test_market, db_session
):
    yes = next(o for o in test_market.outcomes if o.name.lower() == "yes")
    pos = Position(
        user_id=test_user.id, market_id=test_market.id, outcome_id=yes.id,
        shares_held=D("40"), average_price=D("0.5"), realized_pnl=D(0),
    )
    db_session.add(pos)
    test_market.status = "resolved"
    test_market.winning_outcome_id = yes.id
    pool = await _get_pool(db_session, test_market.id)
    pool.collateral = D("10")
    await db_session.commit()

    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.post(f"/api/v1/markets/{test_market.slug}/claim")
    assert resp.status_code == 422, resp.text

    # Snapshot ids first: rollback expires every instance in the session, and
    # touching an expired attribute outside greenlet context raises.
    market_id, user_id = test_market.id, test_user.id
    await db_session.rollback()
    # Nothing was conjured: position still claimable, wallet untouched,
    # escrow unchanged.
    pos_after = (
        await db_session.execute(
            select(Position)
            .where(Position.market_id == market_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert pos_after.settled_at is None
    assert await _balance(db_session, user_id) == D(1000)
    assert (await _get_pool(db_session, market_id)).collateral == D("10")


# ── The bug this section exists for ───────────────────────────────────────────
#
# Settlement used to pay each winner with `allow_shortfall=True`, then stamp
# `settled_at` on every position regardless. An underfunded escrow therefore
# paid the first winners in full, gave the last one whatever was left, and
# marked everybody settled • so the remainder was owed to nobody and reachable
# by nobody. It also had a `pool is not None` guard that *skipped the debit
# entirely* and credited the wallet anyway: money from nothing.
#
# Both are invariant violations, and a shortfall can only be caused by one, so
# the correct response is to abort the settlement rather than absorb it.

@pytest.mark.asyncio
async def test_settlement_refuses_to_run_on_an_underfunded_escrow(
    client: AsyncClient, test_user, admin_user, test_market, db_session
):
    """An escrow that cannot cover winners + fees must abort the whole settle.

    Nothing is paid, nothing is marked settled, and the market is not marked
    resolved • so the position stays claimable and a later top-up (or retry)
    can settle it in full. Nothing is lost.
    """
    yes = next(o for o in test_market.outcomes if o.name.lower() == "yes")
    no = next(o for o in test_market.outcomes if o.name.lower() == "no")
    pool = await _seed_settlement(
        db_session, test_market, test_user, admin_user, yes, no,
        winner_shares="40", fees="5",
    )
    # Drain the escrow below what settlement owes (45), leaving 10.
    pool.collateral = D("10")
    await db_session.commit()

    market_id, user_id = test_market.id, test_user.id
    user_before = await _balance(db_session, user_id)

    with pytest.raises(EscrowShortfallError):
        await settle_market(str(market_id), str(yes.id), "short-task")

    await db_session.rollback()
    # No money moved …
    assert await _balance(db_session, user_id) == user_before
    # … the escrow is untouched …
    assert (await _get_pool(db_session, market_id)).collateral == D("10")
    # … the fee record is not silently zeroed …
    assert (await _get_pool(db_session, market_id)).protocol_fees == D("5")
    # … and the position is still open, so it remains claimable.
    pos = (
        await db_session.execute(
            select(Position)
            .where(Position.market_id == market_id, Position.user_id == user_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert pos.settled_at is None
    assert pos.shares_held == D("40")

    # The market is NOT resolved, so the retry/top-up path still works and
    # the winner can still self-serve via the claim endpoint.
    market = (
        await db_session.execute(
            select(Market).where(Market.id == market_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert market.status == "resolving"


@pytest.mark.asyncio
async def test_settlement_never_mints_money_when_the_pool_row_is_missing(
    db_session, test_user, admin_user, test_market
):
    """`pool is not None` used to guard the debit, so with no pool the wallet
    was credited in full with nothing behind it. Now it raises."""
    yes = next(o for o in test_market.outcomes if o.name.lower() == "yes")
    no = next(o for o in test_market.outcomes if o.name.lower() == "no")
    await _seed_settlement(
        db_session, test_market, test_user, admin_user, yes, no,
        winner_shares="40", fees="0", lp_tokens="0",
    )
    pool = await _get_pool(db_session, test_market.id)
    await db_session.delete(pool)
    await db_session.commit()

    market_id, user_id = test_market.id, test_user.id
    before = await _balance(db_session, user_id)
    with pytest.raises(EscrowShortfallError):
        await settle_market(str(market_id), str(yes.id), "no-pool")
    await db_session.rollback()
    assert await _balance(db_session, user_id) == before


@pytest.mark.asyncio
async def test_escrow_exactly_covering_the_obligation_settles(
    db_session, test_user, admin_user, test_market
):
    """The boundary must not fail: escrow == winners + fees settles in full,
    and the LP residual is exactly zero rather than a rounding crumb."""
    yes = next(o for o in test_market.outcomes if o.name.lower() == "yes")
    no = next(o for o in test_market.outcomes if o.name.lower() == "no")
    pool = await _seed_settlement(
        db_session, test_market, test_user, admin_user, yes, no,
        winner_shares="40", fees="10", lp_tokens="0",
    )
    pool.collateral = D("50")          # exactly 40 winners + 10 fees
    await db_session.commit()

    market_id, user_id = test_market.id, test_user.id
    before = await _balance(db_session, user_id)
    result = await settle_market(str(market_id), str(yes.id), "exact")
    assert "Settled market" in result, result

    after_pool = await _get_pool(db_session, market_id)
    assert after_pool.collateral == D("0")        # every dollar accounted for
    assert await _balance(db_session, user_id) - before == D("40")


@pytest.mark.asyncio
async def test_winner_can_claim_while_the_market_is_still_resolving(
    client: AsyncClient, test_user, test_market, db_session
):
    """If settlement refuses (underfunded escrow, worker down, retry pending),
    the winner must not be locked out of money they already won.

    Both callers that record a winning outcome commit it together with the
    move out of "active", so a `resolving` market has a decided outcome. Claim
    stays all-or-nothing out of the escrow and takes the same Pool → Position →
    Wallet locks as settlement, so it can never double-pay a concurrent settle.
    """
    yes = next(o for o in test_market.outcomes if o.name.lower() == "yes")
    db_session.add(Position(
        user_id=test_user.id, market_id=test_market.id, outcome_id=yes.id,
        shares_held=D("12"), average_price=D("0.5"), realized_pnl=D(0),
    ))
    pool = await _get_pool(db_session, test_market.id)
    pool.collateral = D("30")
    test_market.status = "resolving"
    test_market.winning_outcome_id = yes.id
    await db_session.commit()

    client.cookies.set("access_token", token_for(test_user.id))
    before = await _balance(db_session, test_user.id)

    resp = await client.post(f"/api/v1/markets/{test_market.slug}/claim")
    assert resp.status_code == 200, resp.text
    assert D(resp.json()["data"]["claimed"]) == D("12")

    assert await _balance(db_session, test_user.id) - before == D("12")
    assert (await _get_pool(db_session, test_market.id)).collateral == D("18")
