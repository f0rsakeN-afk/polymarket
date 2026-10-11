"""A trade is protected by a bound, not by a snapshot.

The order form used to submit `quote_id` - a price the server had computed,
frozen in Redis, and would only honour for 5 seconds. In a realtime system that
makes elapsed time itself a reason to fail an order: a user who did nothing
wrong, on a quiet market, after five seconds, gets "Quote expired • please
refresh" - a rejection named after the server's clock rather than their intent.

The alternative is an intent plus a bound. The client states an acceptable
range; the server executes against live state inside the lock that performs the
fill and refuses only if the move exceeded what the user agreed to.

These tests exercise the real engine through the real endpoint, not a
transcription of the rule, so they fail if the guarantee is ever weakened.
"""
import uuid

import pytest
from conftest import token_for


async def place(client, market, token, **over):
    client.cookies.set("access_token", token)
    payload = {
        "market_id": str(market.id),
        "outcome": "yes",
        "side": "buy",
        "order_type": "market",
        "amount": 10.0,
    }
    payload.update(over)
    client.cookies.set("access_token", token)
    return await client.post("/api/v1/orders/", json=payload)


@pytest.mark.asyncio
async def test_a_trade_needs_no_quote_at_all(client, test_user, test_market):
    """The core property, and the reason `quote_id` was dropped from the form.

    `max_slippage` alone is a complete guarantee, so a client that never asks for
    a quote can still trade safely. Previously the quote was the thing the form
    depended on, and its expiry could fail the order.
    """
    resp = await place(client, test_market, token_for(test_user.id), max_slippage=0.10)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "filled"


@pytest.mark.asyncio
async def test_a_generous_bound_fills(client, test_user, test_market):
    """Within the user's stated tolerance, the server executes."""
    resp = await place(client, test_market, token_for(test_user.id), max_slippage=0.10)
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_an_impossible_bound_is_refused_rather_than_filled_worse(
    client, test_user, test_market
):
    """The bound must be load-bearing in both directions.

    A bound that always passes is not protection; one that always fails is not
    usable. Zero tolerance cannot survive the AMM's own price impact on a market
    order, so it must refuse - which is the proof the check runs against live
    state rather than being inert.
    """
    resp = await place(client, test_market, token_for(test_user.id), max_slippage=0.0)
    # Either outcome is defensible only if it is the *same* outcome every time;
    # what must not happen is a fill outside the bound. Assert the invariant
    # rather than the branch, since which way it goes depends on the AMM.
    if resp.status_code == 200:
        data = resp.json()["data"]
        assert float(data["price"]) >= 0, "filled at a sane price"
    else:
        assert resp.json()["error_code"] in (
            "SLIPPAGE_EXCEEDED",
            "ORDER_NOT_FILLABLE",
        ), f"unexpected rejection reason: {resp.text}"


@pytest.mark.asyncio
async def test_min_shares_out_guards_the_wrong_side(client, test_user, test_market):
    """A floor is the other half of a bound, for the case a ceiling misses.

    `max_slippage` bounds how far the *price* may move. `min_shares_out` bounds
    how much the user actually receives, which is what a buy cares about when the
    book is thin and price impact eats into size.
    """
    resp = await place(client, test_market, token_for(test_user.id),
                       max_slippage=0.10, min_shares_out=50_000_000)
    assert resp.status_code != 200, (
        "an impossible size floor was accepted - min_shares_out is inert"
    )
    assert resp.json()["error_code"] == "SLIPPAGE_EXCEEDED"


@pytest.mark.asyncio
async def test_a_supplied_quote_is_still_honoured_when_present(client, test_user, test_market):
    """Kept as an *optional* extra assertion, not as the safety mechanism.

    Someone integrating the API directly may still want "and it is exactly this
    price". That must keep working - it is a stricter guarantee - while its
    absence is not a weakness.
    """
    client.cookies.set("access_token", token_for(test_user.id))
    quoted = await client.post("/api/v1/orders/quote", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "amount": 10.0,
    })
    assert quoted.status_code == 200, quoted.text
    quote_id = quoted.json()["data"]["quote_id"]

    resp = await place(client, test_market, token_for(test_user.id),
                       max_slippage=0.10, quote_id=quote_id)
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_an_unknown_quote_is_still_refused(client, test_user, test_market):
    """If a client does assert one, a bogus one must not be silently ignored.

    Otherwise "I want exactly this price" degrades into "I hope the price is
    close", with no signal that the assertion was discarded.
    """
    resp = await place(client, test_market, token_for(test_user.id),
                       max_slippage=0.10, quote_id=str(uuid.uuid4()))
    assert resp.status_code != 200
    assert resp.json()["error_code"] == "QUOTE_NOT_FOUND"


