"""
Locust load test for Polymarket backend.
Tests ALL API endpoints + WebSocket.

Usage:
    locust -f scripts/locustfile.py --host=http://localhost:8000

    # 500 users, 60s, headless:
    locust -f scripts/locustfile.py --host=http://localhost:8000 \
        --users=500 --spawn-rate=50 --run-time=60s --headless

    # REST API only (no WebSocket):
    locust -f scripts/locustfile.py --host=http://localhost:8000 \
        --users=500 --spawn-rate=50 --run-time=60s --headless \
        --class-picker RestAPIUser

    # WebSocket only:
    locust -f scripts/locustfile.py --host=http://localhost:8000 \
        --users=1000 --spawn-rate=100 --run-time=30s --headless \
        --class-picker WebSocketUser
"""
import random
import uuid

from locust import HttpUser, between, task
from locust.contrib.fasthttp import FastHttpUser


# ── Shared test user credentials ────────────────────────────────────────────────
_SHARED_EMAIL = "loadtest@example.com"
_SHARED_PASSWORD = "TstPsX79!bQ"
_cached_token = None
_cached_user_id = None
_auth_lock = None  # threading.Lock set lazily


def _ensure_auth(client):
    """Register (ignore 422) + login. Cached after first success — no stomping."""
    global _cached_token, _cached_user_id, _auth_lock
    import threading
    if _auth_lock is None:
        _auth_lock = threading.Lock()

    if _cached_token:
        return _cached_token, _cached_user_id

    with _auth_lock:
        # Double-check after acquiring lock
        if _cached_token:
            return _cached_token, _cached_user_id
        client.post("/api/v1/auth/register", json={
            "email": _SHARED_EMAIL,
            "username": f"lt_{uuid.uuid4().hex[:8]}",
            "password": _SHARED_PASSWORD,
        })
        resp = client.post("/api/v1/auth/login", json={
            "email": _SHARED_EMAIL,
            "password": _SHARED_PASSWORD,
        })
        if resp.status_code == 200:
            d = resp.json()
            _cached_token = d.get("access_token")
            _cached_user_id = d.get("user_id")
            return _cached_token, _cached_user_id
        return None, None


def _get_active_market(client):
    """Try to get a real active market slug."""
    resp = client.get("/api/v1/markets?status=active&page=1&page_size=10")
    if resp.status_code == 200:
        markets = resp.json().get("markets", [])
        if markets:
            return random.choice(markets)
    return None


class APIBase(FastHttpUser):
    abstract = True
    wait_time = between(0.05, 0.3)
    token = None
    user_id = None

    def on_start(self):
        self.token, self.user_id = _ensure_auth(self.client)

    def headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}


# ══════════════════════════════════════════════════════════════════════════════
# FULL API TEST USER — tests every endpoint
# ══════════════════════════════════════════════════════════════════════════════

