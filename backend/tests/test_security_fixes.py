"""Regression tests for the security fixes in auth / websocket / middleware / OTP.

Each test pins one behaviour that used to be broken:

1. WebSocket accepted tokens after their session was revoked or the token
   was blacklisted (signature-only check).
2. X-Forwarded-For was honoured even with no configured trusted proxy, so a
   client could rotate fake IPs and slip past every rate limit.
3. OTP codes were written to Redis in plaintext next to their hash.
4. The Origin allowlist only ran when app_env == "production".
5. Unknown-user logins returned faster than known-user ones (enumeration).
6. AMM (non-book) fills on a BUY wrote no Trade row, and total_volume mixed
   USDC with share counts.
"""
import json
from decimal import Decimal

import pytest
from conftest import token_for
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.testclient import TestClient, WebSocketDisconnect

# ── 0. Local WS client (same shape as the one in test_websocket.py) ───────────


@pytest.fixture
def ws_client():
    """Synchronous WS client; mocks the module-level redis_pubsub publisher."""
    from unittest.mock import AsyncMock, patch

    from app.app import app

    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_market = AsyncMock()
        mock_pubsub.subscribe_global_trades = AsyncMock()
        mock_pubsub.subscribe_user = AsyncMock()
        yield TestClient(app)


# ── 1. WebSocket auth parity with HTTP ────────────────────────────────────────


@pytest.mark.asyncio
async def test_websocket_rejects_revoked_session(ws_client, test_user, db_session):
    """A token whose session was revoked must not open a websocket."""
    from app.models.user import Session

    token = token_for(test_user.id)
    from conftest import _BOUND_SESSIONS

    session = await db_session.get(Session, _BOUND_SESSIONS[str(test_user.id)])
    session.revoked = True
    await db_session.commit()

    with pytest.raises(WebSocketDisconnect) as exc:
        with ws_client.websocket_connect(f"/ws/trades?token={token}"):
            pass
    assert exc.value.code == 1008


@pytest.mark.asyncio
async def test_websocket_rejects_blacklisted_token(ws_client, test_user, db_session):
    """Logout-blacklisted jti must be rejected on the WS handshake too."""
    from conftest import _BOUND_SESSIONS

    from app.deps import blacklist_token, create_access_token

    token, jti = create_access_token(
        str(test_user.id), session_id=_BOUND_SESSIONS[str(test_user.id)]
    )
    await blacklist_token(jti, 3600)

    with pytest.raises(WebSocketDisconnect) as exc:
        with ws_client.websocket_connect(f"/ws/trades?token={token}"):
            pass
    assert exc.value.code == 1008


@pytest.mark.asyncio
async def test_websocket_query_token_is_gated_off_by_default(ws_client, test_user, monkeypatch):
    """`?token=` puts a live JWT into URLs — proxy logs, browser history and
    Referer headers all keep it. It stays a legacy fallback that must be
    switched on with WS_ALLOW_QUERY_TOKEN=true; with it off (the shipped
    default) a *valid* token in the query string is rejected, while the
    supported cookie path keeps working."""
    from app.config import settings

    monkeypatch.setattr(settings, "ws_allow_query_token", False)
    token = token_for(test_user.id)

    with pytest.raises(WebSocketDisconnect) as exc:
        with ws_client.websocket_connect(f"/ws/trades?token={token}"):
            pass
    assert exc.value.code == 1008

    # Same token, cookie path — accepted.
    ws_client.cookies.set("access_token", token)
    with ws_client.websocket_connect("/ws/trades"):
        pass


# ── 2. X-Forwarded-For fail-closed ────────────────────────────────────────────

def _request_with_xff(direct_ip: str, forwarded: str | None) -> Request:
    headers = []
    if forwarded:
        headers.append((b"x-forwarded-for", forwarded.encode()))
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/v1/markets",
            "raw_path": b"/api/v1/markets",
            "query_string": b"",
            "root_path": "",
            "headers": headers,
            "client": (direct_ip, 12345),
            "server": ("testserver", 80),
        }
    )


def test_xff_ignored_without_trusted_proxy(monkeypatch):
    """No TRUSTED_PROXY_IPS → the spoofable header is discarded."""
    import app.api.middleware as mw

    monkeypatch.setattr(mw, "_TRUSTED_PROXIES", [])
    # spoofed XFF, real peer 203.0.113.7
    assert mw._get_client_ip(_request_with_xff("203.0.113.7", "1.2.3.4")) == "203.0.113.7"
    # header absent → same answer (nothing changes silently)
    assert mw._get_client_ip(_request_with_xff("203.0.113.7", None)) == "203.0.113.7"


def test_xff_honoured_from_configured_proxy(monkeypatch):
    """When the direct peer IS the proxy, the first XFF hop is the client."""
    import app.api.middleware as mw

    monkeypatch.setattr(mw, "_TRUSTED_PROXIES", ["10.0.0.2"])
    assert (
        mw._get_client_ip(_request_with_xff("10.0.0.2", "1.2.3.4, 10.0.0.2")) == "1.2.3.4"
    )
    # ...but an untrusted peer still cannot smuggle a header through.
    assert (
        mw._get_client_ip(_request_with_xff("198.51.100.9", "1.2.3.4")) == "198.51.100.9"
    )


