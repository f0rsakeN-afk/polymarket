"""Overnight escrow invariant audit.

The nightly task re-checks every pool's escrow against what it still owes, so
a ledger imbalance surfaces while there is time to fix it • instead of at
resolution, where `settle_market` correctly refuses and the market is stuck.

Each test pins one invariant, and • just as importantly • that a healthy pool
produces *no* violation, so the audit can't cry wolf.
"""
import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.liquidity import LiquidityPool, LPShare
from app.models.market import Outcome
from app.models.position import Position
from app.services.escrow_audit import audit_escrow_invariants

D = Decimal


async def _pool(db, market_id) -> LiquidityPool:
    return (
        await db.execute(
            select(LiquidityPool)
            .where(LiquidityPool.market_id == market_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _outcome(db, market_id, name: str) -> Outcome:
    return (
        await db.execute(
            select(Outcome).where(
                Outcome.market_id == market_id, Outcome.name.ilike(name)
            )
        )
    ).scalar_one()


def _kinds(violations) -> set[str]:
    return {v.kind for v in violations}


# ── A healthy system produces nothing ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_healthy_pool_reports_no_violations(db_session, test_market):
    """The fixture market is 50/50 with 100 collateral and no positions, and
    the audit must be silent. An audit that always fires is an audit nobody
    reads."""
    pool = await _pool(db_session, test_market.id)
    pool.collateral = D("100")
    await db_session.commit()

    assert await audit_escrow_invariants(db_session) == []


@pytest.mark.asyncio
async def test_an_exactly_funded_pool_reports_no_violations(db_session, test_market):
    """Escrow == obligations is healthy: settlement pays it to zero and stops."""
    yes = await _outcome(db_session, test_market.id, "yes")
    no = await _outcome(db_session, test_market.id, "no")
    pool = await _pool(db_session, test_market.id)
    pool.collateral = D("40")
    pool.protocol_fees = D("0")
    await db_session.commit()

    db_session.add_all([
        Position(
            user_id=test_market.created_by, market_id=test_market.id,
            outcome_id=yes.id, shares_held=D("25"), average_price=D("0.5"),
        ),
        Position(
            user_id=test_market.created_by, market_id=test_market.id,
            outcome_id=no.id, shares_held=D("40"), average_price=D("0.5"),
        ),
    ])
    await db_session.commit()

    assert await audit_escrow_invariants(db_session) == []


# ── Invariant 1: escrow >= largest open side (+ fees) ─────────────────────────

@pytest.mark.asyncio
async def test_flags_an_escrow_below_the_largest_open_side(db_session, test_market):
    """Only ONE side is paid $1/share at resolution, so the worst case is the
    *larger* side • not the sum. 60 NO shares owed against 50 of escrow is a
    violation even though 60 < 60 + 60."""
    yes = await _outcome(db_session, test_market.id, "yes")
    no = await _outcome(db_session, test_market.id, "no")
    pool = await _pool(db_session, test_market.id)
    pool.collateral = D("50")
    await db_session.commit()

    db_session.add_all([
        Position(
            user_id=test_market.created_by, market_id=test_market.id,
            outcome_id=yes.id, shares_held=D("60"), average_price=D("0.5"),
        ),
        Position(
            user_id=test_market.created_by, market_id=test_market.id,
            outcome_id=no.id, shares_held=D("60"), average_price=D("0.5"),
        ),
    ])
    await db_session.commit()

    violations = await audit_escrow_invariants(db_session)
    assert "escrow_below_obligations" in _kinds(violations)

    v = next(v for v in violations if v.kind == "escrow_below_obligations")
    assert v.owed == D("60")          # the larger side, not both sides
    assert v.available == D("50")
    assert v.shortfall == D("10")
    assert v.market_slug == test_market.slug


@pytest.mark.asyncio
async def test_protocol_fees_count_toward_the_obligation(db_session, test_market):
    """Settlement pays winners *then* fees, so fees are part of what the escrow
    has to fund even when they fit on their own."""
    yes = await _outcome(db_session, test_market.id, "yes")
    pool = await _pool(db_session, test_market.id)
    pool.collateral = D("50")
    pool.protocol_fees = D("5")
    await db_session.commit()

    db_session.add(Position(
        user_id=test_market.created_by, market_id=test_market.id,
        outcome_id=yes.id, shares_held=D("48"), average_price=D("0.5"),
    ))
    await db_session.commit()

    violations = await audit_escrow_invariants(db_session)
    v = next(v for v in violations if v.kind == "escrow_below_obligations")
    assert v.owed == D("53")          # 48 winners + 5 fees
    assert v.shortfall == D("3")


@pytest.mark.asyncio
async def test_settled_positions_are_no_longer_a_claim(db_session, test_market):
    """A paid position must not keep the pool permanently 'underfunded' •
    otherwise every settled market would report a violation forever."""
    yes = await _outcome(db_session, test_market.id, "yes")
    pool = await _pool(db_session, test_market.id)
    pool.collateral = D("5")
    await db_session.commit()

    db_session.add(Position(
        user_id=test_market.created_by, market_id=test_market.id,
        outcome_id=yes.id, shares_held=D("500"), average_price=D("0.5"),
        settled_at=D("1700000000"),
    ))
    await db_session.commit()

    assert await audit_escrow_invariants(db_session) == []


# ── Invariants 2–5 ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_flags_fees_larger_than_the_escrow(db_session, test_market):
    pool = await _pool(db_session, test_market.id)
    pool.collateral = D("5")
    pool.protocol_fees = D("9")
    await db_session.commit()

    assert "fees_exceed_escrow" in _kinds(await audit_escrow_invariants(db_session))


@pytest.mark.asyncio
async def test_flags_lp_supply_drift(db_session, test_market):
    """Settlement refuses to redeem LP tokens when the rows exceed the
    recorded supply; the audit names the market a day earlier."""
    pool = await _pool(db_session, test_market.id)
    pool.lp_token_supply = D("100")
    await db_session.commit()

    db_session.add(LPShare(
        pool_id=pool.id, user_id=test_market.created_by,
        lp_tokens=D("120"), collateral_deposited=D("120"),
    ))
    await db_session.commit()

    violations = await audit_escrow_invariants(db_session)
    assert "lp_supply_drift" in _kinds(violations)
    v = next(v for v in violations if v.kind == "lp_supply_drift")
    assert v.owed == D("120") and v.available == D("100")


@pytest.mark.asyncio
async def test_flags_negative_collateral(db_session, test_market):
    pool = await _pool(db_session, test_market.id)
    pool.collateral = D("-1")
    await db_session.commit()

    assert "negative_collateral" in _kinds(await audit_escrow_invariants(db_session))


@pytest.mark.asyncio
async def test_flags_winners_owed_with_no_pool_at_all(db_session, test_market):
    """No pool means nothing can fund the winners • settlement refuses, so it
    must be caught here with the market named."""
    yes = await _outcome(db_session, test_market.id, "yes")
    pool = await _pool(db_session, test_market.id)
    await db_session.delete(pool)
    await db_session.commit()

    db_session.add(Position(
        user_id=test_market.created_by, market_id=test_market.id,
        outcome_id=yes.id, shares_held=D("30"), average_price=D("0.5"),
    ))
    await db_session.commit()

    violations = await audit_escrow_invariants(db_session)
    assert "pool_missing" in _kinds(violations)
    v = next(v for v in violations if v.kind == "pool_missing")
    assert v.owed == D("30")


# ── Operational behaviour ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_can_be_narrowed_to_one_market(db_session, test_market):
    """Ops needs to re-check a single market while investigating."""
    yes = await _outcome(db_session, test_market.id, "yes")
    pool = await _pool(db_session, test_market.id)
    pool.collateral = D("1")
    await db_session.commit()
    db_session.add(Position(
        user_id=test_market.created_by, market_id=test_market.id,
        outcome_id=yes.id, shares_held=D("30"), average_price=D("0.5"),
    ))
    await db_session.commit()

    # A different market id narrows the scan away from the violation.
    assert await audit_escrow_invariants(db_session, market_ids=[str(uuid4())]) == []
    assert await audit_escrow_invariants(db_session, market_ids=[str(test_market.id)])


@pytest.mark.asyncio
async def test_empty_database_is_clean(db_session):
    """No obligations at all: the audit returns immediately, without touching
    a pool query it doesn't need."""
    assert await audit_escrow_invariants(db_session) == []

@pytest.mark.asyncio
async def test_the_nightly_task_actually_runs_and_reports(db_session, test_market):
    """Guards the wiring, not the arithmetic.

    The audit is only useful if the beat entry point works: a typo in the
    deferred import inside `_run()`, or a `celery_run` problem, would fail at
    4am with nothing but a task-failure log, and the audit would look like it
    simply never finds anything.
    """
    from app.workers.tasks import audit_escrow_invariants

    # Clean database: the task must still run and report a count, not blow up.
    result = await asyncio.to_thread(audit_escrow_invariants.run)
    assert result is not None
    assert result["violations"] == 0

    # Now break a pool and prove the count moves.
    pool = await _pool(db_session, test_market.id)
    pool.collateral = D("-5")
    await db_session.commit()

    result = await asyncio.to_thread(audit_escrow_invariants.run)
    assert result["violations"] >= 1
    assert "negative_collateral" in result["by_kind"]
