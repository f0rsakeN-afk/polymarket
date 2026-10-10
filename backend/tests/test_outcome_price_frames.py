"""Per-outcome prices must reach the client.

The front end has always had an `outcome_prices` branch in its
`market:price_update` handler, but the server never sent that field - so on a
market with 3+ outcomes every line except the first sat frozen at its seed
price while binary markets tracked live.

These tests pin the payload contract: `outcome_prices` is keyed by the outcome's
canonical name, carries every outcome with a usable side, and never invents a
zero for an outcome the book cannot price.

Pure unit tests - the Redis pipeline and the order-book payload are faked.
"""
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.order_service import OrderService
from app.websocket.manager import RedisPubSub


def outcome(name: str):
    return SimpleNamespace(name=name)


def level(price):
    return SimpleNamespace(price=price)


def book(**outcomes):
    """Build an orderbook payload keyed by lower-cased outcome name."""
    return {"outcomes": {k.lower(): v for k, v in outcomes.items()}}


class TestOutcomePricesFromBook:
    def test_mid_of_best_bid_and_ask(self):
        prices = OrderService.outcome_prices_from_book(
            book(Yes={"bids": [level("0.58")], "asks": [level("0.62")]}),
            [outcome("Yes")],
        )
        assert prices == {"Yes": 0.60}

    def test_asks_only_uses_the_lowest_ask(self):
        prices = OrderService.outcome_prices_from_book(
            book(Draw={"bids": [], "asks": [level("0.25"), level("0.21")]}), [outcome("Draw")]
        )
        assert prices == {"Draw": 0.21}

    def test_bids_only_uses_the_bid(self):
        prices = OrderService.outcome_prices_from_book(
            book(Draw={"bids": [level("0.40")], "asks": []}), [outcome("Draw")]
        )
        assert prices == {"Draw": 0.40}

    def test_picks_the_best_of_each_side_not_the_last(self):
        prices = OrderService.outcome_prices_from_book(
            book(Yes={"bids": [level("0.50"), level("0.59")], "asks": [level("0.63"), level("0.61")]}),
            [outcome("Yes")],
        )
        # best bid 0.59, best ask 0.61 -> mid 0.60
        assert prices["Yes"] == pytest.approx(0.60)

    def test_keys_use_the_canonical_outcome_name_not_the_book_key(self):
        # build_orderbook keys by `o.name.lower()`, so an outcome named "Team A"
        # arrives under the key "team a" - including the space, lower-cased.
        payload = {"outcomes": {"team a": {"bids": [], "asks": [level("0.7")]}}}
        prices = OrderService.outcome_prices_from_book(payload, [outcome("Team A")])

        # The payload must use the canonical name so the client can match it
        # against its outcome list without re-normalising.
        assert list(prices) == ["Team A"]
        assert prices["Team A"] == pytest.approx(0.7)

    def test_all_outcomes_are_priced_not_just_the_traded_one(self):
        outcomes = [outcome("Yes"), outcome("No"), outcome("Draw")]
        prices = OrderService.outcome_prices_from_book(
            book(
                Yes={"bids": [], "asks": [level("0.5")]},
                No={"bids": [], "asks": [level("0.3")]},
                Draw={"bids": [], "asks": [level("0.2")]},
            ),
            outcomes,
        )
        assert set(prices) == {"Yes", "No", "Draw"}

    def test_an_unpriceable_outcome_is_omitted_never_zeroed(self):
        # A missing key is a gap the front end renders as a break. A fabricated
        # 0 would be a real, wrong price.
        prices = OrderService.outcome_prices_from_book(
            book(Yes={"bids": [], "asks": [level("0.5")]}), [outcome("Yes"), outcome("Draw")]
        )
        assert set(prices) == {"Yes"}
        assert "Draw" not in prices

    def test_an_empty_side_list_is_not_a_zero(self):
        prices = OrderService.outcome_prices_from_book(
            book(Draw={"bids": [], "asks": []}), [outcome("Draw")]
        )
        assert prices == {}

    def test_missing_outcome_in_book_is_skipped(self):
        prices = OrderService.outcome_prices_from_book(book(Yes={"asks": [level("0.5")]}), [outcome("Draw")])
        assert prices == {}

    def test_rejects_non_finite_prices(self):
        prices = OrderService.outcome_prices_from_book(
            book(Yes={"bids": [level("NaN")], "asks": [level("Infinity")]}),
            [outcome("Yes")],
        )
        assert prices == {}

    def test_rejects_none_and_bool_prices(self):
        prices = OrderService.outcome_prices_from_book(
            book(Yes={"bids": [level(None)], "asks": [level(True)]}), [outcome("Yes")]
        )
        assert prices == {}

    def test_accepts_decimal_levels(self):
        prices = OrderService.outcome_prices_from_book(
            book(Yes={"bids": [level(Decimal("0.58"))], "asks": [level(Decimal("0.62"))]}),
            [outcome("Yes")],
        )
        assert prices["Yes"] == pytest.approx(0.60)

    def test_tolerates_an_empty_book(self):
        assert OrderService.outcome_prices_from_book({}, [outcome("Yes")]) == {}
        assert OrderService.outcome_prices_from_book({"outcomes": {}}, [outcome("Yes")]) == {}

    def test_skips_an_outcome_row_without_a_name(self):
        prices = OrderService.outcome_prices_from_book(
            book(Yes={"asks": [level("0.5")]}), [SimpleNamespace(name=None)]
        )
        assert prices == {}


