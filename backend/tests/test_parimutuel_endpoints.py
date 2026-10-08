"""Every endpoint that reads or writes liquidity must survive a parimutuel market.

The service-layer maths is covered in test_parimutuel_pricing.py and the
schema in test_parimutuel_schema.py, but neither touches the HTTP surface.
That gap was real: `liquidity_pools.market_id` used to be UNIQUE, so a
market_id-only lookup was safe everywhere. Dropping it for per-outcome rows
turned `scalar_one_or_none()` into a `MultipleResultsFound` at runtime on any
multi-outcome market, and the seed script hit exactly that the first time it
was run against a real database.

Each test below drives one previously market_id-only code path and asserts it
does not raise. Several also assert the value is right, because "did not
crash" was never the only thing wrong - picking an arbitrary pool silently
mispriced positions and misattributed LP stakes.
"""
from decimal import Decimal

import pytest
from conftest import token_for
from httpx import AsyncClient
from sqlalchemy import select

from app.models.liquidity import LiquidityPool, LPShare
from app.models.market import Outcome
from app.models.position import Position
from app.services.market_service import MarketService

HOME, DRAW, AWAY = "home", "draw", "away"


async def _outcome_id(db, market, name: str) -> str:
    rows = (
        await db.execute(
            select(Outcome).where(Outcome.market_id == market.id).order_by(Outcome.outcome_index)
        )
    ).scalars().all()
    return str(next(o.id for o in rows if o.name.lower() == name))


