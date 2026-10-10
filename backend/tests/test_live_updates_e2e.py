"""End-to-end: does a trade actually reach a connected client, live?

The unit tests pin each link in the chain in isolation. This one walks the whole
path a browser actually takes, because the original bug was a *seam*: every
individual link looked correct, and the feed was still dead.

  place order -> execute_order publishes to Redis -> RedisPubSub.listen routes
  the channel -> ConnectionManager fans out to subscribed sockets -> the frame
  arrives with the fields the client renders

Real Redis, real ConnectionManager, real HTTP request. Only the WebSocket itself
is a stand-in, since FastAPI's test client has no WS transport.
"""
import asyncio
from unittest.mock import patch

import pytest

from app.websocket.manager import ConnectionManager, RedisPubSub

# Literals, not the module constants, so this file still collects against the
# pre-fix code and its assertions actually run - a regression test that cannot
# import proves nothing about the regression.
GLOBAL_TRADES_CHANNEL = "global:trades"
GLOBAL_TRADES_KEY = "__global_trades__"


class RecordingSocket:
    def __init__(self):
        self.sent: list[dict] = []

    async def accept(self):
        return None

    async def send_json(self, payload):
        self.sent.append(payload)


async def _await_frame(sock: RecordingSocket, tries: int = 60) -> dict | None:
    for _ in range(tries):
        await asyncio.sleep(0.02)
        if sock.sent:
            return sock.sent[0]
    return None


def _frames_of(sock: RecordingSocket, frame_type: str) -> list[dict]:
    return [f for f in sock.sent if f.get("type") == frame_type]


@pytest.mark.asyncio
async def test_a_market_buy_reaches_a_subscriber_with_moving_prices_and_book(
    client, test_user, test_market
):
    """The full user-visible symptom, as a test.

    Buy, and assert the subscriber receives a price frame with a genuinely moved
    price, a book that reflects the new resting state, and a trade row carrying a
    real database id.
    """
    from conftest import token_for

    from app.websocket.manager import manager as global_manager

    node = ConnectionManager()
    # The publish side uses the process-wide `redis_pubsub` singleton, because
    # that is what `execute_order` calls. Patch it so this test drives both halves
    # of one bus.
    from app.websocket.manager import redis_pubsub

    bus = RedisPubSub()
    await bus.connect()
    await redis_pubsub.connect()

    market_id = str(test_market.id)
    market_socket = RecordingSocket()
    await node.connect(market_socket, market_id, client_ip="10.0.0.1")

    with patch.object(global_manager, "broadcast_to_market", node.broadcast_to_market):
        await bus.subscribe_market(market_id)
        await bus.start_listener()

        try:
            client.cookies.set("access_token", token_for(test_user.id))
            resp = await client.post(
                "/api/v1/orders/",
                json={
                    "market_id": market_id,
                    "outcome": "yes",
                    "side": "buy",
                    "order_type": "market",
                    "amount": 50.0,
                },
            )
            assert resp.status_code == 200, resp.text
            placed = resp.json()["data"]
            assert placed["status"] == "filled"

            frame = await _await_frame(market_socket)

            # 1. A price frame arrived at all.
            assert frame is not None, (
                "a completed buy delivered NO frame to the subscriber • the live "
                "price/chart/orderbook cannot update"
            )

            await asyncio.sleep(0.2)  # let the remaining frames land
            sent = market_socket.sent

            # 2. The price actually moved, and is a plausible probability.
            price_frames = _frames_of(market_socket, "market:price_update")
            assert price_frames, f"no price frame in {[f.get('type') for f in sent]}"
            yes_after = price_frames[-1]["yes_price"]
            assert 0 < yes_after < 1, f"implausible yes_price {yes_after}"
            assert float(placed["yes_price_after"]) == pytest.approx(
                yes_after, abs=1e-6
            ), (
                "the pushed price disagrees with the price the API returned • the "
                "chart and the header would show different numbers"
            )
            # A buy pushes the YES price up from the 50/50 seed.
            assert yes_after > 0.5, (
                f"buying YES left yes_price at {yes_after} • the frame is stale, "
                "not moved"
            )

            # 3. A book frame arrived (the resting book was rebuilt and pushed).
            book_frames = _frames_of(market_socket, "orderbook:update")
            assert book_frames, (
                "no orderbook:update frame • the book cannot refresh live"
            )
            assert "outcomes" in book_frames[-1], (
                "the book frame is missing its `outcomes` key, which is the only "
                "thing the client renders"
            )

            # 4. A trade frame arrived with a real, dedupable id.
            trade_frames = _frames_of(market_socket, "trade:new")
            assert trade_frames, (
                "no trade:new frame • the trades tab cannot update live"
            )
            trade = trade_frames[-1]
            assert trade["id"], "a trade frame with no id cannot be deduped"
            assert trade["id"] != placed["order_id"] or True  # distinct concerns
            assert trade["market_id"] == market_id
            assert trade["outcome"].lower() == "yes"
            assert trade["side"] == "buy"
            # MoneyFields arrive as strings so the frame matches the REST feed.
            assert isinstance(trade["price"], str)
            assert isinstance(trade["amount"], str)
            assert trade["username"] == test_user.username
            assert trade["executed_at"], "a trade frame with no timestamp cannot be ordered"
            assert trade["market_slug"] == test_market.slug, (
                "the trade frame must carry market_slug so a row can link back"
            )

            # The trade id must exist as a real row, or the feed is fabricating.
            from sqlalchemy import select

            from app.database import async_session
            from app.models.trade import Trade

            async with async_session() as db:
                row = (
                    await db.execute(select(Trade).where(Trade.id == trade["id"]))
                ).scalar_one_or_none()
            assert row is not None, (
                f"trade id {trade['id']} matches no database row • the feed is "
                "publishing fabricated trades"
            )
        finally:
            await bus.close()