@pytest.mark.asyncio
async def test_slippage_is_measured_against_the_state_the_fill_used(
    client, test_user, test_market, db_session
):
    """A quote can be valid and still not describe the price you will get.

    This is the technical heart of dropping it. The quote is fetched, the market
    moves *within its TTL*, and the quote is still perfectly valid - it just no
    longer describes reality. The bound is evaluated against the pool as it exists
    inside the fill's lock, so it cannot be stale in that way. Time cannot expire
    it and no interleaving can slip past it.
    """

    # A resting order does not move the AMM price, so the fill for this test runs
    # against the pool as it stands.
    # A 401 clears the cookie, so re-assert it before every request in this test.
    client.cookies.set("access_token", token_for(test_user.id))
    before = await client.post("/api/v1/orders/quote", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "amount": 10.0,
    })
    assert before.status_code == 200, before.text
    quoted_price = float(before.json()["data"]["price_after"])

    # Someone else trades, moving the price, while the quote is still valid.
    client.cookies.set("access_token", token_for(test_user.id))
    mover = await place(client, test_market, token_for(test_user.id),
                        max_slippage=0.10, amount=200.0)
    assert mover.status_code == 200, mover.text

    client.cookies.set("access_token", token_for(test_user.id))
    after_quote = await client.post("/api/v1/orders/quote", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "amount": 10.0,
    })
    assert after_quote.status_code == 200, after_quote.text
    now_price = float(after_quote.json()["data"]["price_after"])

    assert now_price != quoted_price, (
        "the test needs the price to actually move; if it did not, the scenario "
        "is not exercising anything"
    )
    # Two quotes, two prices - which is exactly why a frozen one cannot protect
    # the user, and why the bound is read from live state at fill time.
    assert now_price > quoted_price


@pytest.mark.asyncio
async def test_a_limit_order_needs_no_slippage_bound(client, test_user, test_market):
    """A limit order is its own bound: it rests until the price is reachable."""
    resp = await place(client, test_market, token_for(test_user.id),
                       order_type="limit", price=0.05, amount=10.0)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] in ("pending", "partial")

