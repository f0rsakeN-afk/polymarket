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
7. `/auth/refresh` shared the 3/min credential-decision rate-limit bucket, so a
   burst of 401s locked a signed-in client out of rotating its own token.
8. Auth cookies were tagged `Domain=localhost` in dev, which RFC 6265 cookie
   stores reject — so a real client silently dropped the session it was just
   given (every test injected the token by hand and never saw it).
9. The public market/trades feeds required a token, gating data that the REST
   endpoints already serve anonymously — so logged-out visitors were refused and
   the client re-opened the refused socket on every backoff tick.
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
    default) the query token is ignored.

    "Ignored" now means different things on the two kinds of socket, so both are
    checked:

    - **Public feed** — the token is dropped, so the caller is simply anonymous
      and the connection is allowed (it carries nothing private anyway).
    - **Personal feed** — the token is the *only* thing authorising delivery, so
      ignoring it means the connection is refused. This is where the property
      actually matters, and it is asserted with a token that is otherwise valid.
    """
    from unittest.mock import AsyncMock, patch

    from app.config import settings

    monkeypatch.setattr(settings, "ws_allow_query_token", False)
    token = token_for(test_user.id)

    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_global_trades = AsyncMock()
        # Public feed: a valid token in the URL is not honoured, but the socket
        # itself is public and connects.
        with ws_client.websocket_connect(f"/ws/trades?token={token}") as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"

    # Personal feed: same ignored query token, but nothing else identifies the
    # caller, so it must be refused.
    with pytest.raises(WebSocketDisconnect) as exc:
        with ws_client.websocket_connect(f"/ws/notifications/{test_user.id}?token={token}"):
            pass
    assert exc.value.code == 4001

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


# ── 4b. Token refresh must not share the credential-decision bucket ────────────


def test_refresh_has_its_own_rate_limit_bucket():
    """`/auth/refresh` must not be capped like a password-reset request.

    It used to fall through to `AUTH_FAST` (3/min), a bucket sized for endpoints
    that send an email or reveal whether an account exists. A signed-in client
    that hit a burst of 401s — a flaky network, a laptop waking from sleep with an
    expired access token, several components refetching at once — was therefore
    429'd and locked out of rotating its own live session.
    """
    from app.api.middleware import _get_auth_limit_type
    from app.services.rate_limit_service import LimitType, RateLimitService

    assert _get_auth_limit_type("/api/v1/auth/refresh") is LimitType.AUTH_REFRESH

    refresh_limit, _window = RateLimitService._LIMITS[LimitType.AUTH_REFRESH]
    fast_limit, _fast_window = RateLimitService._LIMITS[LimitType.AUTH_FAST]
    assert refresh_limit > fast_limit

    # The abuse-sensitive endpoints keep their tight caps.
    assert (
        _get_auth_limit_type("/api/v1/auth/forgot-password")
        is LimitType.AUTH_FAST
    )
    assert (
        _get_auth_limit_type("/api/v1/auth/login") is LimitType.AUTH_DECISION
    )


# ── 4c. Auth cookies must survive a real cookie jar ───────────────────────────


def test_auth_cookies_are_accepted_by_a_standard_cookie_jar():
    """The issued cookies must actually be sent back on the next request.

    Every other test injects the token with `client.cookies.set(...)`, which
    skips `Set-Cookie` parsing entirely — so nothing here would have caught the
    dev build tagging its cookies `Domain=localhost`. RFC 6265 stores reject
    that attribute outright (Python's `http.cookiejar`, and so httpx/requests,
    silently discard the cookie), which made a successful login look like an
    anonymous one on the following request.

    Cookie scope is host-based and ignores ports, so no `Domain` attribute is
    needed for `localhost:3000 → localhost:8000`; this asserts the real thing —
    that a standards-compliant jar keeps the cookie and replays it.
    """
    import email
    import http.cookiejar
    from urllib.request import Request as UrlRequest

    from starlette.responses import Response

    from app.config import settings
    from app.deps import clear_auth_cookies, set_auth_cookies

    was_prod = settings.app_env
    settings.app_env = "development"
    try:
        resp = Response()
        set_auth_cookies(resp, access_token="ACCESS", refresh_token="REFRESH")

        set_cookie_headers = [
            v.decode() for k, v in resp.raw_headers
            if k.decode().lower() == "set-cookie"
        ]
        assert len(set_cookie_headers) == 2, set_cookie_headers

        # No Domain attribute on either cookie.
        for header in set_cookie_headers:
            assert "domain=" not in header.lower(), header
            assert "httponly" in header.lower(), header
            assert "samesite=lax" in header.lower(), header

        # Feed them to a real jar the way a real client does, then ask what it
        # would send on a follow-up request to the same host.
        jar = http.cookiejar.CookieJar()
        message = email.message_from_string(
            "".join(f"Set-Cookie: {h}\n" for h in set_cookie_headers)
        )
        response = type("R", (), {"info": lambda _self: message})()

        def _request(host: str) -> UrlRequest:
            req = UrlRequest(f"http://{host}/api/v1/auth/me")
            req.add_unredirected_header("Host", host)
            return req

        jar.extract_cookies(response, _request("localhost:8000"))
        assert {c.name for c in jar} == {"access_token", "refresh_token"}

        follow_up = _request("localhost:8000")
        jar.add_cookie_header(follow_up)
        sent = follow_up.get_header("Cookie")
        assert sent and "access_token=ACCESS" in sent, sent
        assert "refresh_token=REFRESH" in sent, sent

        # clear_auth_cookies must mirror what set_auth_cookies wrote, or the
        # browser keeps a cookie the server believes it deleted.
        clear = Response()
        clear_auth_cookies(clear)
        deletions = [
            v.decode() for k, v in clear.raw_headers
            if k.decode().lower() == "set-cookie"
        ]
        assert len(deletions) == 2
        for header in deletions:
            assert "Max-Age=0" in header or "max-age=0" in header, header
            assert "domain=" not in header.lower(), header
    finally:
        settings.app_env = was_prod


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