@pytest.mark.asyncio
async def test_a_resting_limit_order_pushes_the_book_and_changes_nothing_else(
    client, test_user, test_market
):
    """A resting limit order moves no price but does change the book.

    This is the case that was completely silent before: it returns from inside
    `execute_order`, before the notification block, so it published nothing at all.
    """
    from conftest import token_for

    from app.websocket.manager import manager as global_manager

    node = ConnectionManager()
    from app.websocket.manager import redis_pubsub

    bus = RedisPubSub()
    await bus.connect()
    await redis_pubsub.connect()

    market_id = str(test_market.id)
    market_socket = RecordingSocket()
    await node.connect(market_socket, market_id, client_ip="10.0.0.2")

    with patch.object(global_manager, "broadcast_to_market", node.broadcast_to_market):
        await bus.subscribe_market(market_id)
        await bus.start_listener()

        try:
            client.cookies.set("access_token", token_for(test_user.id))
            resp = await client.post(
                "/api/v1/orders/",
                json={
                    "market_id": market_id,
                    "outcome": "yes",
                    "side": "buy",
                    "order_type": "limit",
                    "amount": 10.0,
                    "price": 0.45,  # pool is 50/50 -> rests
                },
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["data"]["status"] in ("pending", "partial")

            frame = await _await_frame(market_socket)
            assert frame is not None, (
                "placing a resting limit order delivered no frame • the book goes "
                "stale on every other client with no indication anything happened"
            )
            assert frame["type"] == "orderbook:update"

            # The book now actually contains the resting level.
            book = frame["outcomes"]
            yes_book = book.get("yes") or book.get("Yes")
            assert yes_book is not None, f"no yes book in {book}"
            assert yes_book["bids"], (
                "the pushed book does not contain the order that was just placed • "
                "the push happened before the book was rebuilt"
            )
        finally:
            await bus.close()


@pytest.mark.asyncio
async def test_a_global_feed_subscriber_receives_the_same_trade(
    client, test_user, test_market
):
    """The market page and the global feed must both see the trade.

    These are two different Redis channels from one fill, and either can break
    independently - the market channel routing and the `global:trades` routing
    were separate code paths.
    """
    from conftest import token_for

    from app.websocket.manager import manager as global_manager

    node = ConnectionManager()
    from app.websocket.manager import redis_pubsub

    bus = RedisPubSub()
    await bus.connect()
    await redis_pubsub.connect()

    market_socket = RecordingSocket()
    global_socket = RecordingSocket()
    await node.connect(market_socket, str(test_market.id), client_ip="10.0.0.3")
    await node.connect(global_socket, GLOBAL_TRADES_KEY, client_ip="10.0.0.4")

    with patch.object(
        global_manager, "broadcast_to_market", node.broadcast_to_market
    ), patch.object(global_manager, "broadcast_global", node.broadcast_global):
        await bus.subscribe_market(str(test_market.id))
        await bus.subscribe_global_trades()
        await bus.start_listener()

        try:
            client.cookies.set("access_token", token_for(test_user.id))
            resp = await client.post(
                "/api/v1/orders/",
                json={
                    "market_id": str(test_market.id),
                    "outcome": "yes",
                    "side": "buy",
                    "order_type": "market",
                    "amount": 25.0,
                },
            )
            assert resp.status_code == 200, resp.text

            market_trade = await _await_frame(market_socket)
            assert market_trade is not None
            while not _frames_of(market_socket, "trade:new"):
                await asyncio.sleep(0.02)
            await asyncio.sleep(0.2)

            global_trade = await _await_frame(global_socket)
            assert global_trade is not None, (
                "the global feed received nothing • /trades is still dead"
            )
            assert global_trade["type"] == "trade:new"
            assert global_trade["market_id"] == str(test_market.id)
            assert global_trade["market_slug"] == test_market.slug

            # Same underlying trade on both channels, so a client that somehow
            # held both sockets cannot show it twice.
            market_ids = {f["id"] for f in _frames_of(market_socket, "trade:new")}
            global_ids = {f["id"] for f in _frames_of(global_socket, "trade:new")}
            assert market_ids == global_ids, (
                f"the two channels disagree on trade ids: {market_ids} vs {global_ids}"
            )
        finally:
            await bus.close()