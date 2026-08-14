"""Tests for notification endpoints."""
import pytest
import uuid

from httpx import AsyncClient


def _token(user_id: str) -> str:
    from app.deps import create_access_token
    t, _ = create_access_token(str(user_id))
    return t


# ── Preferences ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_preferences(client: AsyncClient, test_user):
    """Authenticated user can get notification preferences."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/notifications/preferences")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "email_alerts" in data["data"]


@pytest.mark.asyncio
async def test_update_preferences(client: AsyncClient, test_user):
    """User can update notification preferences."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.put("/api/v1/notifications/preferences", json={
        "email_alerts": False,
        "push_market_resolution": True,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True


@pytest.mark.asyncio
async def test_update_preferences_unauthenticated(client: AsyncClient):
    """Unauthenticated request is rejected."""
    resp = await client.put("/api/v1/notifications/preferences", json={"email_alerts": False})
    assert resp.status_code == 401


# ── List notifications ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_notifications(client: AsyncClient, test_user):
    """Authenticated user can list their notifications."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/notifications")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "data" in data


@pytest.mark.asyncio
async def test_list_notifications_pagination(client: AsyncClient, test_user):
    """Notifications list is paginated."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/notifications?page=1&page_size=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["page"] == 1
    assert data["page_size"] == 5


@pytest.mark.asyncio
async def test_list_notifications_unauthenticated(client: AsyncClient):
    """Unauthenticated request is rejected."""
    resp = await client.get("/api/v1/notifications")
    assert resp.status_code == 401


# ── Mark read ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mark_notification_read(client: AsyncClient, test_user):
    """Marking a notification as read returns 200 or 404 (idempotent)."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post(f"/api/v1/notifications/{uuid.uuid4()}/read")
    # Non-existent notification — returns 404
    assert resp.status_code in (200, 404)


@pytest.mark.asyncio
async def test_mark_notification_read_unauthenticated(client: AsyncClient):
    """Unauthenticated request is rejected."""
    resp = await client.post(f"/api/v1/notifications/{uuid.uuid4()}/read")
    assert resp.status_code == 401


# ── Mark all read ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mark_all_read(client: AsyncClient, test_user):
    """Marking all notifications as read succeeds."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/notifications/read-all")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_mark_all_read_unauthenticated(client: AsyncClient):
    """Unauthenticated request is rejected."""
    resp = await client.post("/api/v1/notifications/read-all")
    assert resp.status_code == 401
