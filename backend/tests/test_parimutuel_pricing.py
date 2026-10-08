"""Parimutuel pricing for multi-outcome markets.

A market with no real YES/NO pair - which includes a two-way NAMED market like
"Trump vs Biden", not just 3+ outcome ones - is parimutuel. Each outcome owns a
pool whose ``yes_shares`` is that outcome's share count, and the price is its
share of the market total.

The invariant that matters is ``sum(prices) == 1``. Getting that wrong is what
produced the original defect: one binary book, one NO reserve, and every outcome
that was not literally "yes" quoted off it - so an eight-way market rendered
"Yes 75 / No 25" from meaningless seed values.

These are pure unit tests over the maths, so the invariants hold without a
database. The schema-level guarantees are in test_parimutuel_schema.py.
"""
from decimal import Decimal

import pytest

from app.services.market_service import MarketService


def outcome(name: str, index: int = 0):
    from types import SimpleNamespace

    return SimpleNamespace(id=f"out-{name}", name=name, outcome_index=index)


def pool(outcome_id: str, shares: str, fee: str = "0.02"):
    from types import SimpleNamespace

    return SimpleNamespace(
        outcome_id=outcome_id,
        yes_shares=Decimal(shares),
        no_shares=Decimal(0),
        fee_rate=Decimal(fee),
    )


class TestIsParimutuel:
    def test_yes_no_market_is_binary(self):
        assert not MarketService.is_parimutuel(
            [outcome("Yes", 0), outcome("No", 1)]
        )

    def test_three_way_market_is_parimutuel(self):
        assert MarketService.is_parimutuel(
            [outcome("Home", 0), outcome("Draw", 1), outcome("Away", 2)]
        )

    def test_two_way_named_market_is_parimutuel(self):
        # The case a `len(outcomes) > 2` test would get wrong: two outcomes, but
        # neither is YES or NO, so there is no NO side to show.
        assert MarketService.is_parimutuel(
            [outcome("Trump", 0), outcome("Biden", 1)]
        )

    def test_matching_is_case_insensitive(self):
        assert not MarketService.is_parimutuel(
            [outcome("YES", 0), outcome("no", 1)]
        )

    def test_yes_without_no_is_parimutuel(self):
        # Degenerate: a single "Yes" outcome has no complement.
        assert MarketService.is_parimutuel([outcome("Yes", 0)])

    def test_empty_outcomes_is_parimutuel(self):
        # No names to judge by; callers fall back to the binary display.
        assert MarketService.is_parimutuel([])


class TestOutcomePrices:
    def test_prices_sum_to_one(self):
        pools = [pool("a", "400"), pool("b", "350"), pool("c", "250")]
        prices = MarketService.outcome_prices(pools)
        assert sum(prices.values()) == pytest.approx(Decimal("1.0"))

    def test_prices_are_the_share_of_total(self):
        pools = [pool("a", "400"), pool("b", "350"), pool("c", "250")]
        prices = MarketService.outcome_prices(pools)
        assert prices["a"] == pytest.approx(Decimal("0.4"))
        assert prices["b"] == pytest.approx(Decimal("0.35"))
        assert prices["c"] == pytest.approx(Decimal("0.25"))

    def test_two_way_named_market_still_sums_to_one(self):
        pools = [pool("trump", "550"), pool("biden", "450")]
        prices = MarketService.outcome_prices(pools)
        assert sum(prices.values()) == pytest.approx(Decimal("1.0"))
        assert prices["trump"] == pytest.approx(Decimal("0.55"))

    def test_never_zero_for_a_funded_outcome(self):
        # An outcome holding shares must never quote 0 - that reads as
        # "certainly loses" rather than "small chance".
        pools = [pool("a", "1000"), pool("b", "1")]
        prices = MarketService.outcome_prices(pools)
        assert prices["b"] > 0

    def test_unfunded_market_returns_an_even_split_not_zeros(self):
        pools = [pool("a", "0"), pool("b", "0"), pool("c", "0")]
        prices = MarketService.outcome_prices(pools)
        assert sum(prices.values()) == pytest.approx(Decimal("1.0"))
        assert all(p > 0 for p in prices.values())

    def test_empty_pool_list(self):
        assert MarketService.outcome_prices([]) == {}


class TestBuildOutcomeAmm:
    def test_reserve_is_the_outcomes_own_shares(self):
        pools = [pool("a", "400"), pool("b", "350"), pool("c", "250")]
        amm, total = MarketService.build_outcome_amm(pools, "b")
        assert amm.yes_shares == Decimal(350)
        assert total == Decimal(1000)

    def test_complement_is_the_rest_of_the_market(self):
        pools = [pool("a", "400"), pool("b", "350"), pool("c", "250")]
        amm, total = MarketService.build_outcome_amm(pools, "a")
        # YES reserve + complement == market total, so BinaryAMM's own total is
        # the market total and its price maths is unchanged.
        assert amm.yes_shares + amm.no_shares == total

    def test_price_matches_the_parimutuel_share(self):
        pools = [pool("a", "400"), pool("b", "600")]
        amm, _ = MarketService.build_outcome_amm(pools, "a")
        assert amm.price("yes") == pytest.approx(Decimal("0.4"))

    def test_buying_raises_this_outcome_and_lowers_the_others(self):
        pools = [pool("a", "500"), pool("b", "500")]
        amm, total = MarketService.build_outcome_amm(pools, "a")

        amm.buy("yes", Decimal(100))
        assert amm.yes_shares > Decimal(500)

        # Total grew, so the untouched outcome's share of it must fall.
        other = Decimal(500)
        assert other / (amm.yes_shares + amm.no_shares) < Decimal("0.5")

    def test_unknown_outcome_falls_back_to_an_even_reserve(self):
        pools = [pool("a", "500")]
        amm, _ = MarketService.build_outcome_amm(pools, "missing")
        assert amm.yes_shares == Decimal(0)

    def test_never_raises_a_negative_complement(self):
        # A pool holding more shares than the recorded total would produce a
        # negative reserve, which BinaryAMM would treat as a real value.
        pools = [pool("a", "600"), pool("b", "100")]
        amm, _ = MarketService.build_outcome_amm(pools, "a")
        assert amm.no_shares >= Decimal(0)


class TestOutcomesStayDistinguishable:
    def test_two_outcomes_no_longer_share_one_price(self):
        # The original defect in one assertion: "No" and "Draw" shared a reserve
        # and therefore quoted the same price.
        pools = [pool("no", "300"), pool("draw", "700")]
        prices = MarketService.outcome_prices(pools)
        assert prices["no"] != prices["draw"]

    def test_eight_way_market_prices_differ(self):
        # Distinct share counts, so the assertion below actually tests that no
        # two outcomes collide - which is the original defect.
        shares = ["100", "200", "50", "80", "30", "25", "10", "5"]
        pools = [pool(f"o{i}", s) for i, s in enumerate(shares)]
        prices = MarketService.outcome_prices(pools)

        assert len(prices) == 8
        assert sum(prices.values()) == pytest.approx(Decimal("1.0"))
        # No two outcomes quote the same price.
        assert len({round(p, 6) for p in prices.values()}) == 8

    def test_prices_stay_in_the_unit_interval(self):
        pools = [pool("a", "1"), pool("b", "999")]
        prices = MarketService.outcome_prices(pools)
        assert all(0 < p < 1 for p in prices.values())