class RestAPIUser(APIBase):
    """Tests all public + authenticated endpoints."""

    # ── Public endpoints ────────────────────────────────────────────────────────

    @task(8)
    def list_markets(self):
        """GET /markets — paginated market list, most common endpoint."""
        self.client.get("/api/v1/markets?page=1&page_size=20")

    @task(5)
    def list_markets_filtered(self):
        """GET /markets with filters — tests different query combos."""
        filters = [
            "status=active",
            "status=closed",
            "category=politics",
            "sort=volume",
            "sort=closing_soon",
            "q=bitcoin",
        ]
        q = random.choice(filters)
        self.client.get(f"/api/v1/markets?{q}&page=1&page_size=20")

    @task(4)
    def get_market_detail(self):
        """GET /markets/{slug} — market detail page."""
        m = _get_active_market(self.client)
        if m:
            self.client.get(f"/api/v1/markets/{m['slug']}")

    @task(3)
    def get_orderbook(self):
        """GET /markets/{slug}/orderbook."""
        m = _get_active_market(self.client)
        if m:
            self.client.get(f"/api/v1/markets/{m['slug']}/orderbook")

    @task(3)
    def get_trades(self):
        """GET /markets/{slug}/trades — public trade feed."""
        m = _get_active_market(self.client)
        if m:
            self.client.get(f"/api/v1/markets/{m['slug']}/trades")

    @task(2)
    def get_market_faqs(self):
        m = _get_active_market(self.client)
        if m:
            self.client.get(f"/api/v1/markets/{m['slug']}/faqs")

    @task(2)
    def get_related_markets(self):
        m = _get_active_market(self.client)
        if m:
            self.client.get(f"/api/v1/markets/{m['slug']}/related")

    @task(2)
    def get_market_activity(self):
        m = _get_active_market(self.client)
        if m:
            self.client.get(f"/api/v1/markets/{m['slug']}/activity")

    @task(1)
    def get_comments(self):
        m = _get_active_market(self.client)
        if m:
            self.client.get(f"/api/v1/markets/{m['slug']}/comments")

    @task(1)
    def get_global_trades(self):
        """GET /trades — global trade feed."""
        self.client.get("/api/v1/trades?page=1&page_size=20")

    # ── Authenticated endpoints ───────────────────────────────────────────────

    @task(3)
    def get_positions(self):
        """GET /positions — portfolio view."""
        self.client.get("/api/v1/positions", headers=self.headers())

    @task(2)
    def get_orders(self):
        """GET /orders — user's order history."""
        self.client.get("/api/v1/orders?page=1&page_size=20", headers=self.headers())

    @task(2)
    def get_wallet(self):
        """GET /wallet — balance check."""
        self.client.get("/api/v1/wallet", headers=self.headers())

    @task(1)
    def get_referral_code(self):
        """GET /referrals/code."""
        self.client.get("/api/v1/referrals/code", headers=self.headers())

    @task(1)
    def get_referral_stats(self):
        self.client.get("/api/v1/referrals/stats", headers=self.headers())

    @task(1)
    def get_alerts(self):
        """GET /alerts."""
        self.client.get("/api/v1/alerts", headers=self.headers())

    @task(1)
    def get_transactions(self):
        """GET /wallet/transactions."""
        self.client.get("/api/v1/wallet/transactions?page=1&page_size=20", headers=self.headers())

    # ── Write endpoints (may fail with 4xx, but we test the path) ────────────

    @task(1)
    def place_order(self):
        """POST /orders — market order (will 400 without wallet balance, but tests the path)."""
        m = _get_active_market(self.client)
        if not m:
            return
        outcomes = m.get("outcomes", [])
        if not outcomes:
            return
        self.client.post(
            "/api/v1/orders",
            json={
                "market_id": m["id"],
                "outcome": outcomes[0] if len(outcomes) > 1 else "YES",
                "side": random.choice(["buy", "sell"]),
                "amount": "1.00",
                "order_type": "market",
                "client_order_id": f"locust_{uuid.uuid4().hex[:8]}",
            },
            headers=self.headers(),
        )

    @task(1)
    def place_limit_order(self):
        """POST /orders — limit order."""
        m = _get_active_market(self.client)
        if not m:
            return
        outcomes = m.get("outcomes", [])
        if not outcomes:
            return
        self.client.post(
            "/api/v1/orders",
            json={
                "market_id": m["id"],
                "outcome": outcomes[0] if len(outcomes) > 1 else "YES",
                "side": "buy",
                "amount": "10.00",
                "price": "0.50",
                "order_type": "limit",
                "client_order_id": f"locust_{uuid.uuid4().hex[:8]}",
            },
            headers=self.headers(),
        )

    @task(1)
    def create_alert(self):
        """POST /alerts — price alert."""
        m = _get_active_market(self.client)
        if not m:
            return
        self.client.post(
            "/api/v1/alerts",
            json={
                "market_id": m["id"],
                "outcome": "yes",
                "condition": random.choice(["above", "below"]),
                "trigger_price": random.choice(["0.30", "0.50", "0.70"]),
            },
            headers=self.headers(),
        )

    @task(1)
    def add_comment(self):
        """POST /markets/{slug}/comments."""
        m = _get_active_market(self.client)
        if not m:
            return
        self.client.post(
            f"/api/v1/markets/{m['slug']}/comments",
            json={"content": f"Load test comment {uuid.uuid4().hex[:6]}"},
            headers=self.headers(),
        )

    @task(1)
    def create_referral_code(self):
        """GET /referrals/code (creates if missing)."""
        self.client.get("/api/v1/referrals/code", headers=self.headers())


# ══════════════════════════════════════════════════════════════════════════════
# WEB SOCKET USER — holds persistent connections
# ══════════════════════════════════════════════════════════════════════════════

class WebSocketUser(HttpUser):
    """
    WebSocket load tester — each user maintains a long-lived WS connection.
    Tests real-time event delivery at scale.
    """
    abstract = True
    wait_time = between(2, 8)  # stay connected 2-8s between reconnects


class MarketWSUser(WebSocketUser):
    """Subscribes to a market's real-time feed."""

    @task
    def market_feed(self):
        import websocket
        import json

        # Try to get a real active market slug
        resp = self.client.get("/api/v1/markets?status=active&page=1&page_size=5")
        market_id = "global"  # fallback
        if resp.status_code == 200:
            markets = resp.json().get("markets", [])
            if markets:
                market_id = markets[0]["slug"]

        ws_url = f"ws://localhost:8000/ws/markets/{market_id}"
        try:
            ws = websocket.create_connection(ws_url, timeout=10)
            ws.send(json.dumps({"type": "subscribe", "market_id": market_id}))

            # Stay connected and receive updates for a few seconds
            for _ in range(random.randint(5, 15)):
                try:
                    msg = ws.recv()
                except Exception:
                    break
            ws.close()
        except Exception:
            pass


class GlobalTradesWSUser(WebSocketUser):
    """Subscribes to global trade feed."""

    @task
    def global_feed(self):
        import websocket
        import json

        try:
            ws = websocket.create_connection("ws://localhost:8000/ws/trades", timeout=10)
            ws.send(json.dumps({"type": "ping"}))

            for _ in range(random.randint(3, 8)):
                try:
                    ws.recv()
                except Exception:
                    break
            ws.close()
        except Exception:
            pass