# ── 3. OTP storage is hash-only ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_otp_plaintext_never_stored_in_redis():
    """Redis must hold an HMAC of the code, never the code itself."""
    from app.redis import get_redis
    from app.services.otp_service import OTPService

    email = "hash_only@example.com"
    purpose = "verify"
    code = await OTPService.send_code(email, purpose)

    r = await get_redis()
    stored = await r.get(f"otp:{purpose}:{email}")
    assert stored is not None
    if isinstance(stored, bytes):
        stored = stored.decode()

    assert code not in stored, "plaintext OTP leaked into Redis"
    assert len(stored) == 64, "expected a bare SHA-256 hex digest"

    # ...and verification still works, then burns the code.
    assert await OTPService.verify_code(email, purpose, code) is True
    assert await OTPService.verify_code(email, purpose, code) is False


# ── 4. Origin allowlist runs in every environment ─────────────────────────────


def _middleware_scope(origin: str | None) -> dict:
    headers = [(b"origin", origin.encode())] if origin else []
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/v1/markets",
        "raw_path": b"/api/v1/markets",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("203.0.113.7", 12345),
        "server": ("testserver", 80),
    }


async def test_origin_allowlist_applies_outside_production(monkeypatch):
    """The Origin check must not be disabled by app_env."""
    from app.api.middleware import RateLimitMiddleware
    from app.config import settings

    monkeypatch.setattr(settings, "app_env", "development")
    middleware = RateLimitMiddleware(lambda scope, receive, send: None, enabled=True)

    async def call_next(_request):
        return PlainTextResponse("ok")

    blocked = await middleware.dispatch(
        Request(_middleware_scope("https://evil.example")), call_next
    )
    assert blocked.status_code == 403
    assert json.loads(bytes(blocked.body))["error_code"] == "ORIGIN_NOT_ALLOWED"

    allowed = await middleware.dispatch(
        Request(_middleware_scope("http://localhost:3000")), call_next
    )
    assert allowed.status_code == 200

    # Browsers omit Origin on same-origin GETs and non-browser clients never
    # send it — those requests must not be collateral damage.
    no_origin = await middleware.dispatch(Request(_middleware_scope(None)), call_next)
    assert no_origin.status_code == 200


# ── 5. Login timing equalisation ──────────────────────────────────────────────


def test_dummy_password_hash_is_cached_bcrypt():
    """The unknown-user bcrypt work must use one stable, real bcrypt hash."""
    from app.deps import dummy_password_hash, verify_password

    first = dummy_password_hash()
    second = dummy_password_hash()
    assert first is second  # generated once, not per call
    assert first.startswith("$2")
    # Any password fails against it — it is a hash of a random secret.
    assert verify_password("whatever", first) is False


# ── 6. AMM fills leave a Trade row, volume is USDC ────────────────────────────


@pytest.mark.asyncio
async def test_amm_buy_writes_trade_row_and_usdc_volume(db_session, test_user, test_market):
    """A market BUY that the book cannot fill still records the AMM leg."""
    from sqlalchemy import select

    from app.models.market import Market
    from app.models.trade import Trade
    from app.schemas.order import OrderRequest
    from app.services.order_service import OrderService

    market_before = (
        await db_session.execute(select(Market).where(Market.id == test_market.id))
    ).scalar_one()
    volume_before = market_before.total_volume
    num_trades_before = market_before.num_trades
    trades_before = len(
        (
            await db_session.execute(
                select(Trade).where(Trade.market_id == test_market.id)
            )
        ).scalars().all()
    )

    result = await OrderService.execute_order(
        db_session,
        test_user,
        OrderRequest(
            market_id=str(test_market.id),
            outcome="yes",
            side="buy",
            order_type="market",
            amount=Decimal(10),
        ),
    )
    assert result.status == "filled"

    trades = (
        await db_session.execute(select(Trade).where(Trade.market_id == test_market.id))
    ).scalars().all()
    assert len(trades) == trades_before + 1, "AMM buy leg must produce one Trade row"

    market = (
        await db_session.execute(select(Market).where(Market.id == test_market.id))
    ).scalar_one()
    # Volume must grow by the USDC SPENT (10), never by the share count the
    # AMM handed out — volume is a dollar figure everywhere it is displayed.
    assert market.total_volume == volume_before + Decimal(10)
    assert market.num_trades == num_trades_before + 1


@pytest.mark.asyncio
async def test_create_market_initial_probability_is_not_inverted(
    client, admin_user, db_session
):
    """initial_probability=0.7 must open the pool at price(YES)=0.70."""
    from datetime import UTC, datetime, timedelta

    from conftest import token_for
    from sqlalchemy import select

    from app.models.liquidity import LiquidityPool

    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.post("/api/v1/markets/", json={
        "question": "Will the inverter hold at 70 percent?",
        "description": "Seeded with an explicit starting probability.",
        "category": "test",
        "slug": "initial-probability-inverter-test",
        "closes_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        "initial_liquidity": 100,
        "initial_probability": 0.70,
    })
    assert resp.status_code == 200, resp.text

    pools = (await db_session.execute(select(LiquidityPool))).scalars().all()
    assert len(pools) == 1, f"expected exactly one seeded pool, got {len(pools)}"
    pool = pools[0]
    total = pool.yes_shares + pool.no_shares
    assert float(pool.yes_shares / total) == pytest.approx(0.70, abs=0.001)
