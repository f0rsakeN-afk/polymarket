"""Tests for admin endpoints."""
import pytest
from uuid import uuid4

from httpx import AsyncClient


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _token(user_id: str) -> str:
    from app.deps import create_access_token
    t, _ = create_access_token(str(user_id))
    return t


# ── List users ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_users_admin(client: AsyncClient, admin_user):
    """Admin can list users."""
    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.get("/api/v1/admin/users")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "data" in data
    assert isinstance(data["data"], list)


@pytest.mark.asyncio
async def test_list_users_admin_pagination(client: AsyncClient, admin_user, test_user):
    """Admin can paginate user list."""
    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.get("/api/v1/admin/users?page=1&page_size=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["page"] == 1
    assert data["page_size"] == 5


@pytest.mark.asyncio
async def test_list_users_admin_search(client: AsyncClient, admin_user, test_user):
    """Admin can search users by email or username."""
    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.get(f"/api/v1/admin/users?search={test_user.email}")
    assert resp.status_code == 200
    data = resp.json()
    assert any(u["email"] == test_user.email for u in data["data"])


@pytest.mark.asyncio
async def test_list_users_empty_search(client: AsyncClient, admin_user):
    """Empty search returns all users."""
    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.get("/api/v1/admin/users?search=")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert isinstance(data["data"], list)


@pytest.mark.asyncio
async def test_list_users_page_beyond_total(client: AsyncClient, admin_user):
    """Page beyond total returns empty data."""
    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.get("/api/v1/admin/users?page=999")
    assert resp.status_code == 200
    data = resp.json()
    assert data["data"] == []


@pytest.mark.asyncio
async def test_list_users_non_admin_forbidden(client: AsyncClient, test_user):
    """Non-admin cannot list users."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/admin/users")
    assert resp.status_code == 403


# ── Get user ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_user_admin(client: AsyncClient, admin_user, test_user):
    """Admin can get any user's details."""
    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.get(f"/api/v1/admin/users/{test_user.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["data"]["email"] == test_user.email


@pytest.mark.asyncio
async def test_get_user_not_found(client: AsyncClient, admin_user):
    """Admin gets 404 for non-existent user."""
    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.get(f"/api/v1/admin/users/{uuid4()}")
    assert resp.status_code == 404


# ── Ban / Unban ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ban_user_admin(client: AsyncClient, admin_user, test_user):
    """Admin can ban a user."""
    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.patch(f"/api/v1/admin/users/{test_user.id}/ban")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "banned"


@pytest.mark.asyncio
async def test_ban_user_not_found(client: AsyncClient, admin_user):
    """Ban on non-existent user returns 404."""
    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.patch(f"/api/v1/admin/users/{uuid4()}/ban")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unban_user_not_found(client: AsyncClient, admin_user):
    """Unban on non-existent user returns 404."""
    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.patch(f"/api/v1/admin/users/{uuid4()}/unban")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_ban_admin_forbidden(client: AsyncClient, admin_user):
    """Admin cannot ban another admin."""
    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.patch(f"/api/v1/admin/users/{admin_user.id}/ban")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_ban_non_admin_forbidden(client: AsyncClient, test_user, admin_user):
    """Non-admin cannot ban users."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.patch(f"/api/v1/admin/users/{test_user.id}/ban")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_unban_user_admin(client: AsyncClient, admin_user, db_session):
    """Admin can unban a user."""
    from app.models.user import User
    # Create and ban a user
    from app.deps import hash_password
    uid = uuid4().hex[:8]
    user = User(
        email=f"banned_{uid}@example.com",
        username=f"banned_{uid}",
        password_hash=hash_password("User!Pass1"),
        is_email_verified=True,
        is_active=False,  # banned
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.patch(f"/api/v1/admin/users/{user.id}/unban")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "unbanned"


# ── Audit events ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_audit_events_admin(client: AsyncClient, admin_user):
    """Admin can list audit events."""
    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.get("/api/v1/admin/audit-events")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "data" in data


@pytest.mark.asyncio
async def test_list_audit_events_non_admin_forbidden(client: AsyncClient, test_user):
    """Non-admin cannot list audit events."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/admin/audit-events")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_audit_events_combined_filter(client: AsyncClient, admin_user):
    """Audit events can be filtered by event type and success/failure combined."""
    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.get("/api/v1/admin/audit-events?event=login&success=failure")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True


@pytest.mark.asyncio
async def test_list_audit_events_invalid_user_id(client: AsyncClient, admin_user):
    """Audit events with invalid UUID user_id returns 400."""
    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.get("/api/v1/admin/audit-events?user_id=invalid-uuid")
    assert resp.status_code == 422  # ValidationError → 422 via handler


# ── Distribute protocol fees ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_distribute_protocol_fees_admin(client: AsyncClient, admin_user):
    """Admin can distribute protocol fees."""
    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.post("/api/v1/admin/distribute-protocol-fees")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_distribute_protocol_fees_non_admin_forbidden(client: AsyncClient, test_user):
    """Non-admin cannot distribute protocol fees."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/admin/distribute-protocol-fees")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_distribute_protocol_fees_empty(client: AsyncClient, admin_user):
    """Distributing when there are no fees returns empty result."""
    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.post("/api/v1/admin/distribute-protocol-fees")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["total_distributed"] == "0.0"
    assert data["data"]["markets"] == []