class _FakePipeline:
    """Models the pipeline the price publish actually issues.

    `eval` is the sequenced publish: the real command runs a Lua script that
    does INCR + splice + PUBLISH atomically, so the fake performs the same
    `__SEQ__` substitution. Substituting here rather than ignoring it keeps the
    payload these tests assert on byte-identical to what a subscriber receives.
    """

    def __init__(self, sink):
        self._sink = sink
        self._seq = 0

    def hset(self, *a, **k):
        return self

    def expire(self, *a, **k):
        return self

    def sadd(self, *a, **k):
        return self

    def publish(self, channel, payload):
        self._sink.append(payload)

    def eval(self, script, numkeys, *keys_and_args):
        payload = keys_and_args[-1]
        self._seq += 1
        self._sink.append(payload.replace('"__SEQ__"', str(self._seq)))
        return self

    async def execute(self):
        return None


class _FakeRedis:
    def __init__(self, sink):
        self._sink = sink

    def pipeline(self):
        return _FakePipeline(self._sink)


async def _call_op(op):
    return await op()


async def _publish(**kwargs):
    published: list[str] = []
    bus = RedisPubSub()
    bus._redis = _FakeRedis(published)
    with patch("app.websocket.manager.redis_cb.call", new=_call_op):
        await bus.publish_price_update("mkt-1", **kwargs)
    assert published, "nothing was published"
    return json.loads(published[0])


class TestPublishPriceUpdatePayload:
    @pytest.mark.asyncio
    async def test_binary_market_omits_outcome_prices(self):
        # Unchanged wire shape, so existing binary clients are unaffected.
        payload = await _publish(yes_price=0.62, no_price=0.38, volume=10.0)
        assert payload["yes_price"] == 0.62
        assert payload["no_price"] == 0.38
        assert "outcome_prices" not in payload

    @pytest.mark.asyncio
    async def test_multi_outcome_market_carries_outcome_prices(self):
        payload = await _publish(
            yes_price=0.5,
            no_price=0.5,
            volume=10.0,
            outcome_prices={"Yes": 0.5, "No": 0.3, "Draw": 0.2},
        )
        assert payload["outcome_prices"] == {"Yes": 0.5, "No": 0.3, "Draw": 0.2}

    @pytest.mark.asyncio
    async def test_empty_outcome_prices_is_treated_as_absent(self):
        # An empty dict must not ship an empty field the client would trip over.
        payload = await _publish(
            yes_price=0.5, no_price=0.5, volume=1.0, outcome_prices={}
        )
        assert "outcome_prices" not in payload

    @pytest.mark.asyncio
    async def test_payload_is_json_serialisable(self):
        payload = await _publish(
            yes_price=0.5, no_price=0.5, volume=1.0, outcome_prices={"Yes": 0.5}
        )
        # re-encode the way redis.publish does
        assert json.loads(json.dumps(payload))["outcome_prices"] == {"Yes": 0.5}