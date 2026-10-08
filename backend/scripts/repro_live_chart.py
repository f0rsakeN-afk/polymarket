"""Reproduce the reported symptom against the *running* stack.

Places a real order over HTTP while a real WebSocket is attached, and reports
exactly which frames arrived. This is the seam the unit tests cannot reach: the
transport, the proxy config, the actual server process.

Usage: .venv/bin/python scripts/repro_live_chart.py [--market <slug>]
"""
import asyncio
import json
import sys

import httpx
import websockets
from sqlalchemy import select

from decimal import Decimal

from app.models.user import User
from app.models.wallet import Wallet

API = "http://localhost:8000"
WS = "ws://localhost:8000"


async def main() -> int:
    market_slug = None
    if "--market" in sys.argv:
        market_slug = sys.argv[sys.argv.index("--market") + 1]

    async with httpx.AsyncClient(base_url=API, timeout=30) as client:
        # --- find a tradable market -------------------------------------
        r = await client.get("/api/v1/markets/", params={"status": "active", "page_size": 5})
        if r.status_code != 200:
            print(f"FAIL listing markets: {r.status_code} {r.text[:300]}")
            return 1
        markets = r.json().get("data", [])
        if market_slug:
            markets = [m for m in markets if m["slug"] == market_slug]
        if not markets:
            print("FAIL no active market to test")
            return 1
        market = markets[0]
        market_id = market["id"]
        print(f"market   : {market['slug']}  id={market_id}")
        print(f"yes/no   : {market['yes_price']} / {market['no_price']}")

        # --- create + fund a throwaway trader ----------------------------
        import secrets
        email = f"repro_{secrets.token_hex(6)}@example.com"
        username = f"repro{secrets.token_hex(4)}"
        pw = f"Rp!{secrets.token_urlsafe(9)}"

        # The user is created directly rather than via /auth/register, which
        # returns `pending_verification` with no token and is rate limited. The
        # RefreshToken + Session pair below is exactly what login creates - a bare
        # JWT is rejected without a `sid` claim.
        sys.path.insert(0, ".")
        from datetime import datetime, timedelta, UTC
        import uuid

        from app.database import async_session
        from app.deps import create_access_token, hash_password
        from app.models.user import RefreshToken, Session
        from app.models.user import User as _User

        async with async_session() as db:
            user = _User(email=email, username=username,
                         password_hash=hash_password(pw), is_active=True,
                         is_email_verified=True)
            db.add(user)
            await db.flush()

            expires_at = datetime.now(UTC) + timedelta(days=7)
            rt = RefreshToken(id=uuid.uuid4(), user_id=user.id,
                              token_hash=uuid.uuid4().hex, expires_at=expires_at,
                              revoked=False, device_info="repro")
            db.add(rt)
            await db.flush()
            sess = Session(id=uuid.uuid4(), user_id=user.id,
                           refresh_token_id=rt.id, expires_at=expires_at,
                           revoked=False, user_agent="repro",
                           ip_address="127.0.0.1")
            db.add(sess)
            await db.flush()

            session_id = str(sess.id)
            user_id = str(user.id)
            await db.commit()

        tok, _ = create_access_token(user_id, session_id=session_id)
        client.cookies.set("access_token", tok)
        print(f"trader   : {username} (id={user_id})")

        # Fund the wallet directly - the repro cares about the live feed, not
        # about the deposit flow.
        async with async_session() as db:
            wallet = (
                await db.execute(select(Wallet).where(Wallet.user_id == user_id))
            ).scalar_one_or_none()
            if wallet is None:
                wallet = Wallet(user_id=user_id, balance=Decimal("100000"),
                               locked_balance=Decimal("0"))
                db.add(wallet)
            else:
                wallet.balance = Decimal("100000")
            await db.commit()
        print("funded   : 100000 USDC")

        # --- attach a real WebSocket BEFORE trading -----------------------
        frames: list[dict] = []
        done = asyncio.Event()

        async with websockets.connect(f"{WS}/ws/markets/{market_id}") as sock:
            async def reader():
                try:
                    async for raw in sock:
                        try:
                            frames.append(json.loads(raw))
                        except Exception:
                            frames.append({"type": "<unparseable>", "raw": str(raw)[:120]})
                except Exception:
                    pass
                done.set()

            task = asyncio.create_task(reader())
            await asyncio.sleep(0.5)  # let the handshake settle

            # --- place a MARKET order: must move the price ---------------
            print("\nplacing MARKET buy 40 USDC of the first outcome ...")
            out = market.get("outcomes") or []
            outcome = (out[0]["name"] if out else "Yes").lower()
            placed = await client.post("/api/v1/orders/", json={
                "market_id": market_id,
                "outcome": outcome,
                "side": "buy",
                "order_type": "market",
                "amount": 40.0,
            })
            if placed.status_code != 200:
                print(f"  order FAILED: {placed.status_code} {placed.text[:400]}")
            else:
                d = placed.json()["data"]
                print(f"  status={d['status']} order_id={d['order_id']}")
                print(f"  yes_price_after={d['yes_price_after']} no_price_after={d['no_price_after']}")

            await asyncio.sleep(1.5)
            task.cancel()

        # --- verdict -----------------------------------------------------
        kinds = [f.get("type") for f in frames]
        print(f"\nframes received: {len(frames)}  types={kinds}")

        price_frames = [f for f in frames if f.get("type") == "market:price_update"]
        chart_ok = bool(price_frames)
        print(f"  market:price_update  : {len(price_frames)}  -> chart moves: {chart_ok}")
        for f in price_frames:
            print(f"      yes={f.get('yes_price')} no={f.get('no_price')} "
                  f"outcomes={f.get('outcome_prices')}")
        print(f"  trade:new            : {len([f for f in frames if f.get('type') == 'trade:new'])}")
        print(f"  orderbook:update     : {len([f for f in frames if f.get('type') == 'orderbook:update'])}")

        # --- does the frame's price actually differ from the pre-trade one?
        moved = False
        if price_frames:
            before = float(market["yes_price"])
            after = float(price_frames[-1]["yes_price"])
            moved = after != before
            print(f"\n  before={before}  after={after}  moved={moved}")
            if not moved:
                print("  !! frame arrived but carried an UNCHANGED price - the chart")
                print("     would append a flat point and appear not to move.")

        print("\nVERDICT:", "OK - chart should move" if (chart_ok and moved) else "PROBLEM")
        return 0 if (chart_ok and moved) else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))