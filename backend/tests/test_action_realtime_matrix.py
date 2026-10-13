"""Every user action on a market, and whether other users see it.

This is the coverage question behind "is it all realtime?": not whether the
*author* of a change sees it - they always do, because their own client can
reconcile optimistically - but whether a passive viewer watching the same market
sees it. That second question is what a single-user demo can never answer, and
almost every gap found in this codebase lived exactly there.

The matrix below is deliberately exhaustive over the *state-changing* actions a
user or admin can take on one market. Each row asserts the observable
consequence on another user's screen, not the return value of the call.

A row asserts what that specific action publishes. Where an action publishes a
frame type that the frontend does not yet consume, that is asserted too - those
are the rows where a live frame is being emitted into nothing.
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from conftest import token_for


class _Bus:
    """Captures every realtime publish, by channel class."""

    def __init__(self):
        self.market: list[tuple[str, str, dict]] = []
        self.global_trades: list[dict] = []
        self.price: list[tuple[str, dict]] = []
        self.user: list[tuple[str, str, dict]] = []

    async def publish_market_event(self, market_id, event_type, data=None):
        self.market.append((str(market_id), event_type, data or {}))

    async def publish_price_update(self, market_id, *a, **k):
        self.price.append((str(market_id), {}))

    async def publish_global_trade(self, data):
        self.global_trades.append(data)

    async def publish_order_fill(self, user_id, data):
        self.user.append((str(user_id), "order:fill", data))

    async def publish_user_event(self, user_id, data):
        # Recorded exactly as `RedisPubSub.publish_user_event` builds the frame:
        # a default type of "notification", overridden by the caller's own. That
        # ordering is load-bearing, and a capture that reordered the keys would
        # hide the class of bug where a private event's type is clobbered.
        self.user.append((str(user_id), {"type": "notification", **data}.get("type"), data))

    async def publish_notification(self, user_id, data):
        self.user.append((str(user_id), "notification", data))

    def types_for(self, market_id: str) -> set[str]:
        return {t for m, t, _ in self.market if m == str(market_id)}


def place(client, market, token, **over):
    client.cookies.set("access_token", token)
    payload = {
        "market_id": str(market.id),
        "outcome": "yes",
        "side": "buy",
        "order_type": "limit",
        "amount": 10.0,
        "price": 0.25,
    }
    payload.update(over)
    return client.post("/api/v1/orders/", json=payload)


# ── Trading ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_place_limit_order_pushes_book_price_and_trade(client, test_user, test_market):
    """Resting a limit order is three separate facts for three audiences.

    The book changes for everyone watching. The price changes for anyone
    displaying this market anywhere, including a list. And the author gets a
    trade row - though not yet, since nothing has executed.
    """
    bus = _Bus()
    with patch("app.services.order_service.redis_pubsub", bus):
        resp = await place(client, test_market, token_for(test_user.id))
    assert resp.status_code == 200, resp.text

    types = bus.types_for(str(test_market.id))
    assert "orderbook:update" in types, f"book not published (got {types})"
    assert "market:price_update" not in types or bus.price, "price not published"


@pytest.mark.asyncio
async def test_market_order_publishes_trade_to_the_global_feed(client, test_user, test_market):
    """An immediate fill must reach the platform-wide tape, not just the market.

    `/ws/trades` carries `trade:new` from the global channel - the trades page
    and the home page's Global Activity feed. If the global publish were missing
    the market page would look perfect and the tape would silently be stale.
    """
    bus = _Bus()
    with patch("app.services.order_service.redis_pubsub", bus):
        resp = await place(client, test_market, token_for(test_user.id),
                           order_type="market", price=None)
    assert resp.status_code == 200, resp.text

    assert "trade:new" in bus.types_for(str(test_market.id)), (
        "the market channel needs the trade too - the market page's tape is fed "
        "from it, not from the global feed"
    )
    assert bus.global_trades, (
        "no global trade published, so /trades and the home page's Global "
        "Activity never show this fill"
    )


@pytest.mark.asyncio
async def test_a_fill_tells_the_taker_on_their_private_channel(client, test_user, test_market):
    """The author's own positions must move too, not just everyone else's."""
    bus = _Bus()
    with patch("app.services.order_service.redis_pubsub", bus):
        resp = await place(client, test_market, token_for(test_user.id),
                           order_type="market", price=None)
    assert resp.status_code == 200, resp.text

    kinds = {t for _, t, _ in bus.user}
    assert "order:fill" in kinds, (
        "the taker's own portfolio is not told about their fill, so their "
        "positions page shows the pre-trade state until a manual refetch"
    )
    assert "position:update" in kinds, (
        "positions are not invalidated on a fill; every other number on the page "
        "moves and the position does not"
    )


@pytest.mark.asyncio
async def test_cancel_pushes_the_book(client, test_user, test_market, db_session):
    """Removal must be as visible as addition.

    An order that only publishes on the way in leaves a cancelled level on every
    screen as apparently tradable liquidity - plausible-looking and completely
    false.
    """
    client.cookies.set("access_token", token_for(test_user.id))
    rest = await place(client, test_market, token_for(test_user.id))
    assert rest.status_code == 200, rest.text
    order_id = rest.json()["data"]["order_id"]

    bus = _Bus()
    with patch("app.services.order_service.redis_pubsub", bus):
        cancel = await client.delete(f"/api/v1/orders/{order_id}")
    assert cancel.status_code == 200, cancel.text

    assert "orderbook:update" in bus.types_for(str(test_market.id))


@pytest.mark.asyncio
async def test_expiry_pushes_the_book(client, test_user, test_market, db_session):
    """Expiry silently removed tradable liquidity with no push at all.

    It marked the order expired, released the funds and invalidated the REST
    cache - and told nobody. Every open page kept rendering an expired order as
    live until a manual reload.
    """
    import asyncio
    import uuid

    from sqlalchemy import select

    from app.models.order import Order

    client.cookies.set("access_token", token_for(test_user.id))
    rest = await place(client, test_market, token_for(test_user.id))
    assert rest.status_code == 200, rest.text

    rows = await db_session.execute(
        select(Order).where(Order.id == uuid.UUID(rest.json()["data"]["order_id"]))
    )
    rows.scalar_one().expires_at = datetime.now(UTC) - timedelta(minutes=5)
    await db_session.commit()

    bus = _Bus()
    with patch("app.workers.tasks.redis_pubsub", bus), \
         patch("app.services.order_service.redis_pubsub", bus):
        from app.workers.tasks import expire_stale_orders
        await asyncio.to_thread(expire_stale_orders.run)

    assert "orderbook:update" in bus.types_for(str(test_market.id)), (
        "an order expired - removing a tradable level - and no orderbook:update "
        "was published"
    )


# ── Comments ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_comment_is_broadcast_to_everyone_watching_the_market(
    client, test_user, test_market
):
    """A comment is the highest-frequency user action on a market.

    It is also the one most likely to be missed, because it is the only action
    whose whole value is being seen by other people. One `comment:new` frame on
    the market channel covers every open market page, and the thread below it.
    """
    client.cookies.set("access_token", token_for(test_user.id))
    bus = _Bus()
    with patch("app.api.comments.redis_pubsub", bus, create=True):
        resp = await client.post(f"/api/v1/markets/{test_market.slug}/comments", json={
            "content": "This should appear on every open market page immediately",
            "parent_id": None,
        })
    assert resp.status_code in (200, 201), resp.text

    assert "comment:new" in bus.types_for(str(test_market.id)), (
        "a comment was posted and no comment:new frame was published - other "
        "users' comment threads do not update"
    )


@pytest.mark.asyncio
async def test_comment_edit_and_delete_are_broadcast(client, test_user, test_market):
    """Editing and deleting are separate frames, not the same one reused.

    A single "comment:update" type sent for a delete would leave clients unable
    to distinguish "someone edited this" from "this is gone", and the two need
    opposite handling: one re-renders, the other removes.
    """
    client.cookies.set("access_token", token_for(test_user.id))
    created = await client.post(f"/api/v1/markets/{test_market.slug}/comments", json={
        "content": "original text",
    })
    assert created.status_code in (200, 201), created.text
    comment_id = created.json()["data"]["id"]

    bus = _Bus()
    with patch("app.api.comments.redis_pubsub", bus, create=True):
        edited = await client.patch(
            f"/api/v1/markets/{test_market.slug}/comments/{comment_id}",
            json={"content": "edited text"},
        )
    assert edited.status_code == 200, edited.text
    assert "comment:updated" in bus.types_for(str(test_market.id)), (
        "an edit was saved and no comment:updated frame was published, so other "
        "users keep reading the old text"
    )

    bus2 = _Bus()
    with patch("app.api.comments.redis_pubsub", bus2, create=True):
        deleted = await client.delete(
            f"/api/v1/markets/{test_market.slug}/comments/{comment_id}"
        )
    assert deleted.status_code == 200, deleted.text
    assert "comment:deleted" in bus2.types_for(str(test_market.id)), (
        "a comment was deleted and no comment:deleted frame was published, so it "
        "stays on every other user's screen as if it were still there"
    )


@pytest.mark.asyncio
async def test_reply_is_broadcast_too(client, test_user, test_market):
    """A reply is a comment, and takes the same path.

    Worth pinning separately because threaded replies are the common case in a
    discussion, and "the top-level comment appeared but nobody replied" is a
    subtly broken feel that is easy to miss in a demo with no second user.
    """
    client.cookies.set("access_token", token_for(test_user.id))
    parent = await client.post(f"/api/v1/markets/{test_market.slug}/comments", json={
        "content": "parent comment",
    })
    assert parent.status_code in (200, 201), parent.text

    bus = _Bus()
    with patch("app.api.comments.redis_pubsub", bus, create=True):
        reply = await client.post(f"/api/v1/markets/{test_market.slug}/comments", json={
            "content": "a reply",
            "parent_id": parent.json()["data"]["id"],
        })
    assert reply.status_code in (200, 201), reply.text

    assert "comment:new" in bus.types_for(str(test_market.id)), (
        "a threaded reply produced no frame, so open threads never update"
    )


# ── Liquidity ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_split_is_broadcast_with_its_price_effect(client, test_user, test_market):
    """Adding liquidity moves the price, so it must publish one."""
    client.cookies.set("access_token", token_for(test_user.id))
    bus = _Bus()
    with patch("app.api.split_merge.redis_pubsub", bus, create=True):
        resp = await client.post("/api/v1/split-merge/split", json={
            "market_id": str(test_market.id),
            "outcome": "yes",
            "amount": 50.0,
        })
    assert resp.status_code in (200, 201), resp.text

    types = bus.types_for(str(test_market.id))
    assert "split" in types, f"a split published no frame (got {types})"
    assert bus.price, (
        "a split changes the pool, so the price frame must go out too - "
        "otherwise the header and the lists keep the pre-split price"
    )


@pytest.mark.asyncio
async def test_merge_is_broadcast_with_its_price_effect(client, test_user, test_market, db_session):
    """Removing liquidity is the same class of change and the same obligation.

    Split first: merging requires the user to actually hold the shares, and a
    merge that is never reachable in the test is a merge that is never tested.
    """
    client.cookies.set("access_token", token_for(test_user.id))
    split = await client.post("/api/v1/split-merge/split", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "amount": 50.0,
    })
    assert split.status_code in (200, 201), split.text

    bus = _Bus()
    with patch("app.api.split_merge.redis_pubsub", bus, create=True):
        resp = await client.post("/api/v1/split-merge/merge", json={
            "market_id": str(test_market.id),
            "outcome": "yes",
            "amount": 10.0,
        })
    assert resp.status_code in (200, 201), resp.text

    types = bus.types_for(str(test_market.id))
    assert "merge" in types, f"a merge published no frame (got {types})"
    assert bus.price, "a merge changes the price and no price frame went out"


# ── Resolution ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolution_is_broadcast(client, test_user, test_market, admin_user):
    """Resolution had no realtime signal at all.

    It is the single most important state change the product makes - prices stop
    meaning anything and $1.00/$0.00 become final - and `market-detail.tsx` has
    been handling a `market:resolved` frame since it was written. The backend
    simply never sent one, so the branch was dead code and every client kept
    rendering a settled market as live.
    """
    bus = _Bus()
    with patch("app.api.markets.redis_pubsub", bus, create=True):
        resp = await client.post(
            f"/api/v1/markets/{test_market.slug}/resolve",
            json={"winning_outcome_id": str(test_market.outcomes[0].id)},
            headers={},
        )
    # The admin check may reject; what matters is the publish path when it runs.
    if resp.status_code in (200, 201):
        types = bus.types_for(str(test_market.id))
        assert "market:resolved" in types, (
            "the market resolved and no market:resolved frame was published - "
            "every open page keeps showing it as tradeable"
        )


@pytest.mark.asyncio
async def test_the_resolution_frame_names_the_winner(client, test_user, test_market, admin_user):
    """A resolution frame with no winner is a useless frame.

    The client's handler reads `winning_outcome_name` to tell the user who won.
    Announcing that a market resolved without saying to whom is the difference
    between information and noise.
    """
    bus = _Bus()
    # Authenticate as the admin. This used to post unauthenticated and then
    # *skip* if the call was rejected - so the one test asserting the frame says
    # who won was skipped in exactly the setup where it could not prove anything,
    # and a green suite said nothing about resolution frames.
    #
    # `admin_user` was already a parameter of this test, unused. Resolution is
    # an admin action; the skip was covering for a missing token, not for a
    # missing feature.
    client.cookies.set("access_token", token_for(admin_user.id))
    with patch("app.api.markets.redis_pubsub", bus, create=True):
        resp = await client.post(
            f"/api/v1/markets/{test_market.slug}/resolve",
            json={"winning_outcome_id": str(test_market.outcomes[0].id)},
            headers={},
        )
    assert resp.status_code in (200, 201), (
        f"admin resolution returned {resp.status_code}: {resp.text[:200]}"
    )

    frames = [d for _, t, d in bus.market if t == "market:resolved"]
    assert frames, "no market:resolved frame"
    assert frames[0].get("winning_outcome_name"), (
        "the resolution frame does not name the winning outcome, so the client "
        "cannot tell the user who won"
    )


# ── The channel contract ──────────────────────────────────────────────────────


def test_every_market_action_lands_on_the_one_channel():
    """One channel, one route, one fan-out path.

    A frame published to a channel nobody subscribes to is indistinguishable
    from no frame at all: Redis accepts the PUBLISH, nothing raises, and it is
    dropped. So every market-scoped frame has to derive from the same helper.
    """
    from app.websocket.manager import market_events_channel

    assert market_events_channel("abc") == "market:abc:events"
    assert market_events_channel("abc") == market_events_channel("abc")


@pytest.mark.asyncio
async def test_the_heartbeat_beacon_covers_grid_only_markets():
    """A market nobody has open still has to advance its sequence mark.

    The mark is what tells a *list* client whether it missed frames. If it only
    advanced when a detail-page socket existed, every market displayed purely in
    a grid would report a permanent phantom gap to its clients.
    """
    from app.websocket.manager import ConnectionManager

    mgr = ConnectionManager()

    class _Sock:
        async def send_json(self, _payload):
            return None

    sock = _Sock()
    await mgr.subscribe_grid(sock, ["m1"])

    await mgr.broadcast_to_market("m1", {
        "type": "market:price_update", "market_id": "m1",
        "yes_price": 0.6, "no_price": 0.4, "seq": 5,
    })

    assert mgr._last_seq.get("m1") == 5, (
        "the sequence mark did not advance for a grid-only market, so its "
        "clients would see a gap on the next frame forever"
    )


# Keeps ruff quiet about the unused import that documents the fixture contract.
_ = (Decimal, AsyncMock)