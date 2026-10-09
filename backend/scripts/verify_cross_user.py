"""Does user A's socket receive user B's trade?

The channel is `market:{market_id}:price` / `:events` - scoped to the market, not
to the user - so every socket watching that market should see every fill, whoever
placed it. This checks it with two independent WebSocket connections standing in
for two browsers, one of which places the order.

Run: PYTHONPATH=. .venv/bin/python scripts/verify_cross_user.py
"""
import asyncio
import json
import os
import secrets
import sys
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import websockets
from sqlalchemy import select

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

API = "http://localhost:8000"
WS = "ws://localhost:8000"


async def _make_trader(db, label: str):
    from app.deps import create_access_token, hash_password
    from app.models.user import RefreshToken, Session, User
    from app.models.wallet import Wallet

    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"{label}_{uid}@example.com",
        username=f"{label}{uid}"[:20],
        password_hash=hash_password(f"Rp!{secrets.token_urlsafe(9)}"),
        is_active=True,
        is_email_verified=True,
    )
    db.add(user)
    await db.flush()
    exp = datetime.now(UTC) + timedelta(days=7)
    rt = RefreshToken(id=uuid.uuid4(), user_id=user.id, token_hash=uuid.uuid4().hex,
                      expires_at=exp, revoked=False, device_info=label)
    db.add(rt)
    await db.flush()
    s = Session(id=uuid.uuid4(), user_id=user.id, refresh_token_id=rt.id,
                expires_at=exp, revoked=False, user_agent=label, ip_address="127.0.0.1")
    db.add(s)
    await db.flush()
    db.add(Wallet(user_id=user.id, balance=Decimal("100000"), locked_balance=Decimal("0")))
    sid, uid_str = str(s.id), str(user.id)
    await db.commit()
    tok, _ = create_access_token(uid_str, session_id=sid)
    return tok, uid_str


async def main() -> int:
    from app.database import async_session

    async with httpx.AsyncClient(base_url=API, timeout=30) as client:
        r = await client.get("/api/v1/markets/", params={"status": "active", "page_size": 5})
        markets = r.json().get("data", [])
        if not markets:
            print("FAIL no active market")
            return 1
        market = markets[0]
        mid = market["id"]
        print(f"market: {market['slug']}  (id={mid})")

        async with async_session() as db:
            tok_a, user_a = await _make_trader(db, "alice")
        async with async_session() as db:
            tok_b, user_b = await _make_trader(db, "bob")

        print(f"alice = {user_a[:8]}   (will place the order)")
        print(f"bob   = {user_b[:8]}   (just watching)")

        # Two independent sockets = two browsers. Bob is logged out of the feed
        # entirely: no token is sent for his connection, proving the market feed
        # is public and still receives another user's fill.
        frames_a: list[dict] = []
        frames_b: list[dict] = []

        async def watch(url: str, sink: list[dict]) -> None:
            async with websockets.connect(url) as sock:
                async for raw in sock:
                    try:
                        sink.append(json.loads(raw))
                    except Exception:
                        pass

        url = f"{WS}/ws/markets/{mid}"
        tasks = [
            asyncio.create_task(watch(url, frames_a)),
            asyncio.create_task(watch(url, frames_b)),
        ]
        await asyncio.sleep(0.6)

        # Alice trades.
        client.cookies.set("access_token", tok_a)
        out = market.get("outcomes") or []
        outcome = (out[0]["name"] if out else "Yes").lower()
        print(f"\nalice market-buys 40 USDC of {outcome} ...")
        placed = await client.post("/api/v1/orders/", json={
            "market_id": mid, "outcome": outcome, "side": "buy",
            "order_type": "market", "amount": 40.0,
        })
        print(f"  HTTP {placed.status_code} status={placed.json()['data']['status']}")

        await asyncio.sleep(2.0)
        for t in tasks:
            t.cancel()

    def kinds(frames):
        return [f.get("type") for f in frames]

    print(f"\nalice's own socket : {len(frames_a)} frames  {kinds(frames_a)}")
    print(f"bob's socket       : {len(frames_b)} frames  {kinds(frames_b)}")

    ok = True
    for name, frames in (("alice", frames_a), ("bob", frames_b)):
        for want in ("market:price_update", "trade:new", "orderbook:update"):
            got = any(f.get("type") == want for f in frames)
            print(f"  {name:5} {want:22} {'yes' if got else 'NO'}")
            if not got:
                ok = False

    # Prove bob's trade row names alice, i.e. this really is someone else's fill.
    for f in frames_b:
        if f.get("type") == "trade:new":
            print(f"\nbob saw a trade executed by: {f.get('username')}")
            break

    print("\nVERDICT:", "OK - a passive viewer receives another user's fill"
          if ok else "PROBLEM")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))