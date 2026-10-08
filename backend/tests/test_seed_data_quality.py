"""The seed must produce data that holds together under inspection.

Every assertion here corresponds to something that was visibly wrong in a demo:
a fill at 0.90 on a market priced 0.15, a chart whose tip contradicted the price
beside it, a settled market still quoting 0.99, resting orders claiming more
unfilled than they were sized for.

The generators are pure functions (`_price_path`, `_trade_price`,
`_planned_resolved_at`) so their invariants are tested directly. The DB-backed
properties are covered in test_parimutuel_endpoints.py; what matters here is that
the generators cannot emit an impossible value in the first place.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from seed import (  # noqa: E402
    RESOLVED_MARKETS,
    _outcome_weights,
    _planned_resolved_at,
    _price_path,
    _trade_price,
)


class TestPricePath:
    def test_ends_exactly_on_the_live_price(self):
        """The chart's tip must equal the price shown beside it."""
        for end in (0.05, 0.26, 0.5, 0.62, 0.93):
            assert _price_path(end, points=48)[-1] == pytest.approx(end)

    def test_returns_the_requested_number_of_points(self):
        assert len(_price_path(0.5, points=48)) == 48

    def test_single_point_series(self):
        assert _price_path(0.7, points=1) == [0.7]

    def test_every_point_is_a_valid_probability(self):
        for end in (0.02, 0.5, 0.98):
            for p in _price_path(end, points=60):
                assert 0.0 < p < 1.0, f"{p} out of range for end={end}"

    def test_is_ordered_oldest_to_newest(self):
        # Reversal happens in the caller; if this helper ever returns
        # newest-first the chart would run backwards in time.
        path = _price_path(0.62, points=30)
        assert path[-1] == pytest.approx(0.62)

    def test_has_shape_rather_than_being_flat(self):
        # A flat series is what "price has not moved" looks like, and it reads as
        # a broken chart rather than a quiet market.
        assert len(set(_price_path(0.5, points=48))) > 5

    def test_converges_rather_than_drifting(self):
        # The final stretch should be tight around the end price, not a random
        # walk that happens to land there.
        tail = _price_path(0.5, points=40)[-10:]
        assert max(abs(v - 0.5) for v in tail) < 0.25


class TestTradePrice:
    def test_stays_near_the_market(self):
        """The defect: fills drawn independently of the market's price."""
        for market_price in (0.05, 0.26, 0.5, 0.75, 0.95):
            for _ in range(200):
                assert abs(_trade_price(market_price) - market_price) < 0.06

    def test_is_never_outside_the_unit_interval(self):
        for market_price in (0.0, 0.01, 0.5, 0.99, 1.0):
            for _ in range(200):
                p = _trade_price(market_price)
                assert 0.0 < p < 1.0

    def test_never_returns_zero(self):
        # A 0.00 fill is not a tradeable price.
        for market_price in (0.001, 0.01, 0.05):
            for _ in range(200):
                assert _trade_price(market_price) >= 0.01

    def test_clusters_on_the_market_rather_than_spreading_flat(self):
        prices = [_trade_price(0.5) for _ in range(500)]
        near = sum(1 for p in prices if abs(p - 0.5) <= 0.02)
        assert near > len(prices) * 0.8


class TestOutcomeWeights:
    def test_sums_to_one(self):
        # price_i = shares_i / SUM(shares), so the weights must total 1 or the
        # outcome prices will not.
        for n in (2, 3, 6, 8, 20):
            assert sum(_outcome_weights(n)) == pytest.approx(1.0)

    def test_favours_the_first_outcome(self):
        weights = _outcome_weights(8)
        assert weights == sorted(weights, reverse=True)

    def test_gives_a_plausible_favourite(self):
        # Below 0.2 reads as noise; an even split makes every chart line overlap.
        assert 0.3 < _outcome_weights(8)[0] < 0.7

    def test_single_outcome(self):
        assert _outcome_weights(1) == [pytest.approx(1.0)]


class TestResolvedMarkets:
    def test_every_planned_slug_exists_in_the_market_list(self):
        from seed import MARKETS_DATA

        slugs = {m["slug"] for m in MARKETS_DATA}
        for entry in RESOLVED_MARKETS:
            assert entry["slug"] in slugs, f"{entry['slug']} is not a seeded market"

    def test_every_winner_is_a_real_outcome_on_that_market(self):
        """A winner name that matches nothing would silently skip resolution."""
        from seed import MARKETS_DATA

        for entry in RESOLVED_MARKETS:
            market = next(m for m in MARKETS_DATA if m["slug"] == entry["slug"])
            names = (
                list(market["outcomes"])
                if market.get("multi_outcome")
                else ["Yes", "No"]
            )
            assert entry["winner"].lower() in [n.lower() for n in names], (
                f"{entry['slug']} has no outcome '{entry['winner']}'"
            )

    def test_slugs_are_unique(self):
        slugs = [e["slug"] for e in RESOLVED_MARKETS]
        assert len(slugs) == len(set(slugs))


class TestPlannedResolutionDate:
    def test_is_in_the_past(self):
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        assert _planned_resolved_at("trump-2024-wins", now) < now

    def test_falls_inside_the_history_window(self):
        """A series shorter than the time to settlement runs past its own end.

        The history generator sizes its window from this date, and the
        snapshot-price worker writes ~48 points at 16 h intervals, so anything
        resolved beyond ~32 days would leave the tip mid-range instead of at the
        $1.00 / $0.00 settlement value.
        """
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        for entry in RESOLVED_MARKETS:
            when = _planned_resolved_at(entry["slug"], now)
            days = (now - when).days
            assert 0 < days <= 32, f"{entry['slug']} resolves {days} days ago"

    def test_is_deterministic(self):
        """History and the resolver must agree on the date, so it cannot drift."""
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        a = _planned_resolved_at("trump-2024-wins", now)
        b = _planned_resolved_at("trump-2024-wins", now)
        assert a == b