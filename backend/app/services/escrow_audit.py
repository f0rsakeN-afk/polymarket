"""Overnight invariant audit over every pool's escrow.

Settlement pre-flights the escrow against what the pool owes and refuses to run
if it can't cover it (`EscrowShortfallError`). That turns a broken ledger into
a *resolution-time* failure • correct, but it surfaces once, at the worst
possible moment, and only to whoever happens to be watching.

This module runs the same arithmetic on a schedule so an imbalance surfaces
overnight, with the market named, while there is still time to fund or unwind
it. It reports; it never repairs. Auto-fixing a ledger you don't fully
understand is how a rounding bug becomes a fraud.

The checks mirror the pre-flight in `settle_market` exactly, so a clean audit
means the next settlement cannot fail for lack of escrow.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.liquidity import LiquidityPool, LPShare
from app.models.market import Market
from app.models.position import Position

logger = logging.getLogger("PredictX")

D = Decimal


@dataclass
class EscrowViolation:
    """One broken invariant, with enough context to act on it."""

    market_id: str
    market_slug: str
    kind: str
    detail: str
    owed: Decimal = D(0)
    available: Decimal = D(0)
    shortfall: Decimal = D(0)
    extra: dict = field(default_factory=dict)

    def as_log(self) -> dict:
        return {
            "event": "escrow_invariant_violation",
            "market_id": self.market_id,
            "market_slug": self.market_slug,
            "kind": self.kind,
            "detail": self.detail,
            "owed": float(self.owed),
            "available": float(self.available),
            "shortfall": float(self.shortfall),
            **self.extra,
        }


async def audit_escrow_invariants(
    db: AsyncSession,
    *,
    market_ids: list[str] | None = None,
) -> list[EscrowViolation]:
    """Check every pool that still has obligations. Returns the violations.

    Three aggregate queries total regardless of how many markets exist • the
    shape that keeps this cheap enough to run every night on a big table.
    """
    # 1. Shares still owed, per market per outcome. Unsettled is the right
    #    filter: a settled position has already been paid, so it is not a
    #    claim on the escrow any more.
    owed_rows = await db.execute(
        select(
            Position.market_id,
            Position.outcome_id,
            func.coalesce(func.sum(Position.shares_held), 0),
        )
        .where(Position.settled_at.is_(None))
        .group_by(Position.market_id, Position.outcome_id)
    )
    owed_by_market: dict[str, dict[str, Decimal]] = defaultdict(dict)
    for market_id, outcome_id, total in owed_rows.all():
        owed_by_market[str(market_id)][str(outcome_id)] = D(str(total))

    # 2. Live LP tokens per pool.
    lp_rows = await db.execute(
        select(LPShare.pool_id, func.coalesce(func.sum(LPShare.lp_tokens), 0))
        .where(LPShare.lp_tokens > 0)
        .group_by(LPShare.pool_id)
    )
    lp_by_pool = {str(pool_id): D(str(total)) for pool_id, total in lp_rows.all()}

    # Pools are scanned in one pass rather than filtered by an id list: a pool
    # can owe nothing to *positions* and still be worth checking, because it
    # may hold live LP tokens whose rows have drifted from `lp_token_supply`.
    # Filtering on "markets with unsettled positions" silently skipped exactly
    # that case • a market nobody has traded yet is all LP rows and no claims.
    pool_rows = await db.execute(
        select(LiquidityPool, Market.slug)
        .join(Market, Market.id == LiquidityPool.market_id)
    )
    pools = pool_rows.all()

    wanted = {str(m) for m in market_ids} if market_ids is not None else None
    if wanted is not None:
        pools = [
            (pool, slug) for pool, slug in pools
            if str(pool.market_id) in wanted
        ]

    violations: list[EscrowViolation] = []

    # Positions with no pool at all: winners would be owed money nothing can
    # fund. Settlement refuses this, so surface it rather than let a market
    # fail at resolution.
    pooled_markets = {str(pool.market_id) for pool, _slug in pools}
    for market_id, sides in owed_by_market.items():
        if sides and market_id not in pooled_markets:
            if wanted is not None and market_id not in wanted:
                continue
            violations.append(EscrowViolation(
                market_id=market_id,
                market_slug="(market row missing)",
                kind="pool_missing",
                detail="positions are owed to winners but the market has no "
                       "liquidity pool to fund them from",
                owed=sum(sides.values()),
                available=D(0),
                shortfall=sum(sides.values()),
                extra={"outcomes_with_claims": len(sides)},
            ))

    for pool, slug in pools:
        pool_id = str(pool.id)
        market_id = str(pool.market_id)
        collateral = D(str(pool.collateral or 0))
        fees = D(str(pool.protocol_fees or 0))
        slug = slug or "(unknown)"

        # ── Invariant 1 & 2: the escrow must cover the worst-case settlement.
        #
        # At resolution exactly ONE side is paid $1 per share, so the worst
        # case is the *larger* side's unsettled shares • plus the recorded
        # protocol fees, which settlement pays before LPs. This is precisely
        # the condition `settle_market` pre-flights, so if this is clean the
        # settlement cannot fail for lack of escrow.
        sides = owed_by_market.get(market_id, {})
        if sides:
            worst_outcome = max(sides, key=lambda k: sides[k])
            worst_side = sides[worst_outcome]
            required = worst_side + fees
            if required > collateral:
                violations.append(EscrowViolation(
                    market_id=market_id,
                    market_slug=slug,
                    kind="escrow_below_obligations",
                    detail="the escrow cannot fund settlement of the largest "
                           "open side plus protocol fees",
                    owed=required,
                    available=collateral,
                    shortfall=required - collateral,
                    extra={
                        "worst_side_outcome_id": worst_outcome,
                        "worst_side_shares": float(worst_side),
                        "protocol_fees": float(fees),
                        "total_shares_owed": float(sum(sides.values())),
                        "outcomes_with_claims": len(sides),
                    },
                ))

        # ── Invariant 3: fees are a sub-ledger INSIDE the escrow.
        if fees > collateral:
            violations.append(EscrowViolation(
                market_id=market_id,
                market_slug=slug,
                kind="fees_exceed_escrow",
                detail="recorded protocol fees exceed the escrow backing them",
                owed=fees,
                available=collateral,
                shortfall=fees - collateral,
            ))

        # ── Invariant 4: LP share rows must not exceed the recorded supply.
        # Settlement refuses on drift, so it belongs here with a market name.
        lp_total = lp_by_pool.get(pool_id, D(0))
        supply = D(str(pool.lp_token_supply or 0))
        if lp_total > supply:
            violations.append(EscrowViolation(
                market_id=market_id,
                market_slug=slug,
                kind="lp_supply_drift",
                detail="LP share rows total more tokens than lp_token_supply",
                owed=lp_total,
                available=supply,
                shortfall=lp_total - supply,
            ))

        # ── Invariant 5: the escrow is a balance, it cannot be negative.
        if collateral < 0:
            violations.append(EscrowViolation(
                market_id=market_id,
                market_slug=slug,
                kind="negative_collateral",
                detail="pool escrow is negative",
                owed=D(0),
                available=collateral,
                shortfall=-collateral,
            ))

    return violations


async def audit_and_report(db: AsyncSession, **kwargs) -> list[EscrowViolation]:
    """Run the audit, log every violation as a structured ERROR, return them.

    Deliberately loud: each line is machine-parseable (`event` +
    `kind` + market id) so it can be shipped straight to an alerting tool
    without parsing prose.
    """
    violations = await audit_escrow_invariants(db, **kwargs)
    for v in violations:
        logger.error(v.as_log())
    return violations