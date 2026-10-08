"""Auth endpoint tests."""
import time

import pytest
from conftest import token_for
from httpx import AsyncClient
from sqlalchemy import select

from app.models.user import User

# ── Helpers ───────────────────────────────────────────────────────────────────

# ── Registration ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_success(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "email": "newuser@example.com",
        "username": "newuser",
        "password": "MyStr0ng!Pass",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["email"] == "newuser@example.com"
    # Registration never returns an account id: the response has to be
    # identical whether or not the address already existed (see the
    # duplicate-email test below).
    assert data["data"]["status"] == "pending_verification"
    assert data["message"] == "Check your email to continue"


@pytest.mark.asyncio
async def test_register_weak_password(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "email": "weak@example.com",
        "username": "weakuser",
        "password": "123",
    })
    assert resp.status_code == 422
    data = resp.json()
    assert data["success"] is False
    assert data["error_code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_register_short_username(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "email": "short@example.com",
        "username": "ab",
        "password": "MyStr0ng!Pass",
    })
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_register_duplicate_email_is_not_enumerable(client: AsyncClient, test_user, db_session):
    """Registering an address that already has a *verified* account must be
    indistinguishable from registering a new one.

    It used to answer 409 "An account with this email already exists. Please
    sign in." • a free oracle for "does this person have an account here?",
    which is exactly what login brute-force tooling wants. The owner is told
    by email instead; the HTTP response never changes shape.
    """
    existing = await client.post("/api/v1/auth/register", json={
        "email": test_user.email,
        "username": "someoneelse",
        "password": "MyStr0ng!Pass",
    })
    fresh = await client.post("/api/v1/auth/register", json={
        "email": "brand.new.person@example.com",
        "username": "brandnewperson",
        "password": "MyStr0ng!Pass",
    })

    assert existing.status_code == 200, existing.text
    assert fresh.status_code == 200, fresh.text

    a, b = existing.json(), fresh.json()
    assert a["success"] is True and b["success"] is True
    # Same message, same data keys, same status • only the echoed email differs.
    assert a["message"] == b["message"]
    assert set(a["data"]) == set(b["data"]) == {"email", "status"}
    assert a["data"]["status"] == b["data"]["status"] == "pending_verification"
    assert a["data"]["email"] == test_user.email
    assert b["data"]["email"] == "brand.new.person@example.com"

    # The duplicate attempt must not have created a second account.
    rows = (await db_session.execute(
        select(User).where(User.email == test_user.email)
    )).scalars().all()
    assert len(rows) == 1


# ── Login ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, test_user):
    resp = await client.post("/api/v1/auth/login", json={
        "email": test_user.email,
        "password": "User!Pass1",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["email"] == test_user.email


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, test_user):
    resp = await client.post("/api/v1/auth/login", json={
        "email": test_user.email,
        "password": "Wrong!Pass1",
    })
    assert resp.status_code == 401
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: AsyncClient):
    resp = await client.post("/api/v1/auth/login", json={
        "email": "ghost@example.com",
        "password": "Any!Pass1",
    })
    assert resp.status_code == 401
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_login_inactive_user(db_session):
    from app.deps import hash_password
    from app.models.user import User
    user = User(
        email="inactive@example.com",
        username="inactive",
        password_hash=hash_password("MyStr0ng!Pass"),
        is_email_verified=True,
        is_active=False,
    )
    db_session.add(user)
    await db_session.commit()

    from httpx import ASGITransport, AsyncClient

    from app.app import app
    from app.database import get_db

    async def override():
        yield db_session
    app.dependency_overrides[get_db] = override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post("/api/v1/auth/login", json={
            "email": "inactive@example.com",
            "password": "MyStr0ng!Pass",
        })
    app.dependency_overrides.clear()
    assert resp.status_code == 401
    assert resp.json()["success"] is False


# ── 2FA ────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_setup_2fa(client: AsyncClient, test_user):
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.get("/api/v1/auth/2fa/setup")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "uri" in data["data"]
    assert data["data"]["uri"].startswith("otpauth://")


@pytest.mark.asyncio
async def test_2fa_status(client: AsyncClient, test_user):
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.get("/api/v1/auth/2fa/status")
    assert resp.status_code == 200
    assert resp.json()["data"]["is_2fa_enabled"] is False


@pytest.mark.asyncio
async def test_2fa_enable_wrong_code(client: AsyncClient, test_user):
    client.cookies.set("access_token", token_for(test_user.id))
    # First set up
    await client.get("/api/v1/auth/2fa/setup")
    # Try enable with wrong code
    resp = await client.post("/api/v1/auth/2fa/enable", json={"code": "000000"})
    assert resp.status_code == 401
    assert resp.json()["success"] is False


# ── Me / Sessions ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_me_authenticated(client: AsyncClient, test_user):
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["data"]["email"] == test_user.email


