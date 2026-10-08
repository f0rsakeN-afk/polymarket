"""Price invariants behind the live chart.

The frontend used to draw a flat zero when a market's price did not move. That
symptom had no backend cause, and this file exists to keep it that way: the
server must never publish or record a price of 0, because the chart treats a 0
as a real value and draws it.

Everything here is a pure unit test - no database, no Redis - so the guarantee
can be checked without the stack. The integration-level behaviour is covered by
test_markets.py / test_websocket.py.
"""
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.services.market_service import MarketService
from app.services.order_service import OrderService


class FakePool:
    """Stand-in for a LiquidityPool with the two fields price maths reads."""

    def __init__(self, yes, no):
        self.yes_shares = Decimal(str(yes))
        self.no_shares = Decimal(str(no))


EMPTY = FakePool(0, 0)
# Pools where BOTH sides hold shares. One-sided pools are excluded on purpose:
# a side with genuinely no shares is worth exactly 0, which is asserted
# separately below.
BOTH_SIDES = [
    (0.5, 0.5),
    (0.62, 0.38),
    (0.9, 0.1),
    (0.999, 0.001),
    (1234.5, 987.5),
]
ALL_SPLITS = [*BOTH_SIDES, (1, 0), (0, 1)]


class TestComputePricesNeverZero:
    """An unfunded pool must read 0.5, not 0.

    0.5 is the "no information" price. Returning 0 would mean "this outcome is
    certain", which is a real, wrong market state - and it is exactly what the
    chart would render.
    """

    def test_missing_pool_is_an_even_split(self):
        assert MarketService.compute_prices(None) == (Decimal("0.5"), Decimal("0.5"))

    def test_empty_pool_is_an_even_split(self):
        assert MarketService.compute_prices(EMPTY) == (Decimal("0.5"), Decimal("0.5"))

    def test_pool_price_of_empty_pool_is_an_even_split(self):
        assert MarketService.pool_price(EMPTY) == Decimal("0.5")

    def test_order_service_helper_mirrors_the_same_guard(self):
        # OrderService has its own float copy of the same maths; it must not be
        # the one place that leaks a 0.
        assert OrderService._get_market_prices(EMPTY) == (0.5, 0.5)

    @pytest.mark.parametrize("yes,no", BOTH_SIDES)
    def test_prices_are_strictly_inside_the_unit_interval(self, yes, no):
        pool = FakePool(yes, no)
        yes_price, no_price = MarketService.compute_prices(pool)

        for price in (yes_price, no_price):
            assert Decimal(0) < price < Decimal(1), f"{price} escaped (0, 1)"

    @pytest.mark.parametrize("yes,no", ALL_SPLITS)
    def test_prices_always_sum_to_one(self, yes, no):
        yes_price, no_price = MarketService.compute_prices(FakePool(yes, no))
        assert yes_price + no_price == Decimal(1)

    @pytest.mark.parametrize(
        "yes,no,empty_is", [(0, 1, "yes"), (1, 0, "no")]
    )
    def test_a_one_sided_pool_reports_zero_only_for_the_genuinely_empty_side(
        self, yes, no, empty_is
    ):
        # A side holding no shares is worth 0 - a real, correct state. What must
        # never happen is an EMPTY pool producing a 0 for either side, which is
        # covered by the even-split tests above.
        yes_price, no_price = MarketService.compute_prices(FakePool(yes, no))
        prices = {"yes": yes_price, "no": no_price}

        assert prices[empty_is] == Decimal(0)
        assert prices["yes" if empty_is == "no" else "no"] == Decimal(1)

    def test_float_helper_agrees_with_the_decimal_one(self):
        for yes, no in ALL_SPLITS:
            pool = FakePool(yes, no)
            d_yes, d_no = MarketService.compute_prices(pool)
            f_yes, f_no = OrderService._get_market_prices(pool)

            assert float(d_yes) == pytest.approx(f_yes, abs=1e-9)
            assert float(d_no) == pytest.approx(f_no, abs=1e-9)


class _FakePipeline:
    """Captures the payload the publisher hands to Redis pub/sub."""

    def __init__(self, sink):
        self._sink = sink

    def hset(self, *args, **kwargs):
        return self

    def expire(self, *args, **kwargs):
        return self

    def sadd(self, *args, **kwargs):
        return self

    def publish(self, channel, payload):
        self._sink.append(payload)

    async def execute(self):
        return None


class _FakeRedis:
    """Just enough Redis for RedisPubSub.publish_price_update.

    `publish_price_update` gates on `if not self._redis`, then calls
    `self._redis.pipeline()` inside the body handed to redis_cb.call.
    """

    def __init__(self, sink):
        self._sink = sink

    def pipeline(self):
        return _FakePipeline(self._sink)


async def _call_op(op):
    """Stand-in for redis_cb.call that actually runs the operation.

    Must be a real coroutine function, not AsyncMock(side_effect=lambda op:
    op()): that returns the coroutine object without awaiting it, so the
    publisher's body never runs and nothing is ever published.
    """
    return await op()


async def _publish_price_update(market_id, yes_price, no_price, volume):
    """Run publish_price_update against the fakes and return what was published."""
    import json

    from app.websocket.manager import RedisPubSub

    published: list[str] = []
    bus = RedisPubSub()
    bus._redis = _FakeRedis(published)

    with patch("app.websocket.manager.redis_cb.call", new=_call_op):
        await bus.publish_price_update(market_id, yes_price, no_price, volume)

    assert published, "nothing was published"
    return json.loads(published[0])


class TestPriceUpdatePayload:
    """The wire contract the frontend's realtime handling depends on."""

    @pytest.mark.asyncio
    async def test_published_frame_carries_yes_and_no_prices(self):
        payload = await _publish_price_update("mkt-1", 0.62, 0.38, 10.0)

        assert payload["type"] == "market:price_update"
        assert payload["market_id"] == "mkt-1"
        assert payload["yes_price"] == 0.62
        assert payload["no_price"] == 0.38

    @pytest.mark.asyncio
    async def test_published_frame_has_no_outcome_prices_key(self):
        """Documents a real frontend/backend mismatch.

        The frontend's handler has an `outcome_prices` branch, but the server has
        never sent that field - so the branch is dead code and multi-outcome
        markets cannot learn per-outcome prices over the socket. Pinning it here
        means that if the server ever starts sending it, this test fails loudly
        instead of the two sides drifting apart quietly.
        """
        payload = await _publish_price_update("mkt-1", 0.62, 0.38, 10.0)
        assert "outcome_prices" not in payload