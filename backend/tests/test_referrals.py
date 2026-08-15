"""Tests for referral endpoints."""
import pytest

from httpx import AsyncClient


def _token(user_id: str) -> str:
    from app.deps import create_access_token
    t, _ = create_access_token(str(user_id))
    return t


# ── Referral code ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_referral_code(client: AsyncClient, test_user):
    """Getting referral code creates one if missing."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/referrals/code")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "referral_code" in data["data"]


@pytest.mark.asyncio
async def test_get_referral_code_unauthenticated(client: AsyncClient):
    """Unauthenticated request is rejected."""
    resp = await client.get("/api/v1/referrals/code")
    assert resp.status_code == 401


# ── Referral stats ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_referral_stats(client: AsyncClient, test_user):
    """User can get their referral stats."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/referrals/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "total_referrals" in data["data"]
    assert "referral_code" in data["data"]


@pytest.mark.asyncio
async def test_get_referral_stats_unauthenticated(client: AsyncClient):
    """Unauthenticated request is rejected."""
    resp = await client.get("/api/v1/referrals/stats")
    assert resp.status_code == 401
