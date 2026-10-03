"""Single-entry escrow ledger + settlement tests.

Every dollar a wallet gains from a pool must be a dollar `pool.collateral`
lost, and every pool payout must be covered by collateral that actually went
in. These tests pin the invariant that used to be missing (§6.1 of
docs/trading-engine.md): buys, splits and deposits credit the escrow; sells,
merges, LP exits, fee sweeps, claims and settlement debit it — so settlement
can never mint money, and a market can never promise more than it holds.
"""
from decimal import Decimal
from uuid import uuid4

import pytest
from conftest import token_for
from httpx import AsyncClient
from sqlalchemy import select

from app.models.liquidity import LiquidityPool, LPShare
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
    """The escrow can never go negative — it is a hard payout bound."""
    pool = _pool("10")
    assert pool.debit_collateral(D("25"), allow_shortfall=True) == D("10")
    assert pool.collateral == D("0")
    assert pool.debit_collateral(D("5"), allow_shortfall=True) == D("0")


def test_strict_debit_raises_and_leaves_escrow_intact():
    """Trading paths fail closed: a broken ledger rolls the trade back."""
    pool = _pool("10")
    with pytest.raises(ValueError):
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
    # Bounded by the pro-rata escrow slice — never the inflated reserve sum
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
    assert test_market.status == "resolving"  # untouched — no partial settle


@pytest.mark.asyncio
async def test_settlement_never_pays_more_than_the_escrow_holds(
    client: AsyncClient, test_user, admin_user, test_market, db_session
):
    """Underfunded escrow: winners are capped at what is backed, LPs take the
    residual (zero), and collateral lands on exactly 0 — never negative."""
    yes = next(o for o in test_market.outcomes if o.name.lower() == "yes")
    no = next(o for o in test_market.outcomes if o.name.lower() == "no")
    pool = await _seed_settlement(
        db_session, test_market, test_user, admin_user, yes, no,
        winner_shares="400", fees="0",
    )
    pool.collateral = D("50")   # promises 400, holds 50
    await db_session.commit()

    user_before = await _balance(db_session, test_user.id)
    admin_before = await _balance(db_session, admin_user.id)

    assert "Settled market" in await settle_market(str(test_market.id), str(yes.id), "t1")

    pool = await _get_pool(db_session, test_market.id)
    # The escrow is a hard bound: 50 was owed-and-paid, 350 was owed-and
    # refused, and the residual (0) went to LPs. Never below zero.
    assert pool.collateral == D(0)
    assert pool.collateral >= 0
    assert await _balance(db_session, test_user.id) == user_before + D("50")
    # LPs are last in line and get nothing when the escrow is empty.
    assert await _balance(db_session, admin_user.id) == admin_before


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
