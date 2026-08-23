"""Auth endpoint tests."""
import pytest
from httpx import AsyncClient


# ── Helpers ───────────────────────────────────────────────────────────────────

def _token(user_id: str) -> str:
    from app.deps import create_access_token
    t, _ = create_access_token(str(user_id))
    return t


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
    assert "id" in data["data"]


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
async def test_register_duplicate_email(client: AsyncClient, test_user):
    resp = await client.post("/api/v1/auth/register", json={
        "email": test_user.email,
        "username": "anotheruser",
        "password": "MyStr0ng!Pass",
    })
    assert resp.status_code == 409
    assert resp.json()["success"] is False
    assert "already exists" in resp.json()["error"]


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
    from app.models.user import User
    from app.deps import hash_password
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
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/auth/2fa/setup")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "uri" in data["data"]
    assert data["data"]["uri"].startswith("otpauth://")


@pytest.mark.asyncio
async def test_2fa_status(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/auth/2fa/status")
    assert resp.status_code == 200
    assert resp.json()["data"]["is_2fa_enabled"] is False


@pytest.mark.asyncio
async def test_2fa_enable_wrong_code(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    # First set up
    await client.get("/api/v1/auth/2fa/setup")
    # Try enable with wrong code
    resp = await client.post("/api/v1/auth/2fa/enable", json={"code": "000000"})
    assert resp.status_code == 401
    assert resp.json()["success"] is False


# ── Me / Sessions ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_me_authenticated(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
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
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/auth/sessions")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ── Logout ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_logout(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_logout_all(client: AsyncClient, test_user):
    """logout_all invalidates all sessions."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/auth/logout-all")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ── Change password ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_change_password_success(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/auth/change-password", json={
        "old_password": "User!Pass1",
        "new_password": "New!Str0ngPass",
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_change_password_wrong_old(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/auth/change-password", json={
        "old_password": "Wrong!Old1",
        "new_password": "New!Str0ngPass",
    })
    assert resp.status_code == 401
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_change_password_same_as_old(client: AsyncClient, test_user):
    """Changing password to the same value should either succeed (re-issuing token) or reject."""
    client.cookies.set("access_token", _token(test_user.id))
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
    client.cookies.set("access_token", _token(test_user.id))

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