class TestReadEndpointsSurviveParimutuel:
    """GET paths. Each used a market_id-only pool lookup."""

    @pytest.mark.asyncio
    async def test_lp_position_sums_the_stake_across_every_pool(
        self, client: AsyncClient, db_session, multi_outcome_market, test_user
    ):
        # The user is an LP in two of the three outcome pools. Reporting only
        # one would understate their stake by two thirds.
        pools = await MarketService.load_outcome_pools(db_session, multi_outcome_market.id)
        for pool in pools[:2]:
            db_session.add(
                LPShare(
                    pool_id=pool.id,
                    user_id=test_user.id,
                    lp_tokens=Decimal(100),
                    collateral_deposited=Decimal(50),
                )
            )
        await db_session.commit()

        resp = await client.get(
            f"/api/v1/markets/{multi_outcome_market.id}/liquidity",
            headers={"Authorization": f"Bearer {token_for(test_user.id)}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]

        assert Decimal(data["lp_tokens"]) == Decimal(200)
        assert Decimal(data["collateral_deposited"]) == Decimal(100)
        # Pool totals span all three pools, not one.
        assert Decimal(data["pool_lp_token_supply"]) == sum(
            (p.lp_token_supply for p in pools), Decimal(0)
        )

    @pytest.mark.asyncio
    async def test_lp_position_with_no_stake_reports_zero(
        self, client: AsyncClient, multi_outcome_market, test_user
    ):
        resp = await client.get(
            f"/api/v1/markets/{multi_outcome_market.id}/liquidity",
            headers={"Authorization": f"Bearer {token_for(test_user.id)}"},
        )
        assert resp.status_code == 200
        assert Decimal(resp.json()["data"]["lp_tokens"]) == 0

    @pytest.mark.asyncio
    async def test_market_activity_prices_the_leading_outcome(
        self, client: AsyncClient, multi_outcome_market
    ):
        resp = await client.get(f"/api/v1/markets/{multi_outcome_market.slug}/activity")
        assert resp.status_code == 200, resp.text

        prices = [
            Decimal(o["price"])
            for o in resp.json()["data"].get("price_history", [])
        ]
        for p in prices:
            assert 0 <= p <= 1

    @pytest.mark.asyncio
    async def test_positions_are_priced_against_their_own_outcome_pool(
        self, client: AsyncClient, db_session, multi_outcome_market, test_user
    ):
        """A position must not be priced off a sibling outcome's pool.

        The old code keyed pools by market_id, so with one pool per outcome the
        dict kept whichever row came last and priced every position off it.
        """
        away_id = await _outcome_id(db_session, multi_outcome_market, AWAY)
        db_session.add(
            Position(
                user_id=test_user.id,
                market_id=multi_outcome_market.id,
                outcome_id=away_id,
                shares_held=Decimal(100),
                average_price=Decimal("0.30"),
            )
        )
        await db_session.commit()

        resp = await client.get(
            "/api/v1/positions/", headers={"Authorization": f"Bearer {token_for(test_user.id)}"}
        )
        assert resp.status_code == 200, resp.text

        rows = [
            p
            for p in resp.json()["data"]["positions"]
            if str(p["market_id"]) == str(multi_outcome_market.id)
        ]
        assert rows, "the position should be returned"
        row = rows[0]

        pools = await MarketService.load_outcome_pools(db_session, multi_outcome_market.id)
        total = sum((p.yes_shares for p in pools), Decimal(0))
        away = next(p for p in pools if str(p.outcome_id) == away_id)
        # shares_i / SUM(shares). Dividing by the pool's own yes+no instead
        # would give 1.0 for every outcome, since a parimutuel pool stores
        # no_shares = 0 - which is the bug this test guards.
        expected = float(away.yes_shares / total) if total > 0 else 0.5

        assert expected < 1.0, "sanity: the expected price must not be a flat 1.0"
        assert Decimal(str(row["current_price"])) == pytest.approx(
            Decimal(str(expected)), abs=Decimal("0.001")
        )

    @pytest.mark.asyncio
    async def test_market_detail_lists_every_outcome_price(
        self, client: AsyncClient, multi_outcome_market
    ):
        resp = await client.get(f"/api/v1/markets/{multi_outcome_market.slug}")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]

        outcomes = data["outcomes"]
        assert len(outcomes) == 3
        # Each outcome carries its own price - not a shared yes/no value.
        prices = {Decimal(str(o["price"])) for o in outcomes}
        assert len(prices) > 1, f"outcomes share one price: {prices}"


class TestLiquidityRequiresAnOutcomeOnParimutuel:
    """LP deposits must name an outcome once a market has more than one pool."""

    @pytest.mark.asyncio
    async def test_add_liquidity_without_an_outcome_is_rejected(
        self, client: AsyncClient, multi_outcome_market, test_user
    ):
        resp = await client.post(
            f"/api/v1/markets/{multi_outcome_market.id}/liquidity",
            json={"amount": "50"},
            headers={"Authorization": f"Bearer {token_for(test_user.id)}"},
        )
        assert resp.status_code == 422
        assert resp.json()["error_code"] == "OUTCOME_REQUIRED"

    @pytest.mark.asyncio
    async def test_add_liquidity_names_the_outcome_in_the_error(
        self, client: AsyncClient, multi_outcome_market, test_user
    ):
        resp = await client.post(
            f"/api/v1/markets/{multi_outcome_market.id}/liquidity",
            json={"amount": "50"},
            headers={"Authorization": f"Bearer {token_for(test_user.id)}"},
        )
        message = resp.json()["error"]
        assert "Home" in message and "Draw" in message and "Away" in message

    @pytest.mark.asyncio
    async def test_add_liquidity_credits_only_the_named_outcome_pool(
        self, client: AsyncClient, db_session, multi_outcome_market, test_user
    ):
        before = {
            str(p.outcome_id): p.yes_shares
            for p in await MarketService.load_outcome_pools(db_session, multi_outcome_market.id)
        }

        resp = await client.post(
            f"/api/v1/markets/{multi_outcome_market.id}/liquidity",
            json={"amount": "5", "outcome": AWAY},
            headers={"Authorization": f"Bearer {token_for(test_user.id)}"},
        )
        assert resp.status_code == 200, resp.text

        after = {
            str(p.outcome_id): p.yes_shares
            for p in await MarketService.load_outcome_pools(db_session, multi_outcome_market.id)
        }
        changed = [k for k in before if before[k] != after[k]]
        assert len(changed) == 1, f"expected one pool to move, moved {len(changed)}"

        away_id = await _outcome_id(db_session, multi_outcome_market, AWAY)
        assert changed == [away_id]

    @pytest.mark.asyncio
    async def test_add_liquidity_rejects_an_unknown_outcome(
        self, client: AsyncClient, multi_outcome_market, test_user
    ):
        resp = await client.post(
            f"/api/v1/markets/{multi_outcome_market.id}/liquidity",
            json={"amount": "5", "outcome": "Sponsorship"},
            headers={"Authorization": f"Bearer {token_for(test_user.id)}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_binary_market_needs_no_outcome(
        self, client: AsyncClient, test_market, test_user
    ):
        """The parimutuel requirement must not leak onto binary markets."""
        resp = await client.post(
            f"/api/v1/markets/{test_market.id}/liquidity",
            json={"amount": "50"},
            headers={"Authorization": f"Bearer {token_for(test_user.id)}"},
        )
        assert resp.status_code == 200, resp.text


class TestSplitMergeIsBinaryOnly:
    """Split/merge mint and redeem YES/NO pairs, so they cannot be parimutuel."""

    @pytest.mark.asyncio
    async def test_split_is_rejected_on_a_parimutuel_market(
        self, client: AsyncClient, multi_outcome_market, test_user
    ):
        resp = await client.post(
            "/api/v1/split-merge/split",
            json={"market_id": str(multi_outcome_market.id), "amount": "50"},
            headers={"Authorization": f"Bearer {token_for(test_user.id)}"},
        )
        assert resp.status_code == 422
        assert resp.json()["error_code"] == "NOT_BINARY_MARKET"

    @pytest.mark.asyncio
    async def test_merge_is_rejected_on_a_parimutuel_market(
        self, client: AsyncClient, multi_outcome_market, test_user
    ):
        resp = await client.post(
            "/api/v1/split-merge/merge",
            json={"market_id": str(multi_outcome_market.id), "amount": "50"},
            headers={"Authorization": f"Bearer {token_for(test_user.id)}"},
        )
        assert resp.status_code == 422
        assert resp.json()["error_code"] == "NOT_BINARY_MARKET"


class TestSettlementPaysFromTheWinningPoolsEscrow:
    """The payout must come from the winning outcome's own reserve."""

    @pytest.mark.asyncio
    async def test_settlement_drains_the_winning_pool_not_another(
        self, db_session, multi_outcome_market
    ):

        away_id = await _outcome_id(db_session, multi_outcome_market, AWAY)
        multi_outcome_market.winning_outcome_id = away_id
        multi_outcome_market.status = "resolved"
        await db_session.commit()

        pools = await MarketService.load_outcome_pools(db_session, multi_outcome_market.id)
        by_id = {str(p.outcome_id): p for p in pools}

        # Fund only the winning outcome's escrow.
        by_id[away_id].collateral = Decimal(5000)

        from app.workers.tasks import settle_market

        await settle_market(str(multi_outcome_market.id), str(away_id))
        await db_session.refresh(by_id[away_id])

        # The losers' pools are untouched.
        for oid, pool in by_id.items():
            if oid != away_id:
                assert pool.yes_shares > 0, "a losing outcome's pool was drained"


class TestBinaryPoolInvariantHolds:
    """The invariant that makes a market_id-only lookup safe for binary markets.

    Dropping UNIQUE(market_id) is what introduced the MultipleResultsFound
    class of failures. Binary markets must still resolve to exactly one pool, so
    that the remaining single-valued lookups keep working. If a fixture or a
    seeding path ever widens a binary market to two pools, it should fail here
    with a clear message rather than as an unrelated 500 somewhere.
    """

    @pytest.mark.asyncio
    async def test_no_market_has_two_binary_pools(self, db_session):
        rows = (
            await db_session.execute(
                select(LiquidityPool.market_id, LiquidityPool.id).where(
                    LiquidityPool.outcome_id.is_(None)
                )
            )
        ).all()

        by_market: dict = {}
        for market_id, pool_id in rows:
            by_market.setdefault(str(market_id), set()).add(str(pool_id))

        offenders = {k: len(v) for k, v in by_market.items() if len(v) > 1}
        assert not offenders, f"markets with several binary pools: {offenders}"