@pytest.mark.asyncio
async def test_me_unauthenticated(client: AsyncClient):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_sessions_list(client: AsyncClient, test_user):
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.get("/api/v1/auth/sessions")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ── Logout ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_logout(client: AsyncClient, test_user):
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_logout_all(client: AsyncClient, test_user):
    """logout_all invalidates all sessions."""
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.post("/api/v1/auth/logout-all")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ── Change password ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_change_password_success(client: AsyncClient, test_user):
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.post("/api/v1/auth/change-password", json={
        "old_password": "User!Pass1",
        "new_password": "New!Str0ngPass",
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_change_password_wrong_old(client: AsyncClient, test_user):
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.post("/api/v1/auth/change-password", json={
        "old_password": "Wrong!Old1",
        "new_password": "New!Str0ngPass",
    })
    assert resp.status_code == 401
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_change_password_same_as_old(client: AsyncClient, test_user):
    """Changing password to the same value should either succeed (re-issuing token) or reject."""
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.post("/api/v1/auth/change-password", json={
        "old_password": "User!Pass1",
        "new_password": "User!Pass1",
    })
    # Either 200 (re-issues token) or 400 (rejected) are acceptable
    assert resp.status_code in (200, 400)
    if resp.status_code == 200:
        assert resp.json()["success"] is True


# ── Edge cases ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_invalid_email(client: AsyncClient):
    """Email that is not a valid email format should be rejected."""
    resp = await client.post("/api/v1/auth/register", json={
        "email": "notanemail",
        "username": "validuser",
        "password": "MyStr0ng!Pass",
    })
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_register_password_same_as_username(client: AsyncClient):
    """Password identical to username should be rejected as weak."""
    resp = await client.post("/api/v1/auth/register", json={
        "email": "same@example.com",
        "username": "sameuser",
        "password": "sameuser",
    })
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_login_missing_password(client: AsyncClient, test_user):
    """Login with missing password field should be rejected."""
    resp = await client.post("/api/v1/auth/login", json={
        "email": test_user.email,
    })
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_logout_all_token_revoked(client: AsyncClient, test_user):
    """After logout_all, the old token should be blacklisted and subsequent requests fail."""
    client.cookies.set("access_token", token_for(test_user.id))

    # Verify token works before logout_all
    me_resp = await client.get("/api/v1/auth/me")
    assert me_resp.status_code == 200

    # Logout all
    logout_resp = await client.post("/api/v1/auth/logout-all")
    assert logout_resp.status_code == 200
    assert logout_resp.json()["success"] is True

    # Same token should now be rejected
    me_resp2 = await client.get("/api/v1/auth/me")
    assert me_resp2.status_code == 401
    assert me_resp2.json()["success"] is False


# ── Refresh-chain absolute cap ────────────────────────────────────────────────
# Rotation mints a new token with a new expiry every time, so the per-token TTL
# alone lets a client renew forever. The chain carries a deadline in Redis that
# rotation inherits instead of resetting.


def _cookie_value(resp, name: str) -> str:
    """Pull one cookie out of a response's Set-Cookie headers.

    The auth cookies are scoped to Domain=localhost, and httpx's jar drops a
    cookie whose domain does not match the request host (tests hit
    `testserver`) • so read the header directly instead of the jar.
    """
    prefix = f"{name}="
    for header in resp.headers.get_list("set-cookie"):
        if header.startswith(prefix):
            return header[len(prefix):].split(";", 1)[0]
    return ""


async def _login(client: AsyncClient, user) -> str:
    resp = await client.post("/api/v1/auth/login", json={
        "email": user.email,
        "password": "User!Pass1",
    })
    assert resp.status_code == 200, resp.text
    token = _cookie_value(resp, "refresh_token")
    assert token, "login must set the refresh cookie"
    # Hand it back to the client so /auth/refresh receives it as a cookie.
    client.cookies.set("refresh_token", token)
    return token


@pytest.mark.asyncio
async def test_refresh_rotation_inherits_the_chain_deadline(client: AsyncClient, test_user):
    """A rotated token must keep the original chain deadline • renewing the
    session cannot buy it more time than the login granted."""
    from app.api.auth import _hash_refresh_token, _refresh_chain_deadline

    first = await _login(client, test_user)
    deadline_before = await _refresh_chain_deadline(_hash_refresh_token(first))
    assert deadline_before is not None, "login must record a chain anchor"

    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 200, resp.text
    second = _cookie_value(resp, "refresh_token")
    assert second and second != first, "refresh must rotate the cookie"
    client.cookies.set("refresh_token", second)

    deadline_after = await _refresh_chain_deadline(_hash_refresh_token(second))
    assert deadline_after is not None
    # Same absolute instant (the write happens in the same request), i.e.
    # inherited rather than restarted.
    assert abs(deadline_after - deadline_before) <= 1
    assert deadline_after > time.time()


@pytest.mark.asyncio
async def test_refresh_chain_stops_at_the_absolute_deadline(
    client: AsyncClient, test_user, db_session
):
    """Past the chain deadline the refresh is refused AND the whole chain is
    revoked • not just the presented token."""
    from sqlalchemy import select

    from app.api.auth import _chain_key, _hash_refresh_token
    from app.models.user import RefreshToken, Session
    from app.redis import get_redis

    await _login(client, test_user)

    # Pretend the chain started long enough ago to be over.
    r = await get_redis()
    await r.set(_chain_key(_hash_refresh_token(client.cookies.get("refresh_token", domain=""))),
                str(time.time() - 60))

    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401, resp.text
    assert resp.json()["success"] is False

    tokens = (await db_session.execute(
        select(RefreshToken).where(RefreshToken.user_id == test_user.id)
    )).scalars().all()
    assert tokens and all(t.revoked for t in tokens), "chain deadline must revoke every token"

    sessions = (await db_session.execute(
        select(Session).where(Session.user_id == test_user.id)
    )).scalars().all()
    assert sessions and all(s.revoked for s in sessions), "chain deadline must revoke every session"