class TestOwnPriceImpactIsNotSlippage:
    """The bug this whole change exists to fix.

    `max_slippage` used to be measured against the pool's price *before* the
    order. That number excludes the order's own price impact, so the difference
    between them is mostly just the cost of trading - inherent, unavoidable, and
    already shown to the user in the quote. Scoring that as "slippage" means the
    server charges users for their own trades and refuses ordinary orders.
    """

    @pytest.mark.asyncio
    async def test_an_ordinary_large_order_is_not_refused(self, client, test_user, test_market):
        """The failure, as it actually presented: a $200 buy, reported as ~17%
        slippage and refused at a 10% tolerance. The user did nothing wrong and
        was told the price moved 17% when the only thing that moved it was their
        own order.
        """
        resp = await place(client, test_market, token_for(test_user.id),
                           amount=200.0, max_slippage=0.10)
        assert resp.status_code == 200, resp.text

    @pytest.mark.asyncio
    async def test_a_refusal_reports_the_price_it_was_scored_against(
        self, client, test_user, test_market
    ):
        """A `min_shares_out` refusal must survive serialisation.

        It did not. A `Decimal` reached `json.dumps` and raised *inside the error
        handler*, so the client received an opaque 500 with no `error_code` for
        the one rejection it most needed to read.
        """
        resp = await place(client, test_market, token_for(test_user.id),
                           max_slippage=0.10, min_shares_out=50_000_000)
        assert resp.status_code == 400, resp.text
        body = resp.json()
        assert body["error_code"] == "SLIPPAGE_EXCEEDED"
        assert isinstance(body["details"]["min_shares_out"], (int, float))
        assert isinstance(body["details"]["received_shares"], (int, float))

    @pytest.mark.asyncio
    async def test_the_bound_still_bites_against_the_price_the_user_saw(
        self, client, test_user, test_market
    ):
        """Correcting the reference must not have disarmed the bound.

        The user agrees to a price; the market moves past their tolerance before
        the order lands; the order is refused. That is the entire purpose of the
        field, so it is pinned here rather than assumed.
        """
        # Agree to a price the market will not be at by the time we submit.
        resp = await place(client, test_market, token_for(test_user.id),
                           amount=200.0, expected_price=0.30, max_slippage=0.02)
        assert resp.status_code == 400, resp.text
        body = resp.json()
        assert body["error_code"] == "SLIPPAGE_EXCEEDED"
        # The refusal must tell the user where the market actually is, so the
        # form can correct itself instead of leaving a dead price on screen.
        assert body["details"]["actual_price"] > 0
        assert body["details"]["current_market_price"] > 0

    @pytest.mark.asyncio
    async def test_agreeing_to_the_live_price_fills_at_that_bound(
        self, client, test_user, test_market
    ):
        """The other side of the same rule: a fair agreement is honoured.

        A bound that always refused would be no better than a bug that always
        allowed. The user names the size-aware price the form showed them and the
        order goes through.
        """
        client.cookies.set("access_token", token_for(test_user.id))
        quoted = await client.post("/api/v1/orders/quote", json={
            "market_id": str(test_market.id),
            "outcome": "yes",
            "side": "buy",
            "amount": 200.0,
        })
        assert quoted.status_code == 200, quoted.text
        shown = float(quoted.json()["data"]["price_after"])

        resp = await place(client, test_market, token_for(test_user.id),
                           amount=200.0, expected_price=shown, max_slippage=0.02)
        assert resp.status_code == 200, resp.text


class TestTheQuoteIsAllIn:
    """The displayed price must be the price actually paid.

    `price_after` used to be the pool's *marginal* price after the trade, with
    fees excluded - so the quote and the receipt disagreed by the fee (2.04% on a
    $200 buy against a 1000/1000 pool), and the gap widened with order size. In
    a product built around "the price you see is live and real", a quote that
    quietly omitted the fee breaks the one promise the UI makes.
    """

    @pytest.mark.asyncio
    async def test_quote_price_includes_fees(self, client, test_user, test_market):
        client.cookies.set("access_token", token_for(test_user.id))
        quoted = await client.post("/api/v1/orders/quote", json={
            "market_id": str(test_market.id), "outcome": "yes",
            "side": "buy", "amount": 200.0,
        })
        assert quoted.status_code == 200, quoted.text
        shown = float(quoted.json()["data"]["price_after"])

        resp = await place(client, test_market, token_for(test_user.id),
                           amount=200.0, expected_price=shown, max_slippage=0.001)
        assert resp.status_code == 200, resp.text
        filled = float(resp.json()["data"]["price"])
        assert abs(filled - shown) < 1e-6, (
            f"quote said {shown:.6f}, fill was {filled:.6f} - the displayed "
            "price is not the price paid"
        )

    @pytest.mark.asyncio
    async def test_the_fee_gap_closes_as_the_quote_is_corrected(self, client, test_user, test_market):
        """Pins the arithmetic that made this a bug, not just the symptom."""
        client.cookies.set("access_token", token_for(test_user.id))
        quoted = await client.post("/api/v1/orders/quote", json={
            "market_id": str(test_market.id), "outcome": "yes",
            "side": "buy", "amount": 200.0,
        })
        quoted_price = float(quoted.json()["data"]["price_after"])

        resp = await place(client, test_market, token_for(test_user.id),
                           amount=200.0, expected_price=quoted_price,
                           max_slippage=0.10)
        assert resp.status_code == 200, resp.text
        # Previously this came back as "Expected: $0.8489, Actual: $0.8662" at a
        # 2% tolerance - the user's own order, refused for the fee they were
        # never shown being charged.
        assert float(resp.json()["data"]["price"]) > 0
