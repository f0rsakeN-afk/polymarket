"""A fill must reach the people whose money and shares actually moved.

`execute_order` publishes price, trades and the book to everyone watching the
*market*, and used to publish nothing at all to the users whose positions had
just changed. The per-user frames (`order:fill`, `position:update`, the
notification) existed only in `workers/tasks.py` - the 30-second limit-order
sweeper - so the synchronous path every real order takes never emitted them.

The visible failure is exactly the one people describe as "the WebSocket is
broken":

  - You buy someone's resting limit order. The market page updates instantly -
    that part worked. **Their** portfolio, orders and positions pages do not,
    because nothing was addressed to them. They see it on their next refetch.
  - Your own positions page, open in another tab, does not update either.
  - The maker's notification never arrives.

`match_details` already carried `maker_user_id`, `match_shares` and
`match_usdc` - it was read only to build Trade rows, and the participants were
discarded. These tests pin that they are addressed now.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
import pytest_asyncio
from conftest import token_for

D = Decimal


@pytest_asyncio.fixture
async def maker_user(db_session):
    """A second funded user, so a taker and a maker can be distinct people.

    The whole point of this file is that the *other* side of a trade has to be
    notified, so the tests need two identities rather than one user trading
    against their own book.
    """
    import uuid

    from conftest import create_login_session

    from app.deps import hash_password
    from app.models.user import User
    from app.models.wallet import Wallet

    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"maker_{uid}@example.com",
        username=f"maker_{uid}",
        password_hash=hash_password("Maker!Pass1"),
        is_email_verified=True,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(Wallet(user_id=user.id, balance="1000.00", locked_balance="0", currency="USDC"))
    # A token is only accepted when it carries the `sid` of a live session, so
    # the fixture has to mint one or the handshake is rejected as unauthenticated.
    await create_login_session(db_session, user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


class _Capture:
    """Records every private frame published during an order."""

    def __init__(self):
        self.fills: list[tuple[str, dict]] = []
        self.user_events: list[tuple[str, dict]] = []

    async def publish_order_fill(self, user_id, data):
        self.fills.append((str(user_id), data))

    async def publish_user_event(self, user_id, data):
        self.user_events.append((str(user_id), data))

    def users_with_fills(self) -> set[str]:
        return {uid for uid, _ in self.fills}

    def events_for(self, user_id: str) -> list[dict]:
        return [d for uid, d in self.user_events if uid == str(user_id)]


@pytest.fixture
def capture():
    cap = _Capture()
    with patch("app.services.order_service.redis_pubsub", cap):
        yield cap


async def _place(client, user_token, market, **overrides):
    payload = {
        "market_id": str(market.id),
        "outcome": "yes",
        "side": "buy",
        "order_type": "market",
        "amount": 10.0,
    }
    payload.update(overrides)
    client.cookies.set("access_token", user_token)
    return await client.post("/api/v1/orders/", json=payload)


@pytest.mark.asyncio
async def test_the_taker_is_told_about_their_own_fill(
    client, test_user, test_market, db_session, capture
):
    """The order you just placed must move your own positions immediately."""
    resp = await _place(client, token_for(test_user.id), test_market)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "filled"

    assert str(test_user.id) in capture.users_with_fills()

    # The fill frame carries enough to render without a refetch.
    fill = next(d for uid, d in capture.fills if uid == str(test_user.id))
    assert fill["market_id"] == str(test_market.id)
    assert fill["status"] == "filled"
    assert fill["shares"] > 0
    assert fill["role"] == "taker"
    assert fill["order_id"], "must reference the order so the list can key on it"

    # And a position frame, which is what the positions/portfolio caches
    # invalidate on. `publish_notification` would have overwritten its type and
    # this would never have arrived.
    events = capture.events_for(str(test_user.id))
    assert any(e.get("outcome") for e in events), (
        "expected a position frame for the taker"
    )


@pytest.mark.asyncio
async def test_the_maker_is_told_when_their_resting_order_is_hit(
    client, maker_user, test_user, test_market, db_session, capture
):
    """THE regression: a maker whose order was consumed must be notified.

    Two users, two tokens. The maker rests a sell that does not cross. The
    taker crosses it. The maker's positions, orders and wallet all changed, and
    before this fix nothing at all was published to them - they learned about it
    on their next page load, or never.

    The market page updated instantly the whole time. That is what made this
    read as "the socket is broken" rather than "we never notified the maker".
    """
    from app.models.position import Position

    token = token_for(maker_user.id)
    db_session.add(Position(
        user_id=maker_user.id,
        market_id=test_market.id,
        outcome_id=test_market.outcomes[0].id,
        shares_held=D("100"),
        average_price=D("0.5"),
        realized_pnl=D("0"),
    ))
    await db_session.commit()

    # Maker rests a sell above the pool price, so it does not fill instantly.
    rest = await _place(
        client, token, test_market,
        side="sell", order_type="limit", amount=10.0, price=0.80,
    )
    assert rest.status_code == 200, rest.text
    assert rest.json()["data"]["status"] in ("pending", "partial")

    # The taker crosses it.
    cross = await _place(
        client, token_for(test_user.id), test_market,
        side="buy", order_type="limit", amount=10.0, price=0.80,
    )
    assert cross.status_code == 200, cross.text

    maker_fills = [d for uid, d in capture.fills if uid == str(maker_user.id)]
    assert maker_fills, (
        "the maker's resting order was consumed and they were told nothing - "
        "their positions, orders and wallet are all stale until they refetch"
    )
    assert maker_fills[0]["market_id"] == str(test_market.id)
    assert maker_fills[0]["role"] == "maker"

    # And the maker's positions are told to refresh, not just their order list.
    assert capture.events_for(str(maker_user.id)), (
        "a maker whose shares were sold needs a position:update, or the "
        "positions page keeps showing shares they no longer hold"
    )


@pytest.mark.asyncio
async def test_cancelling_pushes_to_the_owners_own_sockets(
    client, test_user, test_market, db_session, capture
):
    """A cancel changes the user's balance and order row; say so immediately."""

    resp = await _place(
        client, token_for(test_user.id), test_market,
        order_type="limit", amount=10.0, price=0.10,
    )
    assert resp.status_code == 200, resp.text
    order_id = resp.json()["data"]["order_id"]

    client.cookies.set("access_token", token_for(test_user.id))
    cancel = await client.delete(f"/api/v1/orders/{order_id}")
    assert cancel.status_code == 200, cancel.text

    cancels = [d for _, d in capture.fills if d.get("status") == "cancelled"]
    assert cancels, "a cancelled order must reach the owner's sockets"
    assert cancels[0]["order_id"] == order_id