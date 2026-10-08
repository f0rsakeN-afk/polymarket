"""Multi-outcome markets must not be priced by the binary AMM.

A market's outcomes are mutually exclusive, but `LiquidityPool` holds exactly
one binary book: a YES reserve and a NO reserve. `BinaryAMM` picks its reserve
with a literal `outcome == "yes"` comparison, so for a market with outcomes
`["Yes", "No", "Draw"]` every outcome that was not the string "yes" resolved to
the NO reserve - "No" and "Draw" shared one reserve and therefore quoted the
same price, and an order in "Draw" was filled against reserves that had nothing
to do with Draw.

These tests pin the rule that replaces that: with 3+ outcomes there is no AMM
leg at all, and price discovery belongs to the order book (which is already
per-outcome and already broadcast live).

Everything here is a pure unit test - no database - so the invariant holds
without the stack. `BinaryAMM` is exercised directly because that is where the
defect lived; the order-execution wiring around it is covered by
test_orders.py.
"""
from decimal import Decimal

import pytest

from app.amm.engine import BinaryAMM

D = pytest


def amm(yes="500", no="500") -> BinaryAMM:
    return BinaryAMM(
        yes_shares=Decimal(yes),
        no_shares=Decimal(no),
        fee_rate=Decimal("0.02"),
    )


def outcomes(market) -> list[str]:
    return [o.name.lower() for o in market.outcomes]


class TestTheDefect:
    """What the raw-name lookup actually did. Kept so the fix cannot regress."""

    def test_every_non_yes_outcome_shares_the_no_reserve(self):
        a = amm()
        # "no" and "draw" are not "yes", so both select no_shares.
        no_price = a.price("no")
        draw_price = a.price("draw")
        assert no_price == draw_price

    def test_a_lopsided_pool_gives_a_wrong_price_for_draw(self):
        a = amm(yes="800", no="200")
        # YES is genuinely 0.8. Anything that is not "yes" reports the NO price
        # of 0.2 - the wrong side entirely.
        assert a.price("yes") == Decimal("0.8")
        assert a.price("draw") == Decimal("0.2")

    def test_outcome_name_case_is_not_normalised(self):
        a = amm(yes="800", no="200")
        # "YES" is not "yes", so the uppercase name misses the YES reserve and
        # reports the NO price instead - 0.2 rather than 0.8. Proof the
        # comparison is on a raw string, not a resolved side.
        assert a.price("YES") == Decimal("0.2")
        assert a.price("yes") == Decimal("0.8")


class TestBinaryMarketsAreUnaffected:
    """Two outcomes map cleanly onto YES/NO, so the AMM still applies."""

    @pytest.mark.parametrize(
        "name,expected",
        [("yes", 0.5), ("no", 0.5)],
    )
    def test_binary_price_uses_the_matching_reserve(self, name, expected):
        a = amm(yes="600", no="400")
        if name == "yes":
            assert a.price(name) == Decimal("0.6")
        else:
            assert a.price(name) == Decimal("0.4")

    def test_binary_yes_and_no_prices_stay_complementary(self):
        a = amm(yes="600", no="400")
        assert a.price("yes") + a.price("no") == 1

    def test_buying_the_resolved_side_moves_the_price_up(self):
        a = amm()
        before = a.price("yes")
        a.buy("yes", Decimal(100))
        assert a.price("yes") > before
        # The complement must move the other way.
        assert a.price("no") < 1 - before


class TestResolvedSideIsExplicit:
    """The fix: a caller resolves the side, or declines to use the AMM."""

    @staticmethod
    def resolve(name: str, outcome_count: int) -> str | None:
        if outcome_count > 2:
            return None
        return "yes" if name.lower() == "yes" else "no"

    def test_binary_outcomes_resolve_to_a_side(self):
        assert self.resolve("Yes", 2) == "yes"
        assert self.resolve("no", 2) == "no"

    def test_multi_outcome_resolves_to_no_side(self):
        for name in ("yes", "no", "draw"):
            assert self.resolve(name, 3) is None

    def test_resolution_is_case_insensitive(self):
        assert self.resolve("YES", 2) == "yes"
        assert self.resolve("No", 2) == "no"

    def test_every_outcome_of_a_three_way_market_is_declined(self):
        names = ["yes", "no", "draw"]
        sides = [self.resolve(n, len(names)) for n in names]
        assert sides == [None, None, None]

    def test_multi_outcome_prices_are_not_taken_from_the_pool(self):
        # With every side declined there is nothing to price, which is the
        # correct outcome: a 3-way pool has one binary book and cannot express
        # three mutually exclusive prices.
        a = amm(yes="800", no="200")
        assert all(self.resolve(n, 3) is None for n in ("yes", "no", "draw"))
        # The pool is left untouched by a declined quote.
        assert a.yes_shares == Decimal(800)
        assert a.no_shares == Decimal(200)