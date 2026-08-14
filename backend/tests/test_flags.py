"""Tests for flag endpoints."""
import pytest
import uuid

from httpx import AsyncClient


def _token(user_id: str) -> str:
    from app.deps import create_access_token
    t, _ = create_access_token(str(user_id))
    return t


# ── Flag market ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_flag_market_success(client: AsyncClient, test_user, test_market):
    """User can flag a market with a reason."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/flags", json={
        "market_id": str(test_market.id),
        "reason": "Inappropriate content",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["reason"] == "Inappropriate content"
    assert data["data"]["status"] == "open"


@pytest.mark.asyncio
async def test_flag_market_duplicate_rejected(client: AsyncClient, test_user, test_market):
    """Same user cannot flag the same market twice."""
    client.cookies.set("access_token", _token(test_user.id))
    await client.post("/api/v1/flags", json={
        "market_id": str(test_market.id),
        "reason": "First flag",
    })
    resp = await client.post("/api/v1/flags", json={
        "market_id": str(test_market.id),
        "reason": "Second flag",
    })
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_flag_nonexistent_market(client: AsyncClient, test_user):
    """Flagging non-existent market returns 404."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/flags", json={
        "market_id": str(uuid.uuid4()),
        "reason": "No market",
    })
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_flag_unauthenticated(client: AsyncClient, test_market):
    """Unauthenticated users cannot flag markets."""
    resp = await client.post("/api/v1/flags", json={
        "market_id": str(test_market.id),
        "reason": "Spam",
    })
    assert resp.status_code == 401


# ── Get market flags ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_market_flags_admin(client: AsyncClient, admin_user, test_user, test_market, db_session):
    """Admin can view all flags for a market."""
    from app.models.flag import MarketFlag

    flag = MarketFlag(market_id=test_market.id, user_id=test_user.id, reason="Spam")
    db_session.add(flag)
    await db_session.commit()
    await db_session.refresh(flag)

    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.get(f"/api/v1/flags/market/{test_market.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]) == 1
    assert data["data"][0]["reason"] == "Spam"


@pytest.mark.asyncio
async def test_get_market_flags_non_admin_forbidden(client: AsyncClient, test_user, test_market):
    """Non-admin cannot view flags."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get(f"/api/v1/flags/market/{test_market.id}")
    assert resp.status_code == 403


# ── Resolve flag ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_flag_admin(client: AsyncClient, admin_user, test_user, test_market, db_session):
    """Admin can resolve a flag with status 'dismissed' or 'actioned'."""
    from app.models.flag import MarketFlag

    flag = MarketFlag(market_id=test_market.id, user_id=test_user.id, reason="Spam")
    db_session.add(flag)
    await db_session.commit()
    await db_session.refresh(flag)

    client.cookies.set("access_token", _token(admin_user.id))

    resp = await client.patch(f"/api/v1/flags/{flag.id}/resolve", json={"status": "dismissed"})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "dismissed"


@pytest.mark.asyncio
async def test_resolve_flag_non_admin_forbidden(client: AsyncClient, test_user, test_market, db_session):
    """Non-admin cannot resolve flags."""
    from app.models.flag import MarketFlag

    flag = MarketFlag(market_id=test_market.id, user_id=test_user.id, reason="Spam")
    db_session.add(flag)
    await db_session.commit()
    await db_session.refresh(flag)

    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.patch(f"/api/v1/flags/{flag.id}/resolve", json={"status": "dismissed"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_resolve_flag_already_resolved(client: AsyncClient, admin_user, test_user, test_market, db_session):
    """Cannot resolve an already-resolved flag."""
    from app.models.flag import MarketFlag

    flag = MarketFlag(market_id=test_market.id, user_id=test_user.id, reason="Spam", status="dismissed")
    db_session.add(flag)
    await db_session.commit()
    await db_session.refresh(flag)

    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.patch(f"/api/v1/flags/{flag.id}/resolve", json={"status": "actioned"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_resolve_nonexistent_flag(client: AsyncClient, admin_user):
    """Resolving non-existent flag returns 404."""
    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.patch(f"/api/v1/flags/{uuid.uuid4()}/resolve", json={"status": "dismissed"})
    assert resp.status_code == 404